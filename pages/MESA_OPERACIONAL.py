import streamlit as st
import pandas as pd
import requests
import urllib.parse
from datetime import datetime, time, date
from PIL import Image
from sqlalchemy import text

# ==============================================================================
# 1. CONFIGURAÇÃO DA PÁGINA
# ==============================================================================
st.set_page_config(page_title="Monitoramento de Faltas", layout="wide", page_icon="📉")

# ==============================================================================
# 2. SEGURANÇA E ESTADO
# ==============================================================================
if not st.session_state.get("authentication_status"):
    st.warning("🔒 Acesso restrito. Faça login na página inicial.")
    st.stop()

if 'mesa_dados' not in st.session_state:
    st.session_state['mesa_dados'] = None
if 'mesa_data_ref' not in st.session_state:
    st.session_state['mesa_data_ref'] = None

# Recupera Credenciais
try:
    TOKEN_FIXO = st.secrets["api_portal_gestor"]["token_fixo"]
    CD_OPERADOR = st.secrets["api_portal_gestor"].get("cd_operador", "033555692836")
    NR_ORG = st.secrets["api_portal_gestor"].get("nr_org", "3260")
except Exception as e:
    st.error("⚠️ Erro de Configuração: Credenciais da API não encontradas no secrets.toml.")
    st.stop()

# ==============================================================================
# 3. BANCO DE DADOS
# ==============================================================================
@st.cache_data(ttl=600)
def fetch_dados_auxiliares_db():
    try:
        conn = st.connection("postgres", type="sql")
        
        # 1. Relação Escola -> Supervisor (Fallback)
        q_unidades = """
        SELECT u."UnidadeID", s."NomeSupervisor" as "Supervisor"
        FROM "Unidades" u
        JOIN "Supervisores" s ON u."SupervisorID" = s."SupervisorID"
        """
        df_unidades = conn.query(q_unidades)
        df_unidades['UnidadeID'] = pd.to_numeric(df_unidades['UnidadeID'], errors='coerce').fillna(0).astype(int)
        
        # 2. Relação Supervisor -> Celular (DICIONÁRIO INFALÍVEL)
        q_telefones = 'SELECT "NomeSupervisor", "Celular" FROM "Supervisores"'
        df_telefones = conn.query(q_telefones)
        
        # Cria dicionário { 'CLAYTON': '119...', ... }
        map_telefones = dict(zip(
            df_telefones['NomeSupervisor'].str.strip().str.upper(), 
            df_telefones['Celular']
        ))
        
        return df_unidades, map_telefones
    except Exception as e:
        st.error(f"Erro DB: {e}")
        return pd.DataFrame(), {}

# ==============================================================================
# 4. API REQUISITION
# ==============================================================================
def fetch_mesa_operacional(data_selecionada):
    url = "https://portalgestor.teknisa.com/backend/index.php/getMesaOperacoes"
    
    data_str = data_selecionada.strftime("%d/%m/%Y")
    
    params = {
        "requestType": "FilterData",
        "DIA": data_str,
        "NRESTRUTURAM": "101091998", 
        "NRORG": NR_ORG,
        "CDOPERADOR": CD_OPERADOR
    }
    
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "OAuth-Token": TOKEN_FIXO,
        "OAuth-Cdoperador": CD_OPERADOR,
        "OAuth-Nrorg": NR_ORG
    }

    try:
        r = requests.get(url, params=params, headers=headers, timeout=30)
        if r.status_code == 200:
            data = r.json()
            if "dataset" in data and "data" in data["dataset"]:
                return pd.DataFrame(data["dataset"]["data"])
    except Exception as e:
        st.error(f"Erro API: {e}")
    
    return pd.DataFrame()

