import streamlit as st
import requests
import pandas as pd
import pytz
from datetime import datetime
from sqlalchemy import text

# ==============================================================================
# 1. CONFIGURAÇÃO DA PÁGINA
# ==============================================================================
st.set_page_config(page_title="HCM - Ocorrências", layout="wide", page_icon="🚨")

# ==============================================================================
# 2. SEGURANÇA E CREDENCIAIS
# ==============================================================================
if not st.session_state.get("authentication_status"):
    st.warning("🔒 Acesso restrito. Faça login na página inicial.")
    st.stop()

# --- CREDENCIAIS HCM (Para buscar as ocorrências) ---
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

# --- CREDENCIAIS PORTAL GESTOR (Para buscar a lista de IDs) ---
try:
    SECRETS_PG = st.secrets["api_portal_gestor"]
    PG_TOKEN = SECRETS_PG["token_fixo"]
    PG_CD_OPERADOR = SECRETS_PG["cd_operador"]
    PG_NR_ORG = SECRETS_PG["nr_org"]
except Exception as e:
    st.error(f"⚠️ Erro Config Portal Gestor: {e}")
    st.stop()

# ==============================================================================
# 3. GESTÃO DE SESSÃO HCM (CACHE EM BANCO)
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
    
    # Validação simples
    if token:
        headers = {
            "OAuth-Token": token, "OAuth-Hash": HCM_HASH, "User-Id": HCM_UID_BROWSER,
            "OAuth-Project": HCM_PROJECT, "Content-Type": "application/json"
        }
        try:
            r = requests.post("https://hcm.teknisa.com/backend/index.php/getPessoa", headers=headers, json={"page":1,"itemsPerPage":1,"requestType":"FilterData"}, timeout=5)
            if r.status_code == 200: return token
        except: pass
    
    # Se falhou, renova
    new_token, new_uid = login_hcm_novo()
    if new_token:
        save_token_db(conn, new_token, new_uid)
        return new_token
    return None

# ==============================================================================
# 4. API PORTAL GESTOR (Buscar IDs)
# ==============================================================================
def fetch_ids_portal_gestor(data_ref):
    """Busca lista de funcionários ativos no Portal Gestor para pegar os IDs (NRVINCULOM)"""
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
                # Filtra apenas Atividade Normal para não buscar demitidos
                if not df.empty and 'NMSITUFUNCH' in df.columns:
                    df = df[df['NMSITUFUNCH'].str.strip() == 'Atividade Normal']
                return df
    except Exception as e:
        st.error(f"Erro Portal Gestor: {e}")
    return pd.DataFrame()

# ==============================================================================
# 5. API HCM (Buscar Ocorrências)
# ==============================================================================
def fetch_ocorrencias_hcm(token, lista_ids, periodo_apuracao, mes_competencia):
    """
    Busca ocorrências (Falta/Atraso) no HCM enviando lista de IDs.
    """
    url = "https://hcm.teknisa.com/backend/index.php/getMarcacaoPontoOcorrencias"
    
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Content-Type": "application/json",
        "OAuth-Token": token,
        "OAuth-Hash": HCM_HASH,
        "OAuth-Project": HCM_PROJECT,
        "User-Id": HCM_UID_BROWSER,
        "OAuth-KeepConnected": "Yes"
    }
    
    # Divide a lista em lotes de 100 para não estourar a request
    chunk_size = 100
    all_ocorrencias = []
    
    total_chunks = len(lista_ids) // chunk_size + 1
    prog_bar = st.progress(0, text="Consultando HCM...")

    for i in range(0, len(lista_ids), chunk_size):
        chunk = lista_ids[i:i + chunk_size]
        prog_bar.progress((i / len(lista_ids)), text=f"Consultando lote {i} a {i+len(chunk)}...")
        
        payload = {
            "disableLoader": False,
            "filter": [
                {"name": "P_NRORG", "operator": "=", "value": "3260"},
                {"name": "P_NRORG_PADRAO", "operator": "=", "value": "0"},
                {"name": "P_DTMESCOMPETENC", "operator": "=", "value": mes_competencia}, # Ex: "01/01/2026"
                {"name": "NRPERIODOAPURACAO", "value": int(periodo_apuracao), "operator": "=", "isCustomFilter": True},
                
                # AQUI ENTRA A LISTA DE IDs DO PORTAL GESTOR
                {"name": "NRVINCULOM_LIST", "value": chunk, "operator": "IN", "isCustomFilter": True},
                
                {"name": "P_TIPOOCORRENCIA", "value": ["ATRASO", "FALTA"], "operator": "IN", "isCustomFilter": True}
            ],
            "page": 1, "itemsPerPage": 9999, "requestType": "FilterData"
        }
        
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=45)
            if r.status_code == 200:
                data = r.json()
                if "dataset" in data and "getMarcacaoPontoOcorrencias" in data["dataset"]:
                    all_ocorrencias.extend(data["dataset"]["getMarcacaoPontoOcorrencias"])
        except Exception as e:
            st.warning(f"Erro no lote {i}: {e}")
            
    prog_bar.empty()
    return pd.DataFrame(all_ocorrencias)

def decimal_para_hora(val):
    """Converte 2.5 para 02:30"""
    try:
        horas = int(val)
        minutos = int((val - horas) * 60)
        return f"{horas:02d}:{minutos:02d}"
    except: return "00:00"

# ==============================================================================
# 6. INTERFACE PRINCIPAL
# ==============================================================================

st.title("🚨 Relatório de Faltas e Atrasos (HCM)")
st.markdown("Cruzamento de dados: **Lista de Ativos (Portal Gestor)** x **Ocorrências (HCM)**")

