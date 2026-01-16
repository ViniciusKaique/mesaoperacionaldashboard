import streamlit as st
import requests
import pandas as pd
import pytz
from datetime import datetime
from sqlalchemy import text
import plotly.express as px  # Added for charts

# ==============================================================================
# 1. PAGE CONFIGURATION
# ==============================================================================
st.set_page_config(page_title="HCM - Occurrences (Turbo)", layout="wide", page_icon="⚡")

# ==============================================================================
# 2. SECURITY AND CREDENTIALS
# ==============================================================================
if not st.session_state.get("authentication_status"):
    st.warning("🔒 Restricted access. Please log in on the home page.")
    st.stop()

# --- HCM CREDENTIALS ---
try:
    SECRETS_HCM = st.secrets["hcm_api"]
    HCM_USER = SECRETS_HCM["usuario"]
    HCM_PASS = SECRETS_HCM["senha"]
    HCM_HASH = SECRETS_HCM["hash_sessao"]
    HCM_UID_BROWSER = SECRETS_HCM["user_id_browser"]
    HCM_PROJECT = SECRETS_HCM.get("project_id", "750")
except Exception as e:
    st.error(f"⚠️ HCM Config Error: {e}")
    st.stop()

# --- PORTAL GESTOR CREDENTIALS ---
try:
    SECRETS_PG = st.secrets["api_portal_gestor"]
    PG_TOKEN = SECRETS_PG["token_fixo"]
    PG_CD_OPERADOR = SECRETS_PG["cd_operador"]
    PG_NR_ORG = SECRETS_PG["nr_org"]
except Exception as e:
    st.error(f"⚠️ Portal Gestor Config Error: {e}")
    st.stop()

# ==============================================================================
# 3. DATABASE (SUPERVISORS MAPPING)
# ==============================================================================
@st.cache_data(ttl=600)
def fetch_dados_auxiliares_db():
    """Fetches School -> Supervisor relationship from DB"""
    try:
        conn = st.connection("postgres", type="sql")
        
        # Relation School -> Supervisor
        q_unidades = """
        SELECT u."NomeUnidade" as "Escola", s."NomeSupervisor" as "Supervisor"
        FROM "Unidades" u
        JOIN "Supervisores" s ON u."SupervisorID" = s."SupervisorID"
        """
        df_unidades = conn.query(q_unidades)
        
        # Create dictionary {School Name: Supervisor Name}
        # Normalizing to uppercase to ensure matching
        if not df_unidades.empty:
            df_unidades['Escola'] = df_unidades['Escola'].str.strip().str.upper()
            df_unidades['Supervisor'] = df_unidades['Supervisor'].str.strip().str.upper()
            return dict(zip(df_unidades['Escola'], df_unidades['Supervisor']))
            
        return {}
    except Exception as e:
        st.error(f"DB Error: {e}")
        return {}

# ==============================================================================
# 4. HCM SESSION MANAGEMENT
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
# 5. API PORTAL GESTOR
# ==============================================================================
@st.cache_data(ttl=3600)
def fetch_estruturas_gestor():
    url = "https://portalgestor.teknisa.com/backend/index.php/getEstruturasGerenciais"
    params = { "requestType": "FilterData", "NRORG": PG_NR_ORG, "CDOPERADOR": PG_CD_OPERADOR }
    headers = { "OAuth-Token": PG_TOKEN, "OAuth-Cdoperador": PG_CD_OPERADOR, "OAuth-Nrorg": PG_NR_ORG, "User-Agent": "Mozilla/5.0" }
    try:
        r = requests.get(url, params=params, headers=headers, timeout=15)
        if r.status_code == 200:
            data = r.json()
            items = (data.get("dataset", {}) or {}).get("data", [])
            return [(i.get("NMESTRUTURA", "Sem Nome"), i.get("NRESTRUTURAM")) for i in items]
    except: pass
    return []