# ==============================================================================
# 5. PROCESSAMENTO INTELIGENTE
# ==============================================================================
def processar_dados_unificados(df_api, df_unidades, map_telefones, data_analise):
    if df_api.empty: return df_api

    if 'NMSITUFUNCH' in df_api.columns:
        df_api = df_api[df_api['NMSITUFUNCH'] == 'Atividade Normal'].copy()
    
    if df_api.empty: return df_api

    # 1. Ajuste de Tipos
    df_api['UnidadeID'] = pd.to_numeric(df_api['NRESTRUTGEREN'], errors='coerce').fillna(0).astype(int)
    
    # 2. Merge com Unidades (para garantir nome do supervisor se faltar na API)
    df_merged = pd.merge(df_api, df_unidades, on="UnidadeID", how="left")
    df_merged['Supervisor'] = df_merged['Supervisor'].fillna("Não Identificado")

    # 3. Injeção do Celular via Dicionário (Mais seguro que join)
    df_merged['Supervisor_Key'] = df_merged['Supervisor'].str.strip().str.upper()
    df_merged['Celular'] = df_merged['Supervisor_Key'].map(map_telefones)

    # 4. Renomear
    df_merged = df_merged.rename(columns={
        'NMESTRUTGEREN': 'Escola', 
        'NMVINCULOM': 'Funcionario',
        'NMOCUPACAOH': 'Cargo',
        'horas_trabalhadas': 'Batidas',
        'horas_escala': 'Escala',
        'OBSERVACAO': 'Obs'
    })

    # Lógica de Horário
    hoje = date.today()
    agora = datetime.now().time()
    eh_hoje = (data_analise == hoje)
    eh_passado = (data_analise < hoje)
    
    def extrair_hora_inicio(lista_escala):
        if not isinstance(lista_escala, list) or not lista_escala: return None
        try:
            str_hora = lista_escala[0][0] 
            h, m = map(int, str_hora.split(':'))
            return time(h, m)
        except: return None

    def get_status(row):
        batidas = row.get('Batidas')
        escala = row.get('Escala')
        
        # Tem batida? Presente
        tem_batida = isinstance(batidas, list) and len(batidas) > 0
        if tem_batida: return '🟢 Presente'

        # Não tem batida, analisa escala
        tem_escala = isinstance(escala, list) and len(escala) > 0
        if tem_escala:
            if eh_passado: return '🔴 Falta'
            if eh_hoje:
                hora_inicio = extrair_hora_inicio(escala)
                if hora_inicio:
                    if agora >= hora_inicio: return '🔴 Falta' # Atrasado = Falta até chegar
                    else: return '⏳ A Iniciar'
                else: return '🔴 Falta' # Escala quebrada
            return '⏳ A Iniciar'
                
        return '🟡 S/ Escala'

    df_merged['Status_Individual'] = df_merged.apply(get_status, axis=1)

    def format_hora(lista):
        if not isinstance(lista, list) or not lista: return "-"
        try: return " | ".join([f"{x[0]}-{x[1]}" for x in lista if len(x) == 2])
        except: return "-"

    df_merged['Escala_Formatada'] = df_merged['Escala'].apply(format_hora)
    df_merged['Ponto_Real'] = df_merged['Batidas'].apply(format_hora)
    
    return df_merged

# ==============================================================================
# 6. FUNCIONALIDADE WHATSAPP (COM ORDENAÇÃO E TOTALIZADORES)
# ==============================================================================
def gerar_link_whatsapp(telefone, mensagem):
    # Garante que a mensagem esteja em utf-8 antes de codificar para URL
    texto_encoded = urllib.parse.quote(mensagem)
    fone_limpo = "".join(filter(str.isdigit, str(telefone))) if telefone else ""
    return f"https://wa.me/55{fone_limpo}?text={texto_encoded}"

