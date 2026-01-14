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
# 3. GESTÃO DE SESSÃO HCM (CACHE)
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
# 4. API PORTAL GESTOR (Buscar IDs e Períodos)
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
    """Busca a lista de períodos disponíveis no endpoint getPeriodosDemonstrativo"""
    url = "https://portalgestor.teknisa.com/backend/index.php/getPeriodosDemonstrativo"
    params = {
        "requestType": "FilterData",
        "NRORG": PG_NR_ORG,
        "CDOPERADOR": PG_CD_OPERADOR
    }
    headers = {
        "OAuth-Token": PG_TOKEN, "OAuth-Cdoperador": PG_CD_OPERADOR, "OAuth-Nrorg": PG_NR_ORG,
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json"
    }
    
    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if "dataset" in data and "data" in data["dataset"]:
                df = pd.DataFrame(data["dataset"]["data"])
                return df
    except Exception as e:
        st.warning(f"Não foi possível carregar lista de períodos: {e}")
    
    return pd.DataFrame()

# ==============================================================================
# 5. API HCM (Buscar Ocorrências - SINGLE REQUEST)
# ==============================================================================
def fetch_ocorrencias_hcm_turbo(token, lista_ids, periodo_apuracao, mes_competencia):
    url = "https://hcm.teknisa.com/backend/index.php/getMarcacaoPontoOcorrencias"
    
    headers = {
        "User-Agent": "Mozilla/5.0", "Content-Type": "application/json",
        "OAuth-Token": token, "OAuth-Hash": HCM_HASH,
        "OAuth-Project": HCM_PROJECT, "User-Id": HCM_UID_BROWSER,
        "OAuth-KeepConnected": "Yes"
    }
    
    # PAYLOAD COM A LISTA COMPLETA
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
        "page": 1, 
        "itemsPerPage": 99999,
        "requestType": "FilterData"
    }
    
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=70) # Timeout generoso
        if r.status_code == 200:
            data = r.json()
            if "dataset" in data and "getMarcacaoPontoOcorrencias" in data["dataset"]:
                return pd.DataFrame(data["dataset"]["getMarcacaoPontoOcorrencias"])
        else:
            st.error(f"Erro HTTP {r.status_code}: {r.text}")
    except Exception as e:
        st.error(f"Erro na Requisição Única: {e}")
            
    return pd.DataFrame()

def decimal_para_hora(val):
    try:
        horas = int(val)
        minutos = int((val - horas) * 60)
        return f"{horas:02d}:{minutos:02d}"
    except: return "00:00"

# ==============================================================================
# 6. INTERFACE PRINCIPAL
# ==============================================================================

st.title("⚡ Relatório Turbo - Faltas e Atrasos (HCM)")
st.markdown("**Modo Otimizado:** Busca em lote e seleção dinâmica de períodos.")

with st.sidebar:
    st.header("Parâmetros")
    
    # 1. SELEÇÃO DE PERÍODO (AUTOMATIZADA)
    df_periodos = fetch_periodos_apuracao()
    
    periodo_selecionado = None
    competencia_sugerida = datetime.now().replace(day=1).strftime("%d/%m/%Y")
    
    if not df_periodos.empty:
        # --- ALTERAÇÃO AQUI: Usa apenas a descrição no visual ---
        opcao = st.selectbox("Selecione o Período:", df_periodos['DSPERIODOAPURACAO'])
        
        # Recupera o ID (Código) correspondente à descrição selecionada
        # Filtra o dataframe para achar a linha onde a descrição bate
        row_sel = df_periodos[df_periodos['DSPERIODOAPURACAO'] == opcao].iloc[0]
        periodo_apuracao = row_sel['NRPERIODOAPURACAO']
        
        # Tenta calcular a competência sugerida baseada na data inicial do período
        try:
            dt_ini_str = row_sel['DTINICIALAPURACAO'] # ex: 16/01/2026
            dt_ini = datetime.strptime(dt_ini_str, "%d/%m/%Y")
            competencia_sugerida = dt_ini.replace(day=1).strftime("%d/%m/%Y")
        except:
            pass
            
    else:
        # Fallback manual se a API de períodos falhar
        periodo_apuracao = st.text_input("Período Apuração (Cód)", value="1904")

    # 2. OUTROS FILTROS
    mes_competencia = st.text_input("Mês Competência (HCM)", value=competencia_sugerida, help="Data base para o HCM (Dia 01 do mês).")
    data_ref = st.date_input("Data Ref. (Para Lista de Ativos)", datetime.now())
    
    st.divider()
    # --- ALTERAÇÃO AQUI: Removeu o type="primary" ---
    btn_buscar = st.button("🚀 Disparar Análise", use_container_width=True)