with st.sidebar:
    st.header("Filtros")
    data_ref = st.date_input("Data Ref. (Ativos)", datetime.now())
    
    # Filtros do Payload HCM
    comp_default = datetime.now().replace(day=1).strftime("%d/%m/%Y")
    mes_competencia = st.text_input("Mês Competência (HCM)", value=comp_default, help="Sempre o dia 01 do mês. Ex: 01/01/2026")
    periodo_apuracao = st.text_input("Período Apuração (Cód)", value="1904", help="Código interno do período (Ex: 1904)")
    
    st.divider()
    btn_buscar = st.button("🚀 Gerar Relatório", type="primary", use_container_width=True)

if btn_buscar:
    # 1. BUSCA IDs NO PORTAL GESTOR
    with st.status("🔄 Passo 1: Obtendo lista de funcionários ativos...", expanded=True) as status:
        df_funcionarios = fetch_ids_portal_gestor(data_ref)
        
        if df_funcionarios.empty:
            status.update(label="❌ Nenhum funcionário encontrado no Portal Gestor.", state="error")
            st.stop()
            
        # Pega a lista de IDs limpa (inteiros)
        lista_ids = df_funcionarios['NRVINCULOM'].dropna().astype(int).unique().tolist()
        # Cria dicionário para mapear nomes depois (caso o HCM não traga o nome atualizado)
        mapa_nomes = dict(zip(df_funcionarios['NRVINCULOM'].astype(str), df_funcionarios['NMVINCULOM']))
        mapa_escolas = dict(zip(df_funcionarios['NRVINCULOM'].astype(str), df_funcionarios['NMESTRUTGEREN']))
        
        status.write(f"✅ Encontrados **{len(lista_ids)}** funcionários ativos.")
        
        # 2. AUTENTICAÇÃO HCM
        status.write("🔐 Passo 2: Autenticando no HCM...")
        token_hcm = obter_sessao_hcm()
        if not token_hcm:
            status.update(label="❌ Falha ao logar no HCM.", state="error")
            st.stop()
            
        # 3. BUSCA OCORRÊNCIAS NO HCM
        status.write("📡 Passo 3: Consultando ocorrências em lote no HCM...")
        df_ocorrencias = fetch_ocorrencias_hcm(token_hcm, lista_ids, periodo_apuracao, mes_competencia)
        
        status.update(label="Processamento concluído!", state="complete", expanded=False)

    # 4. PROCESSAMENTO DOS DADOS
    if df_ocorrencias.empty:
        st.info("Nenhuma ocorrência (Falta ou Atraso) encontrada para este período e lista de funcionários.")
    else:
        # Convertendo valores
        df_ocorrencias['DIFF_HOURS'] = pd.to_numeric(df_ocorrencias['DIFF_HOURS'], errors='coerce').fillna(0)
        df_ocorrencias['NRVINCULOM'] = df_ocorrencias['NRVINCULOM'].astype(str)
        
        # Mapeia escola atual do Portal Gestor (garante dado mais recente)
        df_ocorrencias['Escola_Atual'] = df_ocorrencias['NRVINCULOM'].map(mapa_escolas)
        
        # --- AGRUPAMENTO ---
        # Agrupa por ID para somar/contar
        resumo = df_ocorrencias.groupby(['NRVINCULOM', 'NMVINCULOM', 'Escola_Atual']).agg(
            Qtd_Faltas=('TIPO_OCORRENCIA', lambda x: (x == 'FALTA').sum()),
            Total_Horas_Atraso=('DIFF_HOURS', lambda x: x[df_ocorrencias.loc[x.index, 'TIPO_OCORRENCIA'] == 'ATRASO'].sum()),
            Dias_Ocorrencia=('DATA_INICIO', lambda x: ", ".join(x.unique()))
        ).reset_index()
        
        # Filtra apenas quem tem problema
        resumo = resumo[ (resumo['Qtd_Faltas'] > 0) | (resumo['Total_Horas_Atraso'] > 0) ]
        
        # Formata horas
        resumo['Tempo_Atraso_Fmt'] = resumo['Total_Horas_Atraso'].apply(decimal_para_hora)
        
        # Ordenação
        resumo = resumo.sort_values(by=['Qtd_Faltas', 'Total_Horas_Atraso'], ascending=False)
        
        # --- DASHBOARD ---
        k1, k2, k3 = st.columns(3)
        k1.metric("Funcionários c/ Ocorrência", len(resumo))
        k2.metric("Total Faltas", resumo['Qtd_Faltas'].sum())
        k3.metric("Total Horas Atraso", f"{resumo['Total_Horas_Atraso'].sum():.1f}h")
        
        st.divider()
        
        tab1, tab2 = st.tabs(["📋 Resumo Gerencial", "🔍 Detalhe (Log Bruto)"])
        
        with tab1:
            st.dataframe(
                resumo[['NRVINCULOM', 'NMVINCULOM', 'Escola_Atual', 'Qtd_Faltas', 'Tempo_Atraso_Fmt']],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "NRVINCULOM": "Matrícula",
                    "NMVINCULOM": "Funcionário",
                    "Qtd_Faltas": st.column_config.NumberColumn("Faltas", format="%d ❌"),
                    "Tempo_Atraso_Fmt": st.column_config.TextColumn("Horas Atraso", help="Soma total das horas de atraso")
                }
            )
            
            # Download CSV Resumido
            csv_resumo = resumo.to_csv(index=False, sep=';', encoding='utf-8-sig')
            st.download_button("📥 Baixar Resumo (CSV)", csv_resumo, "hcm_resumo_ocorrencias.csv", "text/csv")
            
        with tab2:
            st.write("Dados brutos retornados pelo HCM:")
            st.dataframe(df_ocorrencias, use_container_width=True)