@st.dialog("📢 Central de Alertas", width="large")
def dialog_disparar_alertas(df_completo):
    st.caption("Envie mensagens para os supervisores. Prioriza escolas com possível problema de aparelho.")
    
    # 1. Filtra apenas as linhas com FALTA
    df_faltas_bruto = df_completo[df_completo['Status_Individual'] == '🔴 Falta']
    
    if df_faltas_bruto.empty:
        st.success("🎉 Nenhuma falta registrada para alerta no momento!")
        return

    supervisores_com_falta = sorted(df_faltas_bruto['Supervisor'].unique())
    
    for supervisor in supervisores_com_falta:
        with st.container(border=True):
            c1, c2 = st.columns([3, 1])
            
            # Dados deste supervisor
            df_sup_faltas = df_faltas_bruto[df_faltas_bruto['Supervisor'] == supervisor]
            df_sup_total = df_completo[df_completo['Supervisor'] == supervisor]
            
            # --- PREPARAÇÃO DOS DADOS (PARA ORDENAÇÃO) ---
            escolas_para_mensagem = []
            
            # Itera sobre cada escola que tem falta para classificar
            for escola, dados_falta in df_sup_faltas.groupby('Escola'):
                # Verifica se TEM ALGUMA PRESENÇA na escola (no dataframe total)
                tem_presenca = not df_sup_total[
                    (df_sup_total['Escola'] == escola) & 
                    (df_sup_total['Status_Individual'] == '🟢 Presente')
                ].empty
                
                eh_problema_app = not tem_presenca
                
                # Lista de nomes faltantes
                lista_nomes = dados_falta['Funcionario'].tolist()
                
                escolas_para_mensagem.append({
                    'escola': escola,
                    'is_problem': eh_problema_app,
                    'nomes': lista_nomes,
                    'qtd_faltas': len(lista_nomes)
                })
            
            # --- ORDENAÇÃO ---
            # Escolas com problema (True) aparecem primeiro
            escolas_para_mensagem.sort(key=lambda x: x['is_problem'], reverse=True)
            
            # --- CÁLCULO DOS TOTALIZADORES ---
            total_faltas = sum(e['qtd_faltas'] for e in escolas_para_mensagem)
            total_escolas_problema = sum(1 for e in escolas_para_mensagem if e['is_problem'])
            
            # --- MONTAGEM DA MENSAGEM ---
            msg_lines = [f"Olá *{supervisor}*, resumo de ausências ({datetime.now().strftime('%H:%M')}):"]
            
            # Adiciona Totalizadores no Cabeçalho
            msg_lines.append(f"📊 *Total Faltas:* {total_faltas}")
            if total_escolas_problema > 0:
                msg_lines.append(f"⚠️ *Escolas c/ Problema App:* {total_escolas_problema}")
            
            msg_lines.append("") # Linha em branco
            
            for item in escolas_para_mensagem:
                nomes_str = ", ".join(item['nomes'])
                
                if item['is_problem']:
                    cabecalho = f"🚨 *{item['escola']}* (⚠️ POSSÍVEL PROBLEMA SMARTPHONE)"
                else:
                    cabecalho = f"🏫 *{item['escola']}*"
                
                msg_lines.append(f"{cabecalho}\n🚫 {nomes_str}\n")
            
            msg_final = "\n".join(msg_lines).strip()
            
            # --- UI: EXIBIÇÃO NO STREAMLIT ---
            telefone_bruto = None
            if 'Celular' in df_sup_faltas.columns:
                val = df_sup_faltas['Celular'].iloc[0]
                if pd.notna(val) and str(val).strip() != "" and str(val).strip().lower() != "none":
                    telefone_bruto = val
            
            with c1:
                st.markdown(f"**👤 {supervisor}**")
                # Mostra os contadores visuais para o operador também
                kpi1, kpi2 = st.columns(2)
                kpi1.metric("Faltas", total_faltas)
                kpi2.metric("Escolas Críticas", total_escolas_problema)
                
                with st.expander("Ver mensagem gerada"):
                    st.code(msg_final, language=None)
            
            with c2:
                if telefone_bruto:
                    link = gerar_link_whatsapp(telefone_bruto, msg_final)
                    st.link_button("📲 Enviar WhatsApp", link, use_container_width=True)
                else:
                    st.warning("Sem Celular")
                    st.caption("Cadastre no Banco")

# ==============================================================================
# 7. UI - SIDEBAR
# ==============================================================================
def carregar_logo():
    try: return Image.open("logo.png")
    except: return None

if logo := carregar_logo(): 
    st.sidebar.image(logo, use_container_width=True)
st.sidebar.divider()

if "name" in st.session_state: 
    st.sidebar.write(f"👤 **{st.session_state['name']}**")
    st.sidebar.divider()

st.sidebar.markdown("### 📅 Configuração")
data_selecionada = st.sidebar.date_input("Data de Análise", datetime.now())