if btn_buscar:
    # 1. BUSCA IDs NO PORTAL GESTOR
    with st.status("🔄 Preparando dados...", expanded=True) as status:
        status.write("Obtendo lista de funcionários ativos no Portal Gestor...")
        df_funcionarios = fetch_ids_portal_gestor(data_ref)
        
        if df_funcionarios.empty:
            status.update(label="❌ Ninguém encontrado no Portal Gestor.", state="error")
            st.stop()
            
        lista_ids = df_funcionarios['NRVINCULOM'].dropna().astype(int).unique().tolist()
        mapa_escolas = dict(zip(df_funcionarios['NRVINCULOM'].astype(str), df_funcionarios['NMESTRUTGEREN']))
        
        status.write(f"✅ Lista pronta: **{len(lista_ids)}** IDs.")
        status.write("🔐 Autenticando no HCM...")
        token_hcm = obter_sessao_hcm()
        if not token_hcm:
            status.update(label="❌ Falha de login HCM.", state="error")
            st.stop()
            
        # 3. BUSCA OCORRÊNCIAS (SINGLE SHOT)
        status.write(f"⚡ Consultando Período ID {periodo_apuracao} no HCM...")
        df_ocorrencias = fetch_ocorrencias_hcm_turbo(token_hcm, lista_ids, periodo_apuracao, mes_competencia)
        
        status.update(label="Sucesso!", state="complete", expanded=False)

    # 4. PROCESSAMENTO
    if df_ocorrencias.empty:
        st.info("Nenhuma ocorrência retornada ou erro na requisição.")
    else:
        df_ocorrencias['DIFF_HOURS'] = pd.to_numeric(df_ocorrencias['DIFF_HOURS'], errors='coerce').fillna(0)
        df_ocorrencias['NRVINCULOM'] = df_ocorrencias['NRVINCULOM'].astype(str)
        df_ocorrencias['Escola_Atual'] = df_ocorrencias['NRVINCULOM'].map(mapa_escolas)
        
        # Agrupamento
        resumo = df_ocorrencias.groupby(['NRVINCULOM', 'NMVINCULOM', 'Escola_Atual']).agg(
            Qtd_Faltas=('TIPO_OCORRENCIA', lambda x: (x == 'FALTA').sum()),
            Total_Horas_Atraso=('DIFF_HOURS', lambda x: x[df_ocorrencias.loc[x.index, 'TIPO_OCORRENCIA'] == 'ATRASO'].sum()),
            Datas=('DATA_INICIO', lambda x: ", ".join(sorted(x.unique())))
        ).reset_index()
        
        resumo['Tempo_Atraso_Fmt'] = resumo['Total_Horas_Atraso'].apply(decimal_para_hora)
        resumo = resumo.sort_values(by=['Qtd_Faltas', 'Total_Horas_Atraso'], ascending=False)
        
        # --- EXIBIÇÃO ---
        k1, k2, k3 = st.columns(3)
        k1.metric("Funcionários Encontrados", len(resumo))
        k2.metric("Total Faltas", resumo['Qtd_Faltas'].sum())
        k3.metric("Total Atraso (Horas)", f"{resumo['Total_Horas_Atraso'].sum():.1f}h")
        
        st.divider()
        
        st.subheader("📋 Relatório Consolidado")
        st.dataframe(
            resumo,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Qtd_Faltas": st.column_config.NumberColumn("Faltas", format="%d ❌"),
                "Tempo_Atraso_Fmt": st.column_config.TextColumn("Tempo Atraso"),
                "Total_Horas_Atraso": st.column_config.NumberColumn("Decimais", format="%.2f"),
                "Datas": st.column_config.TextColumn("Dias das Ocorrências", width="large")
            }
        )
        
        csv = resumo.to_csv(index=False, sep=';', encoding='utf-8-sig')
        st.download_button("📥 Baixar Relatório (CSV)", csv, f"hcm_ocorrencias_{periodo_apuracao}.csv", "text/csv")