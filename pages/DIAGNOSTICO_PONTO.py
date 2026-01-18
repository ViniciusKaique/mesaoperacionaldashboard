import streamlit as st
import requests
import pandas as pd
import pytz
import urllib.parse
from datetime import datetime
from sqlalchemy import text
import plotly.express as px

# ==============================================================================
# 1. CONFIGURAÇÃO DA PÁGINA
# ==============================================================================
st.set_page_config(page_title="HCM - Criticidade Ponto", layout="wide", page_icon="⚡")

# ==============================================================================
# 2. SEGURANÇA E CREDENCIAIS
# ==============================================================================
if not st.session_state.get("authentication_status"):
    st.warning("🔒 Acesso restrito. Faça login na página inicial.")
    st.stop()

# --- CREDENCIAIS ---
try:
    SECRETS_HCM = st.secrets["hcm_api"]
    SECRETS_PG = st.secrets["api_portal_gestor"]
    
    HCM_USER = SECRETS_HCM["usuario"]
    HCM_PASS = SECRETS_HCM["senha"]
    HCM_HASH = SECRETS_HCM["hash_sessao"]
    HCM_UID_BROWSER = SECRETS_HCM["user_id_browser"]
    HCM_PROJECT = SECRETS_HCM.get("project_id", "750")
    
    PG_TOKEN = SECRETS_PG["token_fixo"]
    PG_CD_OPERADOR = SECRETS_PG["cd_operador"]
    PG_NR_ORG = SECRETS_PG["nr_org"]
except Exception as e:
    st.error(f"⚠️ Erro de Configuração (Secrets): {e}")
    st.stop()

# ==============================================================================
# 3. CONVERSÃO SEGURA DE TIPOS (A "BLINDAGEM")
# ==============================================================================
def safe_int(val):
    """Converte qualquer coisa para Inteiro. Se falhar, retorna 0."""
    try:
        if pd.isna(val): return 0
        return int(float(val)) # float lida com "123.0"
    except:
        return 0

def safe_str(val):
    """Garante string limpa."""
    if pd.isna(val): return ""
    return str(val).strip()

# ==============================================================================
# 4. GESTÃO DE SESSÃO HCM
# ==============================================================================
def get_data_brasil():
    return datetime.now(pytz.timezone('America/Sao_Paulo'))

def init_db_token(conn):
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
    conn = st.connection("postgres", type="sql")
    init_db_token(conn)
    token, uid = get_token_db(conn)
    if token:
        # Testa token
        headers = {"OAuth-Token": token, "OAuth-Hash": HCM_HASH, "User-Id": HCM_UID_BROWSER, "OAuth-Project": HCM_PROJECT, "Content-Type": "application/json"}
        try:
            r = requests.post("https://hcm.teknisa.com/backend/index.php/getPessoa", headers=headers, json={"page":1,"itemsPerPage":1,"requestType":"FilterData"}, timeout=5)
            if r.status_code == 200: return token
        except: pass
    
    # Se falhou, login novo
    new_token, new_uid = login_hcm_novo()
    if new_token:
        save_token_db(conn, new_token, new_uid)
        return new_token
    return None

# ==============================================================================
# 5. BANCO DE DADOS - VALIDAÇÃO (O CORAÇÃO DO PROBLEMA)
# ==============================================================================

def salvar_validacoes(conn, df_changes, periodo_str, usuario):
    """Salva no banco. Recebe Periodo como STRING e IDs como INT."""
    if df_changes.empty: return
    
    usuario_safe = usuario if usuario else "Sistema"
    
    try:
        with conn.session as session:
            for index, row in df_changes.iterrows():
                # BLINDAGEM DE TIPO: Garante que ID é int e Periodo é str
                colab_id = safe_int(row['NRVINCULOM'])
                if colab_id == 0: continue # Pula ID inválido

                proc_bool = bool(row['Procedente'])
                snap_faltas = safe_int(row.get('Qtd_Faltas', 0))
                snap_horas = float(row.get('Total_Horas_Atraso', 0.0))

                # Query SQL com ON CONFLICT (Upsert)
                query = text("""
                    INSERT INTO "ValidacaoPonto" 
                    ("ColaboradorID", "Periodo", "Procedente", "DataVerificacao", "UsuarioResponsavel", "QtdFaltasSnapshot", "HorasAtrasoSnapshot")
                    VALUES (:cid, :per, :proc, NOW(), :user, :sf, :sh)
                    ON CONFLICT ("ColaboradorID", "Periodo") 
                    DO UPDATE SET 
                        "Procedente" = EXCLUDED."Procedente", 
                        "DataVerificacao" = NOW(),
                        "UsuarioResponsavel" = EXCLUDED."UsuarioResponsavel",
                        "QtdFaltasSnapshot" = EXCLUDED."QtdFaltasSnapshot",
                        "HorasAtrasoSnapshot" = EXCLUDED."HorasAtrasoSnapshot";
                """)
                
                session.execute(query, {
                    'cid': colab_id,
                    'per': str(periodo_str), 
                    'proc': proc_bool,
                    'user': usuario_safe,
                    'sf': snap_faltas,
                    'sh': snap_horas
                })
            session.commit()
        st.toast(f"✅ {len(df_changes)} registros salvos no banco!", icon="💾")
    except Exception as e:
        st.error(f"Erro ao salvar no banco: {e}")

