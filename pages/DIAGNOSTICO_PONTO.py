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

# --- CARREGAR CREDENCIAIS ---
try:
    SECRETS_HCM = st.secrets["hcm_api"]
    HCM_USER = SECRETS_HCM["usuario"]
    HCM_PASS = SECRETS_HCM["senha"]
    HCM_HASH = SECRETS_HCM["hash_sessao"]
    HCM_UID_BROWSER = SECRETS_HCM["user_id_browser"]
    HCM_PROJECT = SECRETS_HCM.get("project_id", "750")

    SECRETS_PG = st.secrets["api_portal_gestor"]
    PG_TOKEN = SECRETS_PG["token_fixo"]
    PG_CD_OPERADOR = SECRETS_PG["cd_operador"]
    PG_NR_ORG = SECRETS_PG["nr_org"]
except Exception as e:
    st.error(f"⚠️ Erro ao carregar secrets.toml: {e}")
    st.stop()

# ==============================================================================
# 3. GESTÃO DE SESSÃO E BANCO DE DADOS
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
# 4. API PORTAL GESTOR (CONEXÕES)
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
# 5. API HCM - OCORRÊNCIAS
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

# ==============================================================================
# 6. API HCM - DETALHES DO PONTO (ESPELHO)
# ==============================================================================
@st.cache_data(ttl=300)
def fetch_dias_demonstrativo(vinculo, periodo):
    """ Busca os dados usando AS CREDENCIAIS DO SECRETS para contornar erro 403 """
    url = "https://portalgestor.teknisa.com/backend/index.php/getDiasDemonstrativo"
    params = {
        "requestType": "FilterData",
        "NRVINCULOM": vinculo,
        "NRPERIODOAPURACAO": periodo,
        "NRORG": PG_NR_ORG,
        "CDOPERADOR": PG_CD_OPERADOR
    }
    headers = {
        "OAuth-Token": PG_TOKEN, 
        "OAuth-Cdoperador": PG_CD_OPERADOR, 
        "OAuth-Nrorg": PG_NR_ORG,
        "User-Agent": "Mozilla/5.0"
    }
    try:
        r = requests.get(url, params=params, headers=headers, timeout=15)
        if r.status_code == 200:
            data = r.json()
            if "dataset" in data and "data" in data["dataset"]:
                return pd.DataFrame(data["dataset"]["data"])
    except: pass
    return pd.DataFrame()

def decimal_para_hora(val):
    try:
        if pd.isna(val) or val == 0: return "00:00"
        horas = int(val)
        minutos = int((val - horas) * 60)
        return f"{horas:02d}:{minutos:02d}"
    except: return "00:00"

# ==============================================================================
# 7. INTERFACE E MODAL
# ==============================================================================

@st.dialog("📅 Espelho de Ponto (Detalhado)", width="large")
def mostrar_espelho_modal(nome, vinculo, periodo):
    st.write(f"**Funcionário:** {nome}")
    st.caption(f"Matrícula: {vinculo} | Período ID: {periodo}")
    
    with st.spinner("Buscando batidas no sistema..."):
        df_espelho = fetch_dias_demonstrativo(vinculo, periodo)
    
    if not df_espelho.empty:
        # Colunas mais úteis para exibir
        cols_show = ['DTAPURACAO', 'DSPONTODIA', 'ENTRADA_SAIDA_1', 'ENTRADA_SAIDA_2', 'ENTRADA_SAIDA_3', 'QTHORASREALIZADAS', 'QTHORASABONADAS', 'QTHORASFALTAS']
        # Filtra só as que existem
        cols_final = [c for c in cols_show if c in df_espelho.columns]
        
        st.dataframe(
            df_espelho[cols_final],
            use_container_width=True,
            hide_index=True,
            column_config={
                "DTAPURACAO": st.column_config.TextColumn("Data"),
                "DSPONTODIA": st.column_config.TextColumn("Situação", width="medium"),
                "QTHORASFALTAS": st.column_config.NumberColumn("Faltas (h)", format="%.2f"),
                "QTHORASREALIZADAS": st.column_config.NumberColumn("Trab (h)", format="%.2f"),
                "ENTRADA_SAIDA_1": "E1/S1",
                "ENTRADA_SAIDA_2": "E2/S2",
                "ENTRADA_SAIDA_3": "E3/S3"
            }
        )
    else:
        st.warning("⚠️ Não foi possível carregar o espelho. Verifique se há dados para este período.")

# ==============================================================================
# 8. LÓGICA PRINCIPAL DA PÁGINA
# ==============================================================================

st.title("⚡ Relatório Turbo - Faltas e Atrasos (HCM)")
st.markdown("**Modo Otimizado:** Ignora ocorrências do dia vigente.")

# --- INICIALIZAÇÃO DO ESTADO DE BUSCA ---
if "busca_realizada" not in st.session_state:
    st.session_state["busca_realizada"] = False