def fetch_ids_portal_gestor(data_ref, codigo_estrutura):
    url = "https://portalgestor.teknisa.com/backend/index.php/getMesaOperacoes"
    params = {
        "requestType": "FilterData",
        "DIA": data_ref.strftime("%d/%m/%Y"),
        "NRESTRUTURAM": codigo_estrutura,
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
# 6. API HCM - OCORRÊNCIAS
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
# 7. API HCM - DETALHES (MODAL)
# ==============================================================================
@st.cache_data(ttl=300)
def fetch_dias_demonstrativo(vinculo, periodo):
    url = "https://portalgestor.teknisa.com/backend/index.php/getDiasDemonstrativo"
    params = {
        "requestType": "FilterData",
        "NRVINCULOM": str(vinculo).split('.')[0],
        "NRPERIODOAPURACAO": periodo,
        "NRORG": PG_NR_ORG, "CDOPERADOR": PG_CD_OPERADOR
    }
    headers = { "OAuth-Token": PG_TOKEN, "OAuth-Cdoperador": PG_CD_OPERADOR, "OAuth-Nrorg": PG_NR_ORG }
    try:
        r = requests.get(url, params=params, headers=headers, timeout=15)
        if r.status_code == 200:
            items = r.json().get("dataset", {}).get("data", [])
            return pd.DataFrame(items)
    except: pass
    return pd.DataFrame()

@st.dialog("📅 Espelho de Ponto", width="large")
def mostrar_espelho_modal(nome, vinculo, periodo):
    st.write(f"**{nome}** (Matrícula: {vinculo})")
    with st.spinner("Buscando dados..."):
        df = fetch_dias_demonstrativo(vinculo, periodo)
    if not df.empty:
        # Tenta ordenar as colunas para melhor visualização
        cols_order = [c for c in ['DTAPURACAO', 'DSPONTODIA', 'ENTRADA_SAIDA_1', 'ENTRADA_SAIDA_2'] if c in df.columns]
        other_cols = [c for c in df.columns if c not in cols_order]
        st.dataframe(df[cols_order + other_cols], use_container_width=True, hide_index=True)
    else:
        st.warning("Sem dados detalhados.")

# ==============================================================================
# 8. LÓGICA PRINCIPAL
# ==============================================================================

st.title("⚡ Relatório Turbo - Faltas e Atrasos (HCM)")
st.markdown("**Modo Otimizado:** Ignora dia vigente, desconta fins de semana e destaca feriados.")

# --- ESTADO ---
if "busca_realizada" not in st.session_state: st.session_state["busca_realizada"] = False
if "dados_cache" not in st.session_state: st.session_state["dados_cache"] = {}

with st.sidebar:
    st.header("Parâmetros")
    
    # ESTRUTURA
    est_opcoes = fetch_estruturas_gestor()
    est_id = "101091998"
    if est_opcoes:
        sel = st.selectbox("🏢 Tomador:", options=est_opcoes, format_func=lambda x: x[0])
        est_id = sel[1]
    
    st.divider()
    
    # PERIODO
    df_per = fetch_periodos_apuracao()
    per_id = "1904"
    comp_sug = datetime.now().replace(day=1).strftime("%d/%m/%Y")
    
    if not df_per.empty:
        opcao = st.selectbox("Período:", df_per['DSPERIODOAPURACAO'])
        row = df_per[df_per['DSPERIODOAPURACAO'] == opcao].iloc[0]
        per_id = row['NRPERIODOAPURACAO']
        try:
            comp_sug = datetime.strptime(row['DTINICIALAPURACAO'], "%d/%m/%Y").replace(day=1).strftime("%d/%m/%Y")
        except: pass
    else:
        per_id = st.text_input("Cód. Período", value="1904")

    mes_hcm = st.text_input("Mês Comp. (HCM)", value=comp_sug)
    data_ref = st.date_input("Data Ref. Ativos", datetime.now())
    
    st.divider()
    if st.button("🚀 Disparar Análise", use_container_width=True):
        st.session_state["busca_realizada"] = True
        st.session_state["dados_cache"] = {} 
        st.rerun()

# --- EXECUÇÃO ---
if st.session_state["busca_realizada"]:
    
    # 1. BUSCA (CACHE)
    if not st.session_state["dados_cache"]:
        with st.status("🔄 Buscando dados...", expanded=True) as status:
            df_func = fetch_ids_portal_gestor(data_ref, est_id)
            if df_func.empty:
                status.update(label="❌ Sem funcionários.", state="error")
                st.session_state["busca_realizada"] = False; st.stop()
            
            # Mapas de Supervisor (DB)
            mapa_supervisores = fetch_dados_auxiliares_db() # Dictionary {Escola: Supervisor}
            
            if 'NMESTRUTGEREN' not in df_func.columns: df_func['NMESTRUTGEREN'] = "GERAL"
            
            lista_ids = df_func['NRVINCULOM'].dropna().astype(int).unique().tolist()
            token = obter_sessao_hcm()
            if not token:
                status.update(label="❌ Erro Login HCM.", state="error")
                st.session_state["busca_realizada"] = False; st.stop()
                
            df_oco = fetch_ocorrencias_hcm_turbo(token, lista_ids, per_id, mes_hcm)
            
            st.session_state["dados_cache"] = {
                "funcionarios": df_func, "ocorrencias": df_oco, "periodo": per_id, "mapa_sup": mapa_supervisores
            }
            status.update(label="Pronto!", state="complete", expanded=False)

    df_func = st.session_state["dados_cache"]["funcionarios"].copy()
    df_oco = st.session_state["dados_cache"]["ocorrencias"].copy()
    per_cache = st.session_state["dados_cache"]["periodo"]
    mapa_sup = st.session_state["dados_cache"]["mapa_sup"]

    # 2. FILTRO POSTO LOCAL
    postos = sorted(df_func['NMESTRUTGEREN'].dropna().unique().tolist())
    f1, f2 = st.columns([3, 1])
    with f1:
        sel_postos = st.multiselect("🔍 Filtrar Posto:", postos, placeholder="Todos")
    
    if sel_postos:
        df_func = df_func[df_func['NMESTRUTGEREN'].isin(sel_postos)]
        if not df_oco.empty:
            df_oco['NRVINCULOM'] = df_oco['NRVINCULOM'].astype(str)
            ids_validos = df_func['NRVINCULOM'].astype(str).tolist()
            df_oco = df_oco[df_oco['NRVINCULOM'].isin(ids_validos)]

    # 3. PROCESSAMENTO
    hoje = datetime.now().strftime('%Y-%m-%d')
    
    if df_oco.empty:
        st.success("🎉 Nenhuma ocorrência encontrada!")
    else:
        # Prepara Dados
        df_oco['DIFF_HOURS'] = pd.to_numeric(df_oco['DIFF_HOURS'], errors='coerce').fillna(0)
        df_oco['NRVINCULOM'] = df_oco['NRVINCULOM'].astype(str)
        df_oco['DATA_INICIO_FILTER'] = df_oco['DATA_INICIO_FILTER'].astype(str)
        df_oco['TIPO_OCORRENCIA'] = df_oco['TIPO_OCORRENCIA'].str.strip().str.upper()
        
        # Mapas
        df_func['NRVINCULOM'] = df_func['NRVINCULOM'].astype(str)
        map_nome = dict(zip(df_func['NRVINCULOM'], df_func['NMVINCULOM']))
        map_esc = dict(zip(df_func['NRVINCULOM'], df_func['NMESTRUTGEREN']))
        
        df_oco['Funcionario'] = df_oco['NRVINCULOM'].map(map_nome).fillna(df_oco['NMVINCULOM'])
        df_oco['Escola'] = df_oco['NRVINCULOM'].map(map_esc).fillna(df_oco['NMESTRUTGEREN'])
        
        # Mapeamento do Supervisor
        # Normaliza chaves para garantir match
        df_oco['Escola_Upper'] = df_oco['Escola'].str.strip().str.upper()
        df_oco['Supervisor'] = df_oco['Escola_Upper'].map(mapa_sup).fillna("NÃO IDENTIFICADO")

        # --- FILTRO 1: REMOVE HOJE ---
        df_oco = df_oco[df_oco['DATA_INICIO_FILTER'] != hoje].copy()

        # --- FILTRO 2: REMOVE FIM DE SEMANA (PARA FALTAS) ---
        df_oco['DT_OBJ'] = pd.to_datetime(df_oco['DATA_INICIO_FILTER'], errors='coerce')
        df_oco['DIA_SEMANA'] = df_oco['DT_OBJ'].dt.dayofweek # 0=Seg, 5=Sab, 6=Dom
        
        # Separa Faltas Válidas (Seg-Sex)
        df_faltas_uteis = df_oco[
            (df_oco['TIPO_OCORRENCIA'] == 'FALTA') & 
            (df_oco['DIA_SEMANA'] < 5)
        ].copy()
        
        # DF ATRASOS (Conta tudo)
        df_atrasos_all = df_oco[df_oco['TIPO_OCORRENCIA'] == 'ATRASO'].copy()

        # --- AGREGAÇÕES ---
        
        # 1. FALTAS ÚTEIS (Dedup por dia)
        s_faltas = df_faltas_uteis.drop_duplicates(subset=['NRVINCULOM', 'DATA_INICIO']).groupby('NRVINCULOM').size().rename('Qtd_Faltas')
        
        # 2. ATRASOS (Soma horas)
        s_atrasos = df_atrasos_all.groupby('NRVINCULOM')['DIFF_HOURS'].sum().rename('Total_Horas_Atraso')
        
        # 3. DATAS (Visual)
        s_datas = df_oco.groupby('NRVINCULOM')['DATA_INICIO'].unique().apply(lambda x: ", ".join(sorted(x))).rename('Datas')

        # JOIN FINAL
        # Note: Agora incluimos Supervisor no agrupamento base
        df_base = df_oco[['NRVINCULOM', 'Funcionario', 'Escola', 'Supervisor']].drop_duplicates('NRVINCULOM').set_index('NRVINCULOM')
        resumo = df_base.join(s_faltas, how='left').join(s_atrasos, how='left').join(s_datas, how='left').fillna(0).reset_index()
        
        resumo['Qtd_Faltas'] = resumo['Qtd_Faltas'].astype(int)
        resumo['Tempo_Atraso_Fmt'] = resumo['Total_Horas_Atraso'].apply(decimal_para_hora)

        # SEM OCORRÊNCIAS
        ids_prob = set(resumo['NRVINCULOM'].unique())
        
        # Prepara o DF de Sem Ocorrencias com Supervisor também
        df_sem = df_func[~df_func['NRVINCULOM'].isin(ids_prob)].copy()
        df_sem['Escola_Upper'] = df_sem['NMESTRUTGEREN'].str.strip().str.upper()
        df_sem['Supervisor'] = df_sem['Escola_Upper'].map(mapa_sup).fillna("NÃO IDENTIFICADO")
        df_sem = df_sem[['NRVINCULOM', 'NMVINCULOM', 'NMESTRUTGEREN', 'Supervisor']].rename(columns={'NMVINCULOM':'Funcionario', 'NMESTRUTGEREN':'Escola'})

        # KPIs
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Analisado", len(df_func))
        c2.metric("✅ Ponto Excelente", len(df_sem), delta_color="normal")
        c3.metric("Com Ocorrências", len(resumo), delta_color="inverse")
        c4.metric("Faltas (Dias Úteis)", resumo['Qtd_Faltas'].sum(), delta_color="inverse")

        st.divider()
        
        # ==================== GRÁFICO POR SUPERVISOR ====================
        st.subheader("📊 Visão por Supervisor")
        
        # Prepara dados para o gráfico
        # Agrupa Ponto Excelente por Supervisor
        grp_excelente = df_sem.groupby('Supervisor').size().reset_index(name='Ponto Excelente')
        
        # Agrupa Com Ocorrencias por Supervisor
        grp_problema = resumo.groupby('Supervisor').size().reset_index(name='Com Ocorrências')
        
        # Merge para plotagem
        df_chart = pd.merge(grp_excelente, grp_problema, on='Supervisor', how='outer').fillna(0)
        
        # Plotly Graph
        fig = px.bar(
            df_chart, 
            x='Supervisor', 
            y=['Ponto Excelente', 'Com Ocorrências'],
            barmode='group',
            color_discrete_map={'Ponto Excelente': '#28a745', 'Com Ocorrências': '#dc3545'},
            text_auto=True
        )
        fig.update_layout(yaxis_title="Qtd. Funcionários", xaxis_title=None, legend_title=None)
        st.plotly_chart(fig, use_container_width=True)
        # =================================================================
        
        st.markdown("---")

        # ABAS
        t1, t2, t3, t4 = st.tabs(["🏆 Ranking Faltas", "📉 Ranking Atrasos", "✅ Ponto Excelente", "📋 Base Completa"])
        
        func_abrir = None
        
        with t1:
            st.caption("Considerando apenas dias úteis (Seg-Sex).")
            # Agora exibe Supervisor
            df_show = resumo[resumo['Qtd_Faltas'] > 0].sort_values(by='Qtd_Faltas', ascending=False)
            ev = st.dataframe(
                df_show[['NRVINCULOM', 'Funcionario', 'Supervisor', 'Escola', 'Qtd_Faltas', 'Datas']], 
                use_container_width=True, hide_index=True, selection_mode="single-row", on_select="rerun", key="t1",
                column_config={"Qtd_Faltas": st.column_config.NumberColumn("Dias", format="%d ❌")}
            )
            if ev.selection.rows: func_abrir = df_show.iloc[ev.selection.rows[0]]

        with t2:
            # Agora exibe Supervisor
            df_show2 = resumo[resumo['Total_Horas_Atraso'] > 0].sort_values(by='Total_Horas_Atraso', ascending=False)
            ev2 = st.dataframe(
                df_show2[['NRVINCULOM', 'Funcionario', 'Supervisor', 'Escola', 'Tempo_Atraso_Fmt', 'Datas']], 
                use_container_width=True, hide_index=True, selection_mode="single-row", on_select="rerun", key="t2",
                column_config={"Tempo_Atraso_Fmt": st.column_config.TextColumn("Horas Totais")}
            )
            if ev2.selection.rows: func_abrir = df_show2.iloc[ev2.selection.rows[0]]

        with t3:
            # Agora exibe Supervisor
            st.dataframe(df_sem[['NRVINCULOM', 'Funcionario', 'Supervisor', 'Escola']], use_container_width=True, hide_index=True)

        with t4:
            st.dataframe(resumo, use_container_width=True, hide_index=True)
            csv = resumo.to_csv(index=False, sep=';', encoding='utf-8-sig')
            st.download_button("📥 Baixar CSV Consolidado", csv, f"relatorio_{per_cache}.csv", "text/csv")

        if func_abrir is not None:
            mostrar_espelho_modal(func_abrir['Funcionario'], func_abrir['NRVINCULOM'], per_cache)