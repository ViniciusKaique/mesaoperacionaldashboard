import streamlit as st
import requests
import pandas as pd
import pytz
from datetime import datetime
from sqlalchemy import text

# ==============================================================================
# 1. CONFIGURAÇÃO DA PÁGINA
# ==============================================================================
st.set_page_config(page_title="HCM - Ocorrências (Turbo)", layout="wide", page_icon="⚡")

# ==============================================================================
# 2. SEGURANÇA E CREDENCIAIS
# ==============================================================================
if not st.session_state.get("authentication_status"):
    st.warning("🔒 Acesso restrito. Faça login na página inicial.")
    st.stop()

# --- CREDENCIAIS HCM ---
try:
    SECRETS_HCM = st.secrets["hcm_api"]
    HCM_USER = SECRETS_HCM["usuario"]
    HCM_PASS = SECRETS_HCM["senha"]
    HCM_HASH = SECRETS_HCM["hash_sessao"]
    HCM_UID_BROWSER = SECRETS_HCM["user_id_browser"]
    HCM_PROJECT = SECRETS_HCM.get("project_id", "750")
except Exception as e:
    st.error(f"⚠️ Erro Config HCM: {e}")
    st.stop()

# --- CREDENCIAIS PORTAL GESTOR ---
try:
    SECRETS_PG = st.secrets["api_portal_gestor"]
    PG_TOKEN = SECRETS_PG["token_fixo"]
    PG_CD_OPERADOR = SECRETS_PG["cd_operador"]
    PG_NR_ORG = SECRETS_PG["nr_org"]
except Exception as e:
    st.error(f"⚠️ Erro Config Portal Gestor: {e}")
    st.stop()

# ==============================================================================
# 3. GESTÃO DE SESSÃO HCM
# ==============================================================================
def get_data_brasil():
    return datetime.now(pytz.timezone('America/Sao_Paulo'))

def init_db_token():
    conn = st.connection("postgres", type="sql")
    try:
        with conn.session as session:
            session.execute(text("""
                CREATE TABLE IF NOT EXISTS public."HCMTokens" (
                    id VARCHAR(50) PRIMARY KEY,
                    access_token TEXT,
                    user_uid TEXT,
                    updated_at TIMESTAMP
                );
            """))
            session.commit()
    except: pass
    return conn

def get_token_db(conn):
    try:
        df = conn.query("SELECT access_token, user_uid FROM public.\"HCMTokens\" WHERE id = 'bot_hcm_contact'", ttl=0)
        if not df.empty: return df.iloc[0]['access_token'], df.iloc[0]['user_uid']
    except: pass
    return None, None

def save_token_db(conn, token, uid):
    try:
        with conn.session as session:
            query = text("""
                INSERT INTO public."HCMTokens" (id, access_token, user_uid, updated_at)
                VALUES ('bot_hcm_contact', :token, :uid, :hora)
                ON CONFLICT (id) DO UPDATE 
                SET access_token = EXCLUDED.access_token, user_uid = EXCLUDED.user_uid, updated_at = EXCLUDED.updated_at;
            """)
            session.execute(query, {"token": token, "uid": uid, "hora": get_data_brasil()})
            session.commit()
    except: pass

def login_hcm_novo():
    url = "https://hcm.teknisa.com/backend_login/index.php/login"
    headers = {
        "User-Agent": "Mozilla/5.0", "Content-Type": "application/json",
        "Origin": "https://hcm.teknisa.com", "Referer": "https://hcm.teknisa.com/login/",
        "User-Id": HCM_UID_BROWSER
    }
    payload = {
        "disableLoader": False,
        "filter": [
            {"name": "EMAIL", "operator": "=", "value": HCM_USER},
            {"name": "PASSWORD", "operator": "=", "value": HCM_PASS},
            {"name": "PRODUCT_ID", "operator": "=", "value": int(HCM_PROJECT)},
            {"name": "HASH", "operator": "=", "value": HCM_HASH},
            {"name": "KEEP_CONNECTED", "operator": "=", "value": "S"}
        ],
        "page": 1, "requestType": "FilterData",
        "origin": {"containerName": "AUTHENTICATION", "widgetName": "LOGIN"}
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=20)
        data = r.json()
        if "dataset" in data and "userData" in data["dataset"]:
            return data["dataset"]["userData"].get("TOKEN"), data["dataset"]["userData"].get("USER_ID")
    except: pass
    return None, None

def obter_sessao_hcm():
    conn = init_db_token()
    token, uid = get_token_db(conn)
    if token:
        headers = {
            "OAuth-Token": token, "OAuth-Hash": HCM_HASH, "User-Id": HCM_UID_BROWSER,
            "OAuth-Project": HCM_PROJECT, "Content-Type": "application/json"
        }
        try:
            r = requests.post("https://hcm.teknisa.com/backend/index.php/getPessoa", headers=headers, json={"page":1,"itemsPerPage":1,"requestType":"FilterData"}, timeout=5)
            if r.status_code == 200: return token
        except: pass
    new_token, new_uid = login_hcm_novo()
    if new_token:
        save_token_db(conn, new_token, new_uid)
        return new_token
    return None

