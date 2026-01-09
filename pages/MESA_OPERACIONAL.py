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

# Inicializa estado dos dados
if 'mesa_dados' not in st.session_state:
    st.session_state['mesa_dados'] = None
# Inicializa estado da data dos dados carregados
if 'mesa_data_ref' not in st.session_state:
    st.session_state['mesa_data_ref'] = None

# Recupera Credenciais (SEGURO: Apenas via Secrets)
try:
    TOKEN_FIXO = st.secrets["api_portal_gestor"]["token_fixo"]
    CD_OPERADOR = st.secrets["api_portal_gestor"].get("cd_operador", "033555692836")
    NR_ORG = st.secrets["api_portal_gestor"].get("nr_org", "3260")
except Exception as e:
    st.error("⚠️ Erro de Configuração: Credenciais da API não encontradas no secrets.toml.")
    st.stop()

# ==============================================================================
# 3. BANCO DE DADOS (CORRIGIDO PARA DICIONÁRIO)
# ==============================================================================
@st.cache_data(ttl=600)
def fetch_dados_auxiliares_db():
    try:
        conn = st.connection("postgres", type="sql")
        
        # 1. Busca relação Escola -> Supervisor (Nome) para fallback
        q_unidades = """
        SELECT u."UnidadeID", s."NomeSupervisor" as "Supervisor"
        FROM "Unidades" u
        JOIN "Supervisores" s ON u."SupervisorID" = s."SupervisorID"
        """
        df_unidades = conn.query(q_unidades)
        df_unidades['UnidadeID'] = pd.to_numeric(df_unidades['UnidadeID'], errors='coerce').fillna(0).astype(int)
        
        # 2. Busca TODOS os telefones direto da tabela Supervisores
        q_telefones = 'SELECT "NomeSupervisor", "Celular" FROM "Supervisores"'
        df_telefones = conn.query(q_telefones)
        
        # Cria dicionário { 'CLAYTON': '119...', 'SAULO': '119...' }
        # Normaliza para maiúsculo e sem espaços para garantir o match
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
    
    # Formata a data passada por parâmetro
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
# 5. PROCESSAMENTO INTELIGENTE (REGRA DE NEGÓCIO)
# ==============================================================================
def processar_dados_unificados(df_api, df_unidades, map_telefones, data_analise):
    if df_api.empty: return df_api

    # 1. Filtro: Atividade Normal
    if 'NMSITUFUNCH' in df_api.columns:
        df_api = df_api[df_api['NMSITUFUNCH'] == 'Atividade Normal'].copy()
    
    if df_api.empty: return df_api

    # 2. Merge com DB (UnidadeID = NRESTRUTGEREN)
    df_api['UnidadeID'] = pd.to_numeric(df_api['NRESTRUTGEREN'], errors='coerce').fillna(0).astype(int)
    
    # Merge com Unidades (para pegar supervisor se a API falhar ou complementar)
    df_merged = pd.merge(df_api, df_unidades, on="UnidadeID", how="left")
    df_merged['Supervisor'] = df_merged['Supervisor'].fillna("Não Identificado")

    # 3. Vincula Supervisor -> Telefone (pelo Nome, usando o dicionário)
    df_merged['Supervisor_Key'] = df_merged['Supervisor'].str.strip().str.upper()
    df_merged['Celular'] = df_merged['Supervisor_Key'].map(map_telefones)

    # 4. Renomear colunas
    df_merged = df_merged.rename(columns={
        'NMESTRUTGEREN': 'Escola', 
        'NMVINCULOM': 'Funcionario',
        'NMOCUPACAOH': 'Cargo',
        'horas_trabalhadas': 'Batidas',
        'horas_escala': 'Escala',
        'OBSERVACAO': 'Obs'
    })

    # --- LÓGICA DE TEMPO ---
    hoje = date.today()
    agora = datetime.now().time()
    
    # Flags de tempo
    eh_hoje = (data_analise == hoje)
    eh_passado = (data_analise < hoje)
    
    def extrair_hora_inicio(lista_escala):
        """ Extrai '13:40' de [['13:40', '17:00']] e converte para time object """
        if not isinstance(lista_escala, list) or not lista_escala: return None
        try:
            str_hora = lista_escala[0][0] 
            h, m = map(int, str_hora.split(':'))
            return time(h, m)
        except: return None

    def get_status(row):
        batidas = row.get('Batidas')
        escala = row.get('Escala')
        
        tem_batida = isinstance(batidas, list) and len(batidas) > 0
        if tem_batida: 
            return '🟢 Presente'

        tem_escala = isinstance(escala, list) and len(escala) > 0
        if tem_escala:
            if eh_passado: return '🔴 Falta'
            
            if eh_hoje:
                hora_inicio = extrair_hora_inicio(escala)
                if hora_inicio:
                    if agora >= hora_inicio: return '🔴 Falta'
                    else: return '⏳ A Iniciar'
                else: return '🔴 Falta'
            
            return '⏳ A Iniciar'
                
        return '🟡 S/ Escala'

    df_merged['Status_Individual'] = df_merged.apply(get_status, axis=1)

    # Formatadores Visuais
    def format_hora(lista):
        if not isinstance(lista, list) or not lista: return "-"
        try: return " | ".join([f"{x[0]}-{x[1]}" for x in lista if len(x) == 2])
        except: return "-"

    df_merged['Escala_Formatada'] = df_merged['Escala'].apply(format_hora)
    df_merged['Ponto_Real'] = df_merged['Batidas'].apply(format_hora)
    
    return df_merged