def fetch_validacoes_ativo(conn, periodo_str):
    """Busca validações SEM CACHE para garantir dados frescos."""
    try:
        query = text('SELECT "ColaboradorID", "Procedente", "UsuarioResponsavel", "QtdFaltasSnapshot", "HorasAtrasoSnapshot" FROM "ValidacaoPonto" WHERE "Periodo" = :per')
        # TTL=0 é essencial aqui!
        df = conn.query(query, params={'per': str(periodo_str)}, ttl=0)
        
        if not df.empty:
            # BLINDAGEM: Converte ID do banco para INT para bater com a API
            df['ColaboradorID'] = df['ColaboradorID'].apply(safe_int)
            return df
            
    except Exception as e:
        # st.error(f"Erro leitura DB: {e}") 
        pass
    
    # Retorna vazio se der erro ou não tiver dados
    return pd.DataFrame(columns=["ColaboradorID", "Procedente", "UsuarioResponsavel", "QtdFaltasSnapshot", "HorasAtrasoSnapshot"])

@st.cache_data(ttl=600)
def fetch_dados_supervisores():
    try:
        conn = st.connection("postgres", type="sql")
        # Busca Supervisores
        q1 = """
        SELECT col."ColaboradorID" as "Matricula", s."NomeSupervisor" as "Supervisor"
        FROM "Colaboradores" col
        JOIN "Unidades" u ON col."UnidadeID" = u."UnidadeID"
        JOIN "Supervisores" s ON u."SupervisorID" = s."SupervisorID"
        WHERE col."Ativo" = TRUE
        """
        df_map = conn.query(q1)
        mapa_sup = {}
        if not df_map.empty:
            # BLINDAGEM: ID vira INT
            df_map['Matricula'] = df_map['Matricula'].apply(safe_int)
            df_map['Supervisor'] = df_map['Supervisor'].str.strip().str.upper()
            mapa_sup = dict(zip(df_map['Matricula'], df_map['Supervisor']))

        # Busca Celulares
        q2 = 'SELECT "NomeSupervisor", "Celular" FROM "Supervisores"'
        df_tel = conn.query(q2)
        mapa_tel = {}
        if not df_tel.empty:
            mapa_tel = dict(zip(
                df_tel['NomeSupervisor'].str.strip().str.upper(), 
                df_tel['Celular']
            ))
        return mapa_sup, mapa_tel
    except:
        return {}, {}

# ==============================================================================
# 6. APIs GERAIS
# ==============================================================================
@st.cache_data(ttl=86400)
def fetch_feriados_brasil(ano):
    try:
        r = requests.get(f"https://brasilapi.com.br/api/feriados/v1/{ano}", timeout=5)
        if r.status_code == 200: return r.json() 
    except: pass
    return []

def get_feriados_set(anos_lista):
    feriados = {}
    if not anos_lista: anos_lista = [datetime.now().year]
    for ano in anos_lista:
        dados = fetch_feriados_brasil(ano)
        if dados:
            for f in dados: feriados[f['date']] = f['name']
        else:
            feriados.update({f"{ano}-01-01": "Confraternização", f"{ano}-12-25": "Natal"})
    return feriados

def decimal_para_hora(val):
    try:
        if pd.isna(val) or val == 0: return "00:00"
        horas = int(val)
        minutos = int((val - horas) * 60)
        return f"{horas:02d}:{minutos:02d}"
    except: return "00:00"