# Limpa cache se mudar data
if st.session_state['mesa_data_ref'] != data_selecionada:
    st.session_state['mesa_dados'] = None 

# --- BOTÃO DE ATUALIZAR ---
if st.sidebar.button("🔄 Atualizar Dados", use_container_width=True):
    st.session_state['mesa_dados'] = None
    st.cache_data.clear()
    st.rerun()

# ==============================================================================
# 8. CARREGAMENTO DOS DADOS (ANTES DA INTERFACE PRINCIPAL)
# ==============================================================================
if st.session_state['mesa_dados'] is None:
    with st.spinner(f"Buscando dados de {data_selecionada.strftime('%d/%m/%Y')}..."):
        df_unidades, map_telefones = fetch_dados_auxiliares_db()
        raw_api = fetch_mesa_operacional(data_selecionada)
        df_proc = processar_dados_unificados(raw_api, df_unidades, map_telefones, data_selecionada)
        
        st.session_state['mesa_dados'] = df_proc
        st.session_state['mesa_data_ref'] = data_selecionada

df = st.session_state['mesa_dados']
data_exibicao = st.session_state['mesa_data_ref'].strftime("%d/%m/%Y")

# ==============================================================================
# 9. DASHBOARD PRINCIPAL
# ==============================================================================
st.title("📉 Monitoramento de Faltas")
st.caption(f"Dados referentes a: **{data_exibicao}**")

# --- BOTÃO DE DISPARO EM DESTAQUE ---
if df is not None and not df.empty:
    st.markdown("---")
    c_btn1, c_btn2 = st.columns([3, 1])
    with c_btn1:
        st.info("💡 Clique ao lado para notificar os supervisores sobre as faltas identificadas.")
    with c_btn2:
        if st.button("📢 Disparar Alertas", use_container_width=True):
            dialog_disparar_alertas(df)
    st.markdown("---")
# -----------------------------------------------------

# Filtro Supervisor
filtro_supervisor = "Todos"
if df is not None and not df.empty:
    opcoes = ["Todos"] + sorted(df['Supervisor'].unique().tolist())
    filtro_supervisor = st.sidebar.selectbox("Filtrar por Supervisor:", opcoes)