# ==============================================================================
# 4. API PORTAL GESTOR
# ==============================================================================
def fetch_ids_portal_gestor(data_ref):
    url = "https://portalgestor.teknisa.com/backend/index.php/getMesaOperacoes"
    params = {
        "requestType": "FilterData",
        "DIA": data_ref.strftime("%d/%m/%Y"),
        "NRESTRUTURAM": "101091998",
        "NRORG": PG_NR_ORG, "CDOPERADOR": PG_CD_OPERADOR
    }
    headers = {
        "OAuth-Token": PG_TOKEN, "OAuth-Cdoperador": PG_CD_OPERADOR, "OAuth-Nrorg": PG_NR_ORG,
        "User-Agent": "Mozilla/5.0"
    }
    try:
        r = requests.get(url, params=params, headers=headers, timeout=30)
        if r.status_code == 200:
            data = r.json()
            if "dataset" in data and "data" in data["dataset"]:
                df = pd.DataFrame(data["dataset"]["data"])
                if not df.empty and 'NMSITUFUNCH' in df.columns:
                    df = df[df['NMSITUFUNCH'].str.strip() == 'Atividade Normal']
                return df
    except Exception as e:
        st.error(f"Erro Portal Gestor: {e}")
    return pd.DataFrame()

@st.cache_data(ttl=3600) 
def fetch_periodos_apuracao():
    url = "https://portalgestor.teknisa.com/backend/index.php/getPeriodosDemonstrativo"
    params = { "requestType": "FilterData", "NRORG": PG_NR_ORG, "CDOPERADOR": PG_CD_OPERADOR }
    headers = { "OAuth-Token": PG_TOKEN, "OAuth-Cdoperador": PG_CD_OPERADOR, "OAuth-Nrorg": PG_NR_ORG, "User-Agent": "Mozilla/5.0" }
    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if "dataset" in data and "data" in data["dataset"]:
                return pd.DataFrame(data["dataset"]["data"])
    except: pass
    return pd.DataFrame()

# ==============================================================================
# 5. API HCM
# ==============================================================================
def fetch_ocorrencias_hcm_turbo(token, lista_ids, periodo_apuracao, mes_competencia):
    url = "https://hcm.teknisa.com/backend/index.php/getMarcacaoPontoOcorrencias"
    headers = {
        "User-Agent": "Mozilla/5.0", "Content-Type": "application/json",
        "OAuth-Token": token, "OAuth-Hash": HCM_HASH,
        "OAuth-Project": HCM_PROJECT, "User-Id": HCM_UID_BROWSER,
        "OAuth-KeepConnected": "Yes"
    }
    payload = {
        "disableLoader": False,
        "filter": [
            {"name": "P_NRORG", "operator": "=", "value": "3260"},
            {"name": "P_NRORG_PADRAO", "operator": "=", "value": "0"},
            {"name": "P_DTMESCOMPETENC", "operator": "=", "value": mes_competencia},
            {"name": "NRPERIODOAPURACAO", "value": int(periodo_apuracao), "operator": "=", "isCustomFilter": True},
            {"name": "NRVINCULOM_LIST", "value": lista_ids, "operator": "IN", "isCustomFilter": True},
            {"name": "P_TIPOOCORRENCIA", "value": ["ATRASO", "FALTA"], "operator": "IN", "isCustomFilter": True}
        ],
        "page": 1, "itemsPerPage": 99999, "requestType": "FilterData"
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=80)
        if r.status_code == 200:
            data = r.json()
            if "dataset" in data and "getMarcacaoPontoOcorrencias" in data["dataset"]:
                return pd.DataFrame(data["dataset"]["getMarcacaoPontoOcorrencias"])
    except Exception as e:
        st.error(f"Erro na requisição: {e}")
    return pd.DataFrame()

def decimal_para_hora(val):
    try:
        if pd.isna(val) or val == 0: return "00:00"
        horas = int(val)
        minutos = int((val - horas) * 60)
        return f"{horas:02d}:{minutos:02d}"
    except: return "00:00"

# ==============================================================================
# 6. INTERFACE
# ==============================================================================

st.title("⚡ Relatório Turbo - Faltas e Atrasos (HCM)")
st.markdown("**Modo Otimizado:** Ignora ocorrências do dia vigente.")

