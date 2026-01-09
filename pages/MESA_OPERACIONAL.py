import streamlit as st
import pandas as pd
import requests
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
    st.info("Adicione [api_portal_gestor] com token_fixo no arquivo de segredos.")
    st.stop()

# ==============================================================================
# 3. BANCO DE DADOS
# ==============================================================================
@st.cache_data(ttl=3600)
def fetch_supervisores_db():
    try:
        conn = st.connection("postgres", type="sql")
        query = """
        SELECT u."UnidadeID", s."NomeSupervisor" as "Supervisor"
        FROM "Unidades" u
        JOIN "Supervisores" s ON u."SupervisorID" = s."SupervisorID"
        """
        df = conn.query(query)
        df['UnidadeID'] = pd.to_numeric(df['UnidadeID'], errors='coerce').fillna(0).astype(int)
        return df
    except Exception as e:
        st.error(f"Erro DB: {e}")
        return pd.DataFrame(columns=["UnidadeID", "Supervisor"])

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
def processar_dados_unificados(df_api, df_supervisores, data_analise):
    if df_api.empty: return df_api

    # 1. Filtro: Atividade Normal
    if 'NMSITUFUNCH' in df_api.columns:
        df_api = df_api[df_api['NMSITUFUNCH'] == 'Atividade Normal'].copy()
    
    if df_api.empty: return df_api

    # 2. Merge com DB (UnidadeID = NRESTRUTGEREN)
    df_api['UnidadeID'] = pd.to_numeric(df_api['NRESTRUTGEREN'], errors='coerce').fillna(0).astype(int)
    df_merged = pd.merge(df_api, df_supervisores, on="UnidadeID", how="left")
    df_merged['Supervisor'] = df_merged['Supervisor'].fillna("Não Identificado")

    # 3. Renomear colunas
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
            # Pega o primeiro item da primeira sublista
            str_hora = lista_escala[0][0] 
            h, m = map(int, str_hora.split(':'))
            return time(h, m)
        except: return None

    def get_status(row):
        batidas = row.get('Batidas')
        escala = row.get('Escala')
        
        # -----------------------------------------------------------
        # REGRA 1: PRESENÇA SOBERANA
        # Se tem batida no dia, é PRESENTE. 
        # Não importa se atrasou, adiantou ou saiu cedo.
        # -----------------------------------------------------------
        tem_batida = isinstance(batidas, list) and len(batidas) > 0
        if tem_batida: 
            return '🟢 Presente'

        # -----------------------------------------------------------
        # REGRA 2: SEM BATIDA (Análise de Falta vs A Iniciar)
        # -----------------------------------------------------------
        tem_escala = isinstance(escala, list) and len(escala) > 0
        
        if tem_escala:
            # Se for dia PASSADO e não bateu = FALTA
            if eh_passado:
                return '🔴 Falta'
            
            # Se for HOJE, comparamos com o relógio
            if eh_hoje:
                hora_inicio = extrair_hora_inicio(escala)
                if hora_inicio:
                    if agora >= hora_inicio:
                        # Já passou da hora de entrar e não tem batida
                        return '🔴 Falta'
                    else:
                        # Ainda não deu o horário de entrada
                        return '⏳ A Iniciar'
                else:
                    # Tem escala mas formato inválido -> Assume Falta para alertar
                    return '🔴 Falta'
            
            # Se for FUTURO (Amanhã em diante)
            return '⏳ A Iniciar'
                
        # Se não tem escala e não tem batida
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
# 6. UI - SIDEBAR
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

if st.sidebar.button("🔄 Atualizar Dados", use_container_width=True):
    st.session_state['mesa_dados'] = None
    st.cache_data.clear()
    st.rerun()

# ==============================================================================
# 7. CARREGAMENTO
# ==============================================================================
if st.session_state['mesa_dados'] is None:
    with st.spinner(f"Buscando dados de {data_selecionada.strftime('%d/%m/%Y')}..."):
        df_sup = fetch_supervisores_db()
        raw_api = fetch_mesa_operacional(data_selecionada)
        df_proc = processar_dados_unificados(raw_api, df_sup, data_selecionada)
        
        st.session_state['mesa_dados'] = df_proc
        st.session_state['mesa_data_ref'] = data_selecionada

df = st.session_state['mesa_dados']
data_exibicao = st.session_state['mesa_data_ref'].strftime("%d/%m/%Y")

# ==============================================================================
# 8. DASHBOARD
# ==============================================================================
st.title("📉 Monitoramento de Faltas")
st.caption(f"Dados referentes a: **{data_exibicao}**")

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

    # --- KPIs Globais ---
    qtd_presente = len(df_filtrado[df_filtrado['Status_Individual'] == '🟢 Presente'])
    qtd_falta = len(df_filtrado[df_filtrado['Status_Individual'] == '🔴 Falta'])
    qtd_a_entrar = len(df_filtrado[df_filtrado['Status_Individual'] == '⏳ A Iniciar'])
    
    qtd_efetivo = qtd_presente + qtd_falta + qtd_a_entrar

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Efetivo Esperado", qtd_efetivo)
    k2.metric("Presentes", qtd_presente)
    k3.metric("Faltas / Atrasos", qtd_falta, delta_color="inverse")
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
        
        # Problema: Tem faltas (já deviam estar lá) mas NINGUÉM chegou
        if presentes == 0:
            if faltas > 0:
                return "⚠️ POSSÍVEL PROBLEMA SMARTPHONE"
            elif a_entrar > 0 and faltas == 0:
                return "🕒 AGUARDANDO INÍCIO"
            else:
                return "⚠️ VERIFICAR"
        
        # Operação OK
        if faltas == 0:
            if a_entrar == 0:
                return "🌟 ESCOLA COMPLETA"
            else:
                return "✅ PARCIAL (Aguardando Tarde/Noite)"
        
        # Presença Parcial (Cálculo apenas sobre quem já deveria estar lá)
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
        if qtd_problema > 0:
            st.error(f"🚨 **{qtd_problema}** escolas com possível problema no Smartphone.")
    with c_info2:
        if qtd_completas > 0:
            st.success(f"🌟 **{qtd_completas}** escolas com efetivo 100% completo.")

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

    # --- Popup ---
    @st.dialog("Detalhe da Escola", width="large")
    def mostrar_detalhe(escola, supervisor, df_local, diag):
        st.subheader(f"🏫 {escola}")
        st.caption(f"Supervisor: {supervisor} | Status: {diag} | Data: {data_exibicao}")
        
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