if "dados_cache" not in st.session_state:
    st.session_state["dados_cache"] = {}

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
    
    # BOTÃO QUE ATIVA A BUSCA
    if st.button("🚀 Disparar Análise", use_container_width=True):
        st.session_state["busca_realizada"] = True
        st.rerun()

# --- EXECUÇÃO DA BUSCA (SE ESTIVER ATIVA) ---
if st.session_state["busca_realizada"]:
    
    # Se ainda não temos os dados no cache ou se foi uma nova busca, carrega
    if not st.session_state["dados_cache"]:
        with st.status("🔄 Analisando...", expanded=True) as status:
            # 1. LISTA DE ATIVOS
            status.write("Buscando funcionários ativos...")
            df_funcionarios = fetch_ids_portal_gestor(data_ref)
            if df_funcionarios.empty:
                status.update(label="❌ Lista vazia.", state="error")
                st.session_state["busca_realizada"] = False
                st.stop()
                
            lista_ids = df_funcionarios['NRVINCULOM'].dropna().astype(int).unique().tolist()
            
            # 2. HCM
            status.write("Consultando ocorrências no HCM...")
            token_hcm = obter_sessao_hcm()
            if not token_hcm:
                status.update(label="❌ Falha login HCM.", state="error")
                st.session_state["busca_realizada"] = False
                st.stop()
                
            df_ocorrencias = fetch_ocorrencias_hcm_turbo(token_hcm, lista_ids, periodo_apuracao, mes_competencia)
            
            # SALVA NO CACHE DE SESSÃO
            st.session_state["dados_cache"] = {
                "funcionarios": df_funcionarios,
                "ocorrencias": df_ocorrencias,
                "periodo_apuracao": periodo_apuracao
            }
            status.update(label="Sucesso!", state="complete", expanded=False)

    # RECUPERA DADOS DO CACHE
    df_funcionarios = st.session_state["dados_cache"]["funcionarios"]
    df_ocorrencias = st.session_state["dados_cache"]["ocorrencias"]
    periodo_apuracao = st.session_state["dados_cache"]["periodo_apuracao"]

    # Cria mapas para referência
    df_funcionarios['NRVINCULOM'] = df_funcionarios['NRVINCULOM'].astype(str)
    mapa_nomes = dict(zip(df_funcionarios['NRVINCULOM'], df_funcionarios['NMVINCULOM']))
    mapa_escolas = dict(zip(df_funcionarios['NRVINCULOM'], df_funcionarios['NMESTRUTGEREN']))

    # --- PROCESSAMENTO DOS DADOS ---
    hoje_str = datetime.now().strftime('%Y-%m-%d')
    ocorrencias_filtradas = pd.DataFrame()
    
    if not df_ocorrencias.empty:
        df_ocorrencias['DATA_INICIO_FILTER'] = df_ocorrencias['DATA_INICIO_FILTER'].astype(str)
        df_ocorrencias['TIPO_OCORRENCIA'] = df_ocorrencias['TIPO_OCORRENCIA'].str.strip().str.upper()
        
        qtd_antes = len(df_ocorrencias)
        ocorrencias_filtradas = df_ocorrencias[df_ocorrencias['DATA_INICIO_FILTER'] != hoje_str].copy()
        
        if qtd_antes > len(ocorrencias_filtradas):
            st.toast(f"ℹ️ Ocorrências de hoje ({hoje_str}) foram ignoradas.")
    
    if ocorrencias_filtradas.empty:
        st.success("🎉 Nenhuma falta ou atraso encontrado (exceto hoje)!")
    else:
        ocorrencias_filtradas['DIFF_HOURS'] = pd.to_numeric(ocorrencias_filtradas['DIFF_HOURS'], errors='coerce').fillna(0)
        ocorrencias_filtradas['NRVINCULOM'] = ocorrencias_filtradas['NRVINCULOM'].astype(str)
        ocorrencias_filtradas['Funcionario'] = ocorrencias_filtradas['NRVINCULOM'].map(mapa_nomes).fillna(ocorrencias_filtradas['NMVINCULOM'])
        ocorrencias_filtradas['Escola'] = ocorrencias_filtradas['NRVINCULOM'].map(mapa_escolas).fillna(ocorrencias_filtradas['NMESTRUTGEREN'])
        
        # Separa Faltas
        df_only_faltas = ocorrencias_filtradas[ocorrencias_filtradas['TIPO_OCORRENCIA'] == 'FALTA'].copy()
        s_faltas = df_only_faltas.drop_duplicates(subset=['NRVINCULOM', 'DATA_INICIO']).groupby('NRVINCULOM').size().rename('Qtd_Faltas')
        
        # Separa Atrasos
        df_only_atrasos = ocorrencias_filtradas[ocorrencias_filtradas['TIPO_OCORRENCIA'] == 'ATRASO'].copy()
        s_atrasos = df_only_atrasos.groupby('NRVINCULOM')['DIFF_HOURS'].sum().rename('Total_Horas_Atraso')
        
        # Datas para exibição
        s_datas = ocorrencias_filtradas.groupby('NRVINCULOM')['DATA_INICIO'].unique().apply(lambda x: ", ".join(sorted(x))).rename('Datas')
        
        # Monta Resumo
        df_base = ocorrencias_filtradas[['NRVINCULOM', 'Funcionario', 'Escola']].drop_duplicates('NRVINCULOM').set_index('NRVINCULOM')
        resumo = df_base.join(s_faltas, how='left').join(s_atrasos, how='left').join(s_datas, how='left').fillna(0).reset_index()
        
        resumo['Qtd_Faltas'] = resumo['Qtd_Faltas'].astype(int)
        resumo['Tempo_Atraso_Fmt'] = resumo['Total_Horas_Atraso'].apply(decimal_para_hora)

        # KPIs
        ids_com_problema = set(resumo['NRVINCULOM'].unique())
        df_sem = df_funcionarios[~df_funcionarios['NRVINCULOM'].isin(ids_com_problema)]

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Total Analisado", len(df_funcionarios))
        k2.metric("✅ Ponto Excelente", len(df_sem), delta_color="normal")
        k3.metric("Com Ocorrências", len(resumo), delta_color="inverse")
        k4.metric("Faltas Totais", resumo['Qtd_Faltas'].sum())
        
        st.divider()
        st.info("💡 **Dica:** Clique na linha da tabela para abrir o Espelho de Ponto detalhado.")

        tab1, tab2, tab3, tab4 = st.tabs(["🏆 Ranking Faltas", "📉 Ranking Atrasos", "✅ Ponto Excelente", "📋 Base Completa"])
        
        # --- TAB 1: FALTAS (COM CLIQUE) ---
        with tab1:
            if not resumo.empty:
                df_show = resumo[resumo['Qtd_Faltas'] > 0].sort_values(by='Qtd_Faltas', ascending=False)
                event1 = st.dataframe(
                    df_show[['NRVINCULOM', 'Funcionario', 'Escola', 'Qtd_Faltas', 'Datas']],
                    use_container_width=True, hide_index=True,
                    selection_mode="single-row", on_select="rerun", key="grid_faltas",
                    column_config={"Qtd_Faltas": st.column_config.NumberColumn("Dias Falta", format="%d ❌")}
                )
                if len(event1.selection.rows) > 0:
                    idx = event1.selection.rows[0]
                    row_data = df_show.iloc[idx]
                    mostrar_espelho_modal(row_data['Funcionario'], row_data['NRVINCULOM'], periodo_apuracao)
            else: st.info("Sem faltas.")
            
        # --- TAB 2: ATRASOS (COM CLIQUE) ---
        with tab2:
            if not resumo.empty:
                df_show2 = resumo[resumo['Total_Horas_Atraso'] > 0].sort_values(by='Total_Horas_Atraso', ascending=False)
                event2 = st.dataframe(
                    df_show2[['NRVINCULOM', 'Funcionario', 'Escola', 'Tempo_Atraso_Fmt', 'Datas']],
                    use_container_width=True, hide_index=True,
                    selection_mode="single-row", on_select="rerun", key="grid_atrasos",
                    column_config={"Tempo_Atraso_Fmt": st.column_config.TextColumn("Horas Totais")}
                )
                if len(event2.selection.rows) > 0:
                    idx = event2.selection.rows[0]
                    row_data = df_show2.iloc[idx]
                    mostrar_espelho_modal(row_data['Funcionario'], row_data['NRVINCULOM'], periodo_apuracao)
            else: st.info("Sem atrasos.")

        # --- TAB 3: SEM OCORRÊNCIAS ---
        with tab3:
            st.dataframe(df_sem[['NRVINCULOM', 'NMVINCULOM', 'NMESTRUTGEREN']], use_container_width=True, hide_index=True)

        # --- TAB 4: GERAL (COM CLIQUE) ---
        with tab4:
            if not resumo.empty:
                event4 = st.dataframe(
                    resumo, use_container_width=True, hide_index=True,
                    selection_mode="single-row", on_select="rerun", key="grid_geral"
                )
                if len(event4.selection.rows) > 0:
                    idx = event4.selection.rows[0]
                    row_data = resumo.iloc[idx]
                    mostrar_espelho_modal(row_data['Funcionario'], row_data['NRVINCULOM'], periodo_apuracao)
                
                csv = resumo.to_csv(index=False, sep=';', encoding='utf-8-sig')
                st.download_button("📥 Baixar CSV", csv, "relatorio.csv", "text/csv")