# ==============================================================================
# 6. FUNCIONALIDADE DE DISPARO WHATSAPP
# ==============================================================================
def gerar_link_whatsapp(telefone, mensagem):
    texto_encoded = urllib.parse.quote(mensagem)
    # Remove formatação do telefone para o link (deixa apenas números)
    fone_limpo = "".join(filter(str.isdigit, str(telefone))) if telefone else ""
    return f"https://wa.me/55{fone_limpo}?text={texto_encoded}"

@st.dialog("📢 Central de Alertas - WhatsApp", width="large")
def dialog_disparar_alertas(df_completo):
    st.caption("Envie mensagens para os supervisores com faltas confirmadas.")
    
    # 1. Filtra apenas quem tem falta
    df_faltas = df_completo[df_completo['Status_Individual'] == '🔴 Falta'].copy()
    
    if df_faltas.empty:
        st.success("🎉 Nenhuma falta registrada para alerta no momento!")
        return

    # 2. Agrupa por Supervisor
    supervisores = df_faltas['Supervisor'].unique()
    
    for supervisor in supervisores:
        with st.container(border=True):
            c1, c2 = st.columns([3, 1])
            
            # Pega as faltas desse supervisor
            df_sup = df_faltas[df_faltas['Supervisor'] == supervisor]
            qtd_faltas = len(df_sup)
            
            # --- PEGA O TELEFONE DO DATAFRAME ---
            # Como já cruzamos no processamento, o telefone está na coluna 'Celular'
            telefone_bruto = None
            if 'Celular' in df_sup.columns:
                val = df_sup['Celular'].iloc[0]
                if pd.notna(val) and str(val).strip() != "":
                    telefone_bruto = val
            
            # Monta a mensagem
            msg_lines = [f"Olá *{supervisor}*, segue o relatório de ausências ({datetime.now().strftime('%H:%M')}):"]
            for escola, dados_escola in df_sup.groupby('Escola'):
                nomes = ", ".join(dados_escola['Funcionario'].tolist())
                msg_lines.append(f"\n🏫 *{escola}*:\n🚫 {nomes}")
            
            msg_final = "\n".join(msg_lines)
            
            # Coluna da Esquerda: Resumo
            with c1:
                st.markdown(f"**👤 {supervisor}**")
                st.caption(f"{qtd_faltas} colaboradores faltantes.")
                with st.expander("Ver mensagem"):
                    st.code(msg_final, language=None)
            
            # Coluna da Direita: Botão de Ação
            with c2:
                # Verifica se o telefone existe
                if telefone_bruto:
                    link = gerar_link_whatsapp(telefone_bruto, msg_final)
                    st.link_button("📲 Enviar WhatsApp", link, use_container_width=True)
                else:
                    st.warning("Sem Celular")
                    st.caption(f"Verifique o cadastro de '{supervisor}'")

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