if df is not None and not df.empty:
    df_filtrado = df.copy()
    if filtro_supervisor != "Todos":
        df_filtrado = df_filtrado[df_filtrado['Supervisor'] == filtro_supervisor]

    if df_filtrado.empty:
        st.warning("Nenhum dado encontrado para o filtro selecionado.")
        st.stop()

    # --- KPIs ---
    qtd_presente = len(df_filtrado[df_filtrado['Status_Individual'] == '🟢 Presente'])
    qtd_falta = len(df_filtrado[df_filtrado['Status_Individual'] == '🔴 Falta'])
    qtd_a_entrar = len(df_filtrado[df_filtrado['Status_Individual'] == '⏳ A Iniciar'])
    qtd_efetivo = qtd_presente + qtd_falta + qtd_a_entrar

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Efetivo Esperado", qtd_efetivo)
    k2.metric("Presentes", qtd_presente)
    k3.metric("Faltas", qtd_falta, delta_color="inverse", help="Postos descobertos")
    k4.metric("Turnos a Iniciar", qtd_a_entrar, delta_color="normal")
    
    st.divider()

    # --- Tabela Agrupada ---
    resumo = df_filtrado.groupby(['Escola', 'Supervisor']).agg(
        Efetivo=('Status_Individual', 'count'), 
        Faltas=('Status_Individual', lambda x: (x == '🔴 Falta').sum()),
        Presentes=('Status_Individual', lambda x: (x == '🟢 Presente').sum()),
        A_Entrar=('Status_Individual', lambda x: (x == '⏳ A Iniciar').sum())
    ).reset_index()

    # --- Diagnóstico ---
    def definir_diagnostico(row):
        presentes = row['Presentes']
        faltas = row['Faltas']
        a_entrar = row['A_Entrar']
        
        if presentes == 0:
            if faltas > 0: return "⚠️ POSSÍVEL PROBLEMA SMARTPHONE"
            elif a_entrar > 0 and faltas == 0: return "🕒 AGUARDANDO INÍCIO"
            else: return "⚠️ VERIFICAR"
        
        if faltas == 0:
            if a_entrar == 0: return "🌟 ESCOLA COMPLETA"
            else: return "✅ PARCIAL (Aguardando Tarde/Noite)"
        
        base_calc = presentes + faltas
        if base_calc > 0:
            perc = (presentes / base_calc) * 100
            return f"{perc:.0f}% Presentes (Turno Atual)"
        return "-"

    resumo['Diagnostico'] = resumo.apply(definir_diagnostico, axis=1)

    # Ordenação
    def get_sort_key(row):
        d = row['Diagnostico']
        if "PROBLEMA" in d: return 0
        if "COMPLETA" in d: return 3
        if "AGUARDANDO" in d: return 2
        return 1

    resumo['sort_group'] = resumo.apply(get_sort_key, axis=1)
    resumo['perc_presenca'] = resumo['Presentes'] / (resumo['Efetivo'].replace(0, 1))
    resumo = resumo.sort_values(by=['sort_group', 'perc_presenca'], ascending=[True, True])

    # --- KPIs Diagnóstico ---
    qtd_problema = len(resumo[resumo['Diagnostico'].str.contains("PROBLEMA")])
    qtd_completas = len(resumo[resumo['Diagnostico'].str.contains("COMPLETA")])
    
    c_info1, c_info2 = st.columns(2)
    with c_info1:
        if qtd_problema > 0: st.error(f"🚨 **{qtd_problema}** escolas com possível problema no Smartphone.")
    with c_info2:
        if qtd_completas > 0: st.success(f"🌟 **{qtd_completas}** escolas com efetivo 100% completo.")

    # --- Tabela Visual ---
    st.markdown(f"### 🏫 Visão por Unidade ({filtro_supervisor})")
    
    event = st.dataframe(
        resumo[['Escola', 'Supervisor', 'Diagnostico', 'Efetivo', 'Presentes', 'Faltas', 'A_Entrar']],
        use_container_width=True,
        hide_index=True,
        selection_mode="single-row",
        on_select="rerun",
        column_config={
            "Escola": st.column_config.TextColumn("Escola", width="large"),
            "Diagnostico": st.column_config.TextColumn("Status", width="medium"),
            "Efetivo": st.column_config.NumberColumn("Total", format="%d 👤"),
            "Presentes": st.column_config.NumberColumn("Ok", format="%d 🟢"),
            "Faltas": st.column_config.NumberColumn("Faltas", format="%d 🔴"),
            "A_Entrar": st.column_config.NumberColumn("A Iniciar", format="%d ⏳"),
        }
    )

    # --- Popup Detalhe ---
    @st.dialog("Detalhe da Escola", width="large")
    def mostrar_detalhe(escola, supervisor, df_local, diag):
        st.subheader(f"🏫 {escola}")
        st.caption(f"Supervisor: {supervisor} | Status: {diag}")
        
        mapa_ordem = {'🔴 Falta': 0, '🟢 Presente': 1, '⏳ A Iniciar': 2, '🟡 S/ Escala': 3}
        df_local['ordem'] = df_local['Status_Individual'].map(mapa_ordem)
        df_show = df_local.sort_values('ordem')

        st.dataframe(
            df_show[['Status_Individual', 'Funcionario', 'Cargo', 'Escala_Formatada', 'Ponto_Real']],
            use_container_width=True,
            hide_index=True,
            column_config={
                "Status_Individual": st.column_config.TextColumn("Situação", width="small"),
                "Escala_Formatada": st.column_config.TextColumn("Escala Prevista", width="medium"),
                "Ponto_Real": st.column_config.TextColumn("Batidas", width="medium"),
            }
        )

    if len(event.selection.rows) > 0:
        idx = event.selection.rows[0]
        row = resumo.iloc[idx]
        df_detalhe = df_filtrado[df_filtrado['Escola'] == row['Escola']]
        mostrar_detalhe(row['Escola'], row['Supervisor'], df_detalhe, row['Diagnostico'])

elif df is not None and df.empty:
    st.info(f"Nenhum dado encontrado para a data {data_exibicao}.")