def gerar_link_whatsapp(telefone, mensagem):
    texto_encoded = urllib.parse.quote_plus(mensagem)
    fone_limpo = "".join(filter(str.isdigit, str(telefone))) if telefone else ""
    return f"https://api.whatsapp.com/send?phone=55{fone_limpo}&text={texto_encoded}"

# ==============================================================================
# 7. APIs GESTOR
# ==============================================================================
@st.cache_data(ttl=3600)
def fetch_estruturas_gestor():
    url = "https://portalgestor.teknisa.com/backend/index.php/getEstruturasGerenciais"
    params = { "requestType": "FilterData", "NRORG": PG_NR_ORG, "CDOPERADOR": PG_CD_OPERADOR }
    headers = { "OAuth-Token": PG_TOKEN, "OAuth-Cdoperador": PG_CD_OPERADOR, "OAuth-Nrorg": PG_NR_ORG, "User-Agent": "Mozilla/5.0" }
    try:
        r = requests.get(url, params=params, headers=headers, timeout=15)
        if r.status_code == 200:
            items = r.json().get("dataset", {}).get("data", [])
            return [(i.get("NMESTRUTURA", "Sem Nome"), i.get("NRESTRUTURAM")) for i in items]
    except: pass
    return []

def fetch_ids_portal_gestor(data_ref, codigo_estrutura):
    url = "https://portalgestor.teknisa.com/backend/index.php/getMesaOperacoes"
    params = {
        "requestType": "FilterData", "DIA": data_ref.strftime("%d/%m/%Y"),
        "NRESTRUTURAM": codigo_estrutura, "NRORG": PG_NR_ORG, "CDOPERADOR": PG_CD_OPERADOR
    }
    headers = { "OAuth-Token": PG_TOKEN, "OAuth-Cdoperador": PG_CD_OPERADOR, "OAuth-Nrorg": PG_NR_ORG, "User-Agent": "Mozilla/5.0" }
    try:
        r = requests.get(url, params=params, headers=headers, timeout=30)
        if r.status_code == 200:
            data = r.json()
            if "dataset" in data and "data" in data["dataset"]:
                return pd.DataFrame(data["dataset"]["data"])
    except: pass
    return pd.DataFrame()

@st.cache_data(ttl=3600) 
def fetch_periodos_apuracao():
    url = "https://portalgestor.teknisa.com/backend/index.php/getPeriodosDemonstrativo"
    params = { "requestType": "FilterData", "NRORG": PG_NR_ORG, "CDOPERADOR": PG_CD_OPERADOR }
    headers = { "OAuth-Token": PG_TOKEN, "OAuth-Cdoperador": PG_CD_OPERADOR, "OAuth-Nrorg": PG_NR_ORG, "User-Agent": "Mozilla/5.0" }
    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json().get("dataset", {}).get("data", [])
            return pd.DataFrame(data)
    except: pass
    return pd.DataFrame()