with st.sidebar:
    st.header("Parâmetros")
    
    df_periodos = fetch_periodos_apuracao()
    periodo_apuracao = "1904"
    competencia_sugerida = datetime.now().replace(day=1).strftime("%d/%m/%Y")
    
    if not df_periodos.empty:
        opcao = st.selectbox("Selecione o Período:", df_periodos['DSPERIODOAPURACAO'])
        row_sel = df_periodos[df_periodos['DSPERIODOAPURACAO'] == opcao].iloc[0]
        periodo_apuracao = row_sel['NRPERIODOAPURACAO']
        try:
            dt_ini = datetime.strptime(row_sel['DTINICIALAPURACAO'], "%d/%m/%Y")
            competencia_sugerida = dt_ini.replace(day=1).strftime("%d/%m/%Y")
        except: pass
    else:
        periodo_apuracao = st.text_input("Período Apuração (Cód)", value="1904")

    mes_competencia = st.text_input("Mês Competência (HCM)", value=competencia_sugerida)
    data_ref = st.date_input("Data Ref. (Para Lista de Ativos)", datetime.now())
    
    st.divider()
    btn_buscar = st.button("🚀 Disparar Análise", use_container_width=True)

if btn_buscar:
    with st.status("🔄 Analisando...", expanded=True) as status:
        # 1. LISTA DE ATIVOS
        status.write("Buscando funcionários ativos...")
        df_funcionarios = fetch_ids_portal_gestor(data_ref)
        if df_funcionarios.empty:
            status.update(label="❌ Lista vazia.", state="error"); st.stop()
            
        lista_ids = df_funcionarios['NRVINCULOM'].dropna().astype(int).unique().tolist()
        
        # Cria mapas para referência
        df_funcionarios['NRVINCULOM'] = df_funcionarios['NRVINCULOM'].astype(str)
        mapa_nomes = dict(zip(df_funcionarios['NRVINCULOM'], df_funcionarios['NMVINCULOM']))
        mapa_escolas = dict(zip(df_funcionarios['NRVINCULOM'], df_funcionarios['NMESTRUTGEREN']))
        
        # 2. HCM
        status.write("Consultando ocorrências no HCM...")
        token_hcm = obter_sessao_hcm()
        if not token_hcm:
            status.update(label="❌ Falha login HCM.", state="error"); st.stop()
            
        df_ocorrencias = fetch_ocorrencias_hcm_turbo(token_hcm, lista_ids, periodo_apuracao, mes_competencia)
        status.update(label="Sucesso!", state="complete", expanded=False)

    # --- PROCESSAMENTO INTELIGENTE ---
    
    # 1. FILTRO DE DATA VIGENTE (HOJE)
    hoje_str = datetime.now().strftime('%Y-%m-%d')
    ocorrencias_filtradas = pd.DataFrame()
    
    if not df_ocorrencias.empty:
        # Remove ocorrências onde DATA_INICIO_FILTER == Hoje
        df_ocorrencias['DATA_INICIO_FILTER'] = df_ocorrencias['DATA_INICIO_FILTER'].astype(str)
        qtd_antes = len(df_ocorrencias)
        ocorrencias_filtradas = df_ocorrencias[df_ocorrencias['DATA_INICIO_FILTER'] != hoje_str].copy()
        qtd_depois = len(ocorrencias_filtradas)
        
        if qtd_antes > qtd_depois:
            st.toast(f"ℹ️ {qtd_antes - qtd_depois} ocorrências de hoje ({hoje_str}) foram ignoradas.")
    
    # 2. SEPARAÇÃO E CÁLCULOS
    if ocorrencias_filtradas.empty:
        st.success("🎉 Nenhuma falta ou atraso encontrado (exceto hoje)!")
    else:
        # Garante que DIFF_HOURS seja numérico
        ocorrencias_filtradas['DIFF_HOURS'] = pd.to_numeric(ocorrencias_filtradas['DIFF_HOURS'], errors='coerce').fillna(0)
        ocorrencias_filtradas['NRVINCULOM'] = ocorrencias_filtradas['NRVINCULOM'].astype(str)
        
        # Nomes e Escolas
        ocorrencias_filtradas['Funcionario'] = ocorrencias_filtradas['NRVINCULOM'].map(mapa_nomes).fillna(ocorrencias_filtradas['NMVINCULOM'])
        ocorrencias_filtradas['Escola'] = ocorrencias_filtradas['NRVINCULOM'].map(mapa_escolas).fillna(ocorrencias_filtradas['NMESTRUTGEREN'])
        
        # ======================================================================
        # CÁLCULOS SEPARADOS (CORREÇÃO DE SOMA)
        # ======================================================================
        
        # A) FALTAS: Remove linhas duplicadas de dia para o mesmo vínculo para contar DIAS
        df_faltas_unique = ocorrencias_filtradas[ocorrencias_filtradas['TIPO_OCORRENCIA'] == 'FALTA'].drop_duplicates(subset=['NRVINCULOM', 'DATA_INICIO'])
        s_faltas = df_faltas_unique.groupby('NRVINCULOM').size().rename('Qtd_Faltas')
        
        # B) ATRASOS: Mantém TODAS as linhas e SOMA as horas
        df_atrasos_all = ocorrencias_filtradas[ocorrencias_filtradas['TIPO_OCORRENCIA'] == 'ATRASO']
        s_atrasos = df_atrasos_all.groupby('NRVINCULOM')['DIFF_HOURS'].sum().rename('Total_Horas_Atraso')
        
        # C) DATAS: Lista todas as datas de problemas
        s_datas = ocorrencias_filtradas.groupby('NRVINCULOM')['DATA_INICIO'].unique().apply(lambda x: ", ".join(sorted(x))).rename('Datas')
        
        # D) CONSOLIDAÇÃO: Pega lista única de pessoas com problema e junta os dados
        # Cria um DF base apenas com os IDs que tiveram algum problema
        df_base_agg = ocorrencias_filtradas[['NRVINCULOM', 'Funcionario', 'Escola']].drop_duplicates('NRVINCULOM').set_index('NRVINCULOM')
        
        # Join (Left join na base de problemas)
        resumo = df_base_agg.join(s_faltas, how='left').join(s_atrasos, how='left').join(s_datas, how='left').fillna(0).reset_index()
        
        # Formatação Visual
        resumo['Qtd_Faltas'] = resumo['Qtd_Faltas'].astype(int)
        resumo['Tempo_Atraso_Fmt'] = resumo['Total_Horas_Atraso'].apply(decimal_para_hora)

        # 3. IDENTIFICAR "SEM OCORRÊNCIAS"
        ids_com_problema = set(resumo['NRVINCULOM'].unique())
        # Filtra do DF original (Portal Gestor) quem não está na lista de problemas
        df_sem_ocorrencias = df_funcionarios[~df_funcionarios['NRVINCULOM'].isin(ids_com_problema)].copy()
        df_sem_ocorrencias = df_sem_ocorrencias[['NRVINCULOM', 'NMVINCULOM', 'NMESTRUTGEREN']].rename(
            columns={'NMVINCULOM': 'Funcionario', 'NMESTRUTGEREN': 'Escola'}
        )

        # --- EXIBIÇÃO ---
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Total Analisado", len(df_funcionarios))
        k2.metric("✅ Ponto Excelente", len(df_sem_ocorrencias), delta_color="normal")
        k3.metric("Com Faltas/Atrasos", len(resumo), delta_color="inverse")
        k4.metric("Faltas Totais (Dias)", resumo['Qtd_Faltas'].sum())
        
        st.divider()
        
        tab1, tab2, tab3, tab4 = st.tabs(["🏆 Ranking Faltas", "📉 Ranking Atrasos", "✅ Ponto Excelente", "📋 Base Completa"])
        
        with tab1:
            st.subheader("Quem mais faltou no período")
            # Filtra quem tem pelo menos 1 falta
            df_faltas_show = resumo[resumo['Qtd_Faltas'] > 0].sort_values(by='Qtd_Faltas', ascending=False)
            st.dataframe(
                df_faltas_show[['NRVINCULOM', 'Funcionario', 'Escola', 'Qtd_Faltas', 'Datas']],
                use_container_width=True,
                hide_index=True,
                column_config={"Qtd_Faltas": st.column_config.NumberColumn("Qtd. Dias Falta", format="%d ❌")}
            )
            
        with tab2:
            st.subheader("Quem tem mais horas de atraso")
            # Filtra quem tem atraso (>0)
            df_atrasos_show = resumo[resumo['Total_Horas_Atraso'] > 0].sort_values(by='Total_Horas_Atraso', ascending=False)
            st.dataframe(
                df_atrasos_show[['NRVINCULOM', 'Funcionario', 'Escola', 'Tempo_Atraso_Fmt', 'Datas']],
                use_container_width=True,
                hide_index=True,
                column_config={"Tempo_Atraso_Fmt": st.column_config.TextColumn("Horas Totais")}
            )
            
        with tab3:
            st.subheader(f"✅ Ponto Excelente ({len(df_sem_ocorrencias)})")
            st.caption("Colaboradores ativos sem nenhuma falta ou atraso registrado no período (descontando hoje).")
            st.dataframe(df_sem_ocorrencias, use_container_width=True, hide_index=True)
            
        with tab4:
            st.subheader("Tabela Geral Consolidada")
            st.dataframe(resumo, use_container_width=True, hide_index=True)
            csv = resumo.to_csv(index=False, sep=';', encoding='utf-8-sig')
            st.download_button("📥 Baixar Planilha", csv, f"hcm_relatorio_{periodo_apuracao}.csv", "text/csv")