def fetch_ocorrencias_hcm_turbo(token, lista_ids, periodo_apuracao, mes_competencia):
    url = "https://hcm.teknisa.com/backend/index.php/getMarcacaoPontoOcorrencias"
    headers = {
        "User-Agent": "Mozilla/5.0", "Content-Type": "application/json",
        "OAuth-Token": token, "OAuth-Hash": HCM_HASH, "OAuth-Project": HCM_PROJECT, "User-Id": HCM_UID_BROWSER, "OAuth-KeepConnected": "Yes"
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
            return pd.DataFrame(r.json().get("dataset", {}).get("getMarcacaoPontoOcorrencias", []))
    except: pass
    return pd.DataFrame()

@st.dialog("📢 Disparar Alertas", width="large")
def dialog_alertas_ponto(df_resumo, mapa_tel, periodo):
    st.caption(f"Alertas de Ponto - Período {periodo}")
    df_probs = df_resumo[(df_resumo['ScoreNum'] > 0) & (df_resumo['Procedente'] == False)].copy()
    
    if df_probs.empty:
        st.success("Nada pendente!")
        return

    supervisores = sorted(df_probs['Supervisor'].unique())
    for sup in supervisores:
        with st.container(border=True):
            c1, c2 = st.columns([3, 1])
            df_sup = df_probs[df_probs['Supervisor'] == sup]
            
            msg = [f"Ola *{sup}*, verificacao de ponto ({periodo}):\n"]
            for _, row in df_sup.iterrows():
                probs = []
                if row['Qtd_Faltas'] > 0: probs.append(f"{row['Qtd_Faltas']} Faltas")
                if row['Total_Horas_Atraso'] > 0: probs.append(f"{decimal_para_hora(row['Total_Horas_Atraso'])}h Atraso")
                msg.append(f"👤 *{row['Funcionario']}*: {', '.join(probs)}")
            
            msg.append("\nPor favor, verificar se procede.")
            msg_final = "\n".join(msg)
            tel = mapa_tel.get(sup)
            
            with c1:
                st.markdown(f"**{sup}** ({len(df_sup)} pendências)")
            with c2:
                if tel:
                    st.link_button("📲 Enviar", gerar_link_whatsapp(tel, msg_final), use_container_width=True)
                else:
                    st.warning("Sem nº")

# ==============================================================================
# 8. UI PRINCIPAL
# ==============================================================================
st.title("⚡ Diagnóstico de Ponto (Criticidade)")

if "busca_realizada" not in st.session_state: st.session_state["busca_realizada"] = False
if "dados_cache" not in st.session_state: st.session_state["dados_cache"] = {}

with st.sidebar:
    st.header("Parâmetros")
    est_opcoes = fetch_estruturas_gestor()
    est_id = "101091998"
    if est_opcoes:
        sel = st.selectbox("🏢 Tomador:", options=est_opcoes, format_func=lambda x: x[0])
        est_id = sel[1]
    
    st.divider()
    
    df_per = fetch_periodos_apuracao()
    per_id_default = "1904"
    comp_sug = datetime.now().replace(day=1).strftime("%d/%m/%Y")
    
    if not df_per.empty:
        opcao = st.selectbox("Período:", df_per['DSPERIODOAPURACAO'])
        row = df_per[df_per['DSPERIODOAPURACAO'] == opcao].iloc[0]
        per_id_default = str(row['NRPERIODOAPURACAO'])
    
    # Campo TEXTO para garantir que não haja conversão automática
    per_id = st.text_input("Cód. Período", value=per_id_default)
    mes_hcm = st.text_input("Mês Comp. (HCM)", value=comp_sug)
    data_ref = st.date_input("Data Ref. Ativos", datetime.now())
    
    filtro_sup_sidebar = []
    if st.session_state.get("busca_realizada") and "mapa_sup" in st.session_state["dados_cache"]:
        mapa = st.session_state["dados_cache"]["mapa_sup"]
        if mapa:
            lista_sup = sorted(list(set(mapa.values())))
            filtro_sup_sidebar = st.multiselect("Filtrar Supervisor:", lista_sup)

    st.divider()
    if st.button("🚀 Disparar Análise", use_container_width=True):
        st.session_state["busca_realizada"] = True
        st.session_state["dados_cache"] = {} 
        st.rerun()

# --- LÓGICA DE CARREGAMENTO E MESTRAGEM ---
if st.session_state["busca_realizada"]:
    
    # 1. BUSCA PESADA (API) - COM CACHE
    if not st.session_state["dados_cache"]:
        with st.status("🔄 Buscando dados APIs...", expanded=True) as status:
            df_func = fetch_ids_portal_gestor(data_ref, est_id)
            if df_func.empty:
                status.update(label="❌ Sem funcionários.", state="error")
                st.session_state["busca_realizada"] = False; st.stop()
            
            mapa_supervisores, mapa_telefones = fetch_dados_supervisores()
            
            lista_ids = df_func['NRVINCULOM'].dropna().astype(int).unique().tolist()
            token = obter_sessao_hcm()
            if not token:
                status.update(label="❌ Erro Login HCM.", state="error")
                st.stop()
                
            df_oco = fetch_ocorrencias_hcm_turbo(token, lista_ids, per_id, mes_hcm)
            
            st.session_state["dados_cache"] = {
                "funcionarios": df_func, 
                "ocorrencias": df_oco, 
                "periodo": per_id, 
                "mapa_sup": mapa_supervisores,
                "mapa_tel": mapa_telefones,
            }
            status.update(label="Pronto!", state="complete", expanded=False)
            
    # 2. BUSCA DO BANCO (SEM CACHE - SEMPRE ATUAL)
    conn = st.connection("postgres", type="sql")
    # Busca a tabela ValidacaoPonto fresquinha
    df_validacoes_db = fetch_validacoes_ativo(conn, st.session_state["dados_cache"]["periodo"])

    # 3. UNIFICAÇÃO
    df_func = st.session_state["dados_cache"]["funcionarios"].copy()
    df_oco = st.session_state["dados_cache"]["ocorrencias"].copy()
    mapa_sup = st.session_state["dados_cache"]["mapa_sup"]
    
    # Normalização de IDs (INT)
    df_func['NRVINCULOM'] = df_func['NRVINCULOM'].apply(safe_int)
    if not df_oco.empty: df_oco['NRVINCULOM'] = df_oco['NRVINCULOM'].apply(safe_int)
    
    df_func['Supervisor'] = df_func['NRVINCULOM'].map(mapa_sup).fillna("NÃO IDENTIFICADO")
    
    # Filtro Supervisor
    if filtro_sup_sidebar:
        df_func = df_func[df_func['Supervisor'].isin(filtro_sup_sidebar)]
        if not df_oco.empty: df_oco = df_oco[df_oco['NRVINCULOM'].isin(df_func['NRVINCULOM'])]

    # Monta Mestra
    hoje = datetime.now().strftime('%Y-%m-%d')
    df_mestra = df_func[['NRVINCULOM', 'NMVINCULOM', 'Supervisor']].rename(columns={'NMVINCULOM':'Funcionario'}).copy()
    
    if not df_oco.empty:
        df_oco['DIFF_HOURS'] = pd.to_numeric(df_oco['DIFF_HOURS'], errors='coerce').fillna(0)
        df_oco['TIPO_OCORRENCIA'] = df_oco['TIPO_OCORRENCIA'].str.strip().str.upper()
        # Remove hoje
        df_oco = df_oco[df_oco['DATA_INICIO_FILTER'].astype(str) != hoje].copy()
        
        # Filtros dias uteis
        df_oco['DT_OBJ'] = pd.to_datetime(df_oco['DATA_INICIO_FILTER'], errors='coerce')
        feriados = get_feriados_set(df_oco['DT_OBJ'].dt.year.unique().tolist())
        df_oco['IS_FERIADO'] = df_oco['DATA_INICIO_FILTER'].map(lambda x: x in feriados)
        
        df_faltas = df_oco[(df_oco['TIPO_OCORRENCIA'] == 'FALTA') & (df_oco['DT_OBJ'].dt.dayofweek < 5) & (~df_oco['IS_FERIADO'])]
        df_atrasos = df_oco[df_oco['TIPO_OCORRENCIA'] == 'ATRASO']
        
        s_faltas = df_faltas.groupby('NRVINCULOM').size().rename('Qtd_Faltas')
        s_atrasos = df_atrasos.groupby('NRVINCULOM')['DIFF_HOURS'].sum().rename('Total_Horas_Atraso')
        s_datas = df_oco.groupby('NRVINCULOM')['DATA_INICIO'].unique().apply(lambda x: ", ".join(sorted(x))).rename('Datas')
        
        df_mestra = df_mestra.set_index('NRVINCULOM').join(s_faltas).join(s_atrasos).join(s_datas).fillna(0).reset_index()
    else:
        df_mestra['Qtd_Faltas'] = 0; df_mestra['Total_Horas_Atraso'] = 0; df_mestra['Datas'] = ""

    # Score
    df_mestra['ScoreNum'] = (df_mestra['Qtd_Faltas'] * 10) + (df_mestra['Total_Horas_Atraso'] / 8.0 * 5)
    df_mestra['ScoreNum'] = df_mestra['ScoreNum'].apply(lambda x: 10 if x > 10 else x)
    df_mestra['Criticidade Ponto'] = df_mestra['ScoreNum'].apply(lambda x: "OK" if x == 0 else f"{x:.1f}")

    # =========================================================================
    # MERGE COM O BANCO DE DADOS (CRUZAMENTO INT -> INT)
    # =========================================================================
    # df_mestra['NRVINCULOM'] já é int (safe_int). 
    # df_validacoes_db['ColaboradorID'] já é int (safe_int).
    
    df_final = pd.merge(df_mestra, df_validacoes_db, left_on='NRVINCULOM', right_on='ColaboradorID', how='left')
    
    df_final['Procedente'] = df_final['Procedente'].fillna(False)
    df_final['UsuarioResponsavel'] = df_final['UsuarioResponsavel'].fillna("-")
    
    def fmt_snap(row):
        f = safe_int(row['QtdFaltasSnapshot'])
        h = float(row['HorasAtrasoSnapshot']) if pd.notnull(row['HorasAtrasoSnapshot']) else 0.0
        return f"{f} Faltas | {decimal_para_hora(h)}h" if (f>0 or h>0) else "-"
        
    df_final['UltimaValidacao'] = df_final.apply(fmt_snap, axis=1)
    df_final['Tempo_Atraso_Fmt'] = df_final['Total_Horas_Atraso'].apply(decimal_para_hora)

    # 4. EXIBIÇÃO
    c1, c2, c3, c4 = st.columns(4)
    df_pendente = df_final[(df_final['ScoreNum'] > 0) & (df_final['Procedente'] == False)]
    c1.metric("Total Colaboradores", len(df_final))
    c2.metric("✅ Resolvidos/Ok", len(df_final) - len(df_pendente))
    c3.metric("⚠️ Pendentes", len(df_pendente), delta_color="inverse")
    c4.metric("Índice Risco", f"{df_pendente['ScoreNum'].mean():.1f}" if not df_pendente.empty else "0.0")

    st.divider()
    c_alert, _ = st.columns([1, 4])
    with c_alert:
        if st.button("📢 Central de Alertas", use_container_width=True):
            dialog_alertas_ponto(df_final, st.session_state["dados_cache"]["mapa_tel"], per_id)

    # GRÁFICO
    df_final['StatusGrafico'] = df_final.apply(lambda x: "Pendência" if (x['ScoreNum'] > 0 and not x['Procedente']) else "Resolvido/Ok", axis=1)
    df_chart = df_final.groupby(['Supervisor', 'StatusGrafico']).size().reset_index(name='Qtd')
    fig = px.bar(df_chart, x='Supervisor', y='Qtd', color='StatusGrafico', color_discrete_map={"Resolvido/Ok": "#007bff", "Pendência": "#dc3545"}, text_auto=True)
    st.plotly_chart(fig, use_container_width=True)

    # TABELA EDITOR
    st.subheader("📋 Painel de Controle Unificado")
    df_show = df_final.sort_values(by=['ScoreNum'], ascending=False).copy()
    
    with st.form("painel_validacao"):
        edited_df = st.data_editor(
            df_show[[
                'Procedente', 'Criticidade Ponto', 'Qtd_Faltas', 'Tempo_Atraso_Fmt', 
                'Funcionario', 'NRVINCULOM', 'UsuarioResponsavel', 'UltimaValidacao', 
                'Datas', 'Total_Horas_Atraso', 'ScoreNum'
            ]],
            use_container_width=True, hide_index=True,
            column_config={
                "Procedente": st.column_config.CheckboxColumn("Ok?", default=False),
                "Criticidade Ponto": st.column_config.TextColumn("Criticidade"),
                "Qtd_Faltas": st.column_config.NumberColumn("Faltas", format="%d ❌"),
                "NRVINCULOM": st.column_config.TextColumn("Matrícula", disabled=True),
                "UsuarioResponsavel": st.column_config.TextColumn("Validado Por", disabled=True),
                "UltimaValidacao": st.column_config.TextColumn("Snapshot", disabled=True),
                "Datas": st.column_config.TextColumn("Detalhe", width="large"),
                "Total_Horas_Atraso": None, "ScoreNum": None
            },
            key="editor_painel"
        )
        
        if st.form_submit_button("💾 Salvar Alterações"):
            # Detecta mudanças
            changes = st.session_state.get("editor_painel", {}).get("edited_rows", {})
            if not changes:
                st.info("Nada alterado.")
            else:
                rows_to_save = edited_df.iloc[list(changes.keys())].copy()
                conn = st.connection("postgres", type="sql")
                user_now = st.session_state.get("name", "Usuario Desconhecido")
                
                # Salva usando INT ID e STRING Periodo (Conforme o banco novo)
                salvar_validacoes(conn, rows_to_save, per_id, user_now)
                st.rerun()

    csv = df_final.to_csv(index=False, sep=';', encoding='utf-8-sig')
    st.download_button("📥 Baixar Relatório", csv, f"relatorio_{per_id}.csv", "text/csv")