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
# 4. BANCO DE DADOS - VALIDAÇÃO & SNAPSHOT
# ==============================================================================
def clean_id(val):
    """
    Padroniza ID para string numérica pura.
    Remove .0, espaços e converte float/int para str.
    Essencial para o match do banco funcionar.
    """
    try:
        if pd.isna(val): return "0"
        # Converte para float primeiro (para pegar '123.0'), depois int, depois str
        return str(int(float(val)))
    except:
        return str(val).strip()

def save_validacao_batch_snapshot(conn, df_changes, periodo, usuario_responsavel):
    """
    Salva validação + Quem validou + Snapshot
    """
    if df_changes.empty: return
    
    user_safe = usuario_responsavel if usuario_responsavel else "Sistema"
    
    try:
        with conn.session as session:
            for index, row in df_changes.iterrows():
                try:
                    # O ID no banco é BigInt, garantimos conversão correta
                    colab_id = int(float(row['NRVINCULOM']))
                except: continue

                proc_bool = bool(row['Procedente'])
                snap_faltas = int(row.get('Qtd_Faltas', 0))
                snap_horas = float(row.get('Total_Horas_Atraso', 0.0))

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
                    'per': str(periodo),
                    'proc': proc_bool,
                    'user': user_safe,
                    'sf': snap_faltas,
                    'sh': snap_horas
                })
            session.commit()
        st.toast(f"{len(df_changes)} Validações salvas!", icon="✅")
    except Exception as e:
        st.error(f"Erro ao salvar: {e}")

def fetch_validacoes_completo(conn, periodo):
    """Busca Validação, Usuário e Snapshot anterior"""
    try:
        query = text('SELECT "ColaboradorID", "Procedente", "UsuarioResponsavel", "QtdFaltasSnapshot", "HorasAtrasoSnapshot" FROM "ValidacaoPonto" WHERE "Periodo" = :per')
        df = conn.query(query, params={'per': str(periodo)}, ttl=0)
        
        if not df.empty:
            # AQUI ESTÁ O TRUQUE: Força converter o ID do banco para String Limpa
            # Isso garante que bate com o ID do DataFrame principal
            df['ColaboradorID'] = df['ColaboradorID'].apply(clean_id)
            
            def format_snap(row):
                f = int(row['QtdFaltasSnapshot']) if pd.notnull(row['QtdFaltasSnapshot']) else 0
                h = float(row['HorasAtrasoSnapshot']) if pd.notnull(row['HorasAtrasoSnapshot']) else 0.0
                if f == 0 and h == 0: return "-"
                h_fmt = decimal_para_hora(h)
                return f"{f} Faltas | {h_fmt}h"

            df['SnapshotTexto'] = df.apply(format_snap, axis=1)

            d_proc = dict(zip(df['ColaboradorID'], df['Procedente']))
            d_user = dict(zip(df['ColaboradorID'], df['UsuarioResponsavel']))
            d_snap = dict(zip(df['ColaboradorID'], df['SnapshotTexto']))
            
            return d_proc, d_user, d_snap
            
    except Exception as e: 
        print(f"Erro fetch DB: {e}")
        pass
    return {}, {}, {}

@st.cache_data(ttl=600)
def fetch_dados_supervisores_completo():
    try:
        conn = st.connection("postgres", type="sql")
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
            df_map['Matricula'] = df_map['Matricula'].apply(clean_id)
            df_map['Supervisor'] = df_map['Supervisor'].str.strip().str.upper()
            mapa_sup = dict(zip(df_map['Matricula'], df_map['Supervisor']))

        q2 = 'SELECT "NomeSupervisor", "Celular" FROM "Supervisores"'
        df_tel = conn.query(q2)
        mapa_tel = {}
        if not df_tel.empty:
            mapa_tel = dict(zip(
                df_tel['NomeSupervisor'].str.strip().str.upper(), 
                df_tel['Celular']
            ))
        return mapa_sup, mapa_tel
    except Exception as e:
        return {}, {}

# ==============================================================================
# 5. API FERIADOS & HELPERS
# ==============================================================================
@st.cache_data(ttl=86400)
def fetch_feriados_brasil(ano):
    url = f"https://brasilapi.com.br/api/feriados/v1/{ano}"
    try:
        r = requests.get(url, timeout=5)
        if r.status_code == 200: return r.json() 
    except: pass
    return []

def get_feriados_set(anos_lista):
    feriados_dict = {}
    if not anos_lista: anos_lista = [datetime.now().year]
    for ano in anos_lista:
        dados = fetch_feriados_brasil(ano)
        if dados:
            for f in dados: feriados_dict[f['date']] = f['name']
        else:
            feriados_dict.update({
                f"{ano}-01-01": "Confraternização Universal",
                f"{ano}-04-21": "Tiradentes",
                f"{ano}-05-01": "Dia do Trabalho",
                f"{ano}-09-07": "Independência do Brasil",
                f"{ano}-10-12": "Nossa Senhora Aparecida",
                f"{ano}-11-02": "Finados",
                f"{ano}-11-15": "Proclamação da República",
                f"{ano}-11-20": "Dia da Consciência Negra",
                f"{ano}-12-25": "Natal"
            })
    return feriados_dict

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
# 6. API PORTAL GESTOR & HCM
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
        "requestType": "FilterData", "DIA": data_ref.strftime("%d/%m/%Y"),
        "NRESTRUTURAM": codigo_estrutura, "NRORG": PG_NR_ORG, "CDOPERADOR": PG_CD_OPERADOR
    }
    headers = { "OAuth-Token": PG_TOKEN, "OAuth-Cdoperador": PG_CD_OPERADOR, "OAuth-Nrorg": PG_NR_ORG, "User-Agent": "Mozilla/5.0" }
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
# 7. MODAIS E DIALOGS
# ==============================================================================
@st.cache_data(ttl=300)
def fetch_dias_demonstrativo(vinculo, periodo):
    url = "https://portalgestor.teknisa.com/backend/index.php/getDiasDemonstrativo"
    params = {
        "requestType": "FilterData", "NRVINCULOM": str(vinculo).split('.')[0],
        "NRPERIODOAPURACAO": periodo, "NRORG": PG_NR_ORG, "CDOPERADOR": PG_CD_OPERADOR
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
        cols_order = [c for c in ['DTAPURACAO', 'DSPONTODIA', 'ENTRADA_SAIDA_1', 'ENTRADA_SAIDA_2'] if c in df.columns]
        other_cols = [c for c in df.columns if c not in cols_order]
        st.dataframe(df[cols_order + other_cols], use_container_width=True, hide_index=True)
    else:
        st.warning("Sem dados detalhados.")

@st.dialog("📢 Disparar Alertas de Ponto", width="large")
def dialog_alertas_ponto(df_resumo, mapa_tel, periodo):
    st.caption(f"Envio de cobrança sobre Faltas e Atrasos (Período: {periodo})")
    
    # Filtra: Só exibe quem tem Score > 0 e NÃO foi validado
    df_probs = df_resumo[(df_resumo['ScoreNum'] > 0) & (df_resumo['Procedente'] == False)].copy()

    if df_probs.empty:
        st.success("Tudo validado ou sem ocorrências! Nenhuma cobrança pendente.")
        return

    supervisores = sorted(df_probs['Supervisor'].unique())

    for sup in supervisores:
        with st.container(border=True):
            c1, c2 = st.columns([3, 1])
            
            df_sup = df_probs[df_probs['Supervisor'] == sup]
            total_f = df_sup['Qtd_Faltas'].sum()
            total_h = df_sup['Total_Horas_Atraso'].sum() 
            
            # Monta Mensagem
            msg_lines = [f"Ola *{sup}*, verificacao de ponto ({periodo}):"]
            msg_lines.append("")
            
            for _, row in df_sup.iterrows():
                detalhes = []
                if row['Qtd_Faltas'] > 0: detalhes.append(f"{row['Qtd_Faltas']} Faltas")
                if row['Total_Horas_Atraso'] > 0: detalhes.append(f"{decimal_para_hora(row['Total_Horas_Atraso'])}h Atraso")
                
                if detalhes:
                    msg_lines.append(f"👤 *{row['Funcionario']}*")
                    msg_lines.append(f"⚠️ {', '.join(detalhes)}")
                    if row['Datas']: msg_lines.append(f"📅 Dias: {row['Datas']}")
                    msg_lines.append("")
            
            msg_lines.append("Por favor, verificar se procede.")
            msg_final = "\n".join(msg_lines)

            tel = mapa_tel.get(sup)

            with c1:
                st.markdown(f"**👤 {sup}**")
                st.caption(f"Pendências: {len(df_sup)} colaboradores")
                with st.expander("Ver mensagem"):
                    st.text(msg_final)
            
            with c2:
                if tel:
                    link = gerar_link_whatsapp(tel, msg_final)
                    st.link_button("📲 Enviar", link, use_container_width=True) # Botão padrão (secondary)
                else:
                    st.warning("Sem Celular")

# ==============================================================================
# 8. LÓGICA PRINCIPAL (UI)
# ==============================================================================

st.title("⚡ Diagnóstico de Ponto (Criticidade)")
st.caption("Visão unificada de Faltas, Atrasos e Validações.")

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

# --- EXECUÇÃO ---
if st.session_state["busca_realizada"]:
    
    # SE FOR A PRIMEIRA VEZ, BUSCA TUDO
    if not st.session_state["dados_cache"]:
        with st.status("🔄 Buscando dados iniciais...", expanded=True) as status:
            df_func = fetch_ids_portal_gestor(data_ref, est_id)
            if df_func.empty:
                status.update(label="❌ Sem funcionários.", state="error")
                st.session_state["busca_realizada"] = False; st.stop()
            
            mapa_supervisores, mapa_telefones = fetch_dados_supervisores_completo()
            
            if 'NMESTRUTGEREN' not in df_func.columns: df_func['NMESTRUTGEREN'] = "GERAL"
            
            lista_ids = df_func['NRVINCULOM'].dropna().astype(int).unique().tolist()
            token = obter_sessao_hcm()
            if not token:
                status.update(label="❌ Erro Login HCM.", state="error")
                st.session_state["busca_realizada"] = False; st.stop()
                
            df_oco = fetch_ocorrencias_hcm_turbo(token, lista_ids, per_id, mes_hcm)
            
            st.session_state["dados_cache"] = {
                "funcionarios": df_func, 
                "ocorrencias": df_oco, 
                "periodo": per_id, 
                "mapa_sup": mapa_supervisores,
                "mapa_tel": mapa_telefones,
                # Validacoes serão buscadas fora do cache "congelado" para atualização em tempo real
            }
            status.update(label="Pronto!", state="complete", expanded=False)
    
    # ----------------------------------------------------------------------
    # BUSCA DE VALIDAÇÕES DO BANCO (SEMPRE FRESCA)
    # Isso garante que se você der F5, ele pega o estado atual do banco
    # ----------------------------------------------------------------------
    conn = st.connection("postgres", type="sql")
    d_proc, d_user, d_snap = fetch_validacoes_completo(conn, st.session_state["dados_cache"]["periodo"])
    
    # Atualiza o cache local com as validações frescas
    st.session_state["dados_cache"]["validacoes"] = d_proc
    st.session_state["dados_cache"]["usuarios_validacao"] = d_user
    st.session_state["dados_cache"]["snapshots"] = d_snap
    # ----------------------------------------------------------------------

    # Recupera Cache
    df_func = st.session_state["dados_cache"]["funcionarios"].copy()
    df_oco = st.session_state["dados_cache"]["ocorrencias"].copy()
    per_cache = st.session_state["dados_cache"]["periodo"]
    mapa_sup = st.session_state["dados_cache"]["mapa_sup"]
    mapa_tel = st.session_state["dados_cache"]["mapa_tel"]
    
    dict_validacoes = st.session_state["dados_cache"]["validacoes"]
    dict_usuarios = st.session_state["dados_cache"]["usuarios_validacao"]
    dict_snapshots = st.session_state["dados_cache"]["snapshots"]

    # --- APLICAÇÃO DOS MAPAS ---
    # ESSENCIAL: Padronizar chave de ID para STRING LIMPA para garantir match com o dicionário
    df_func['NRVINCULOM'] = df_func['NRVINCULOM'].apply(clean_id)
    
    df_func['Supervisor'] = df_func['NRVINCULOM'].map(mapa_sup).fillna("NÃO IDENTIFICADO")
    mapa_nome = dict(zip(df_func['NRVINCULOM'], df_func['NMVINCULOM']))
    
    # --- FILTRO DE SUPERVISOR ---
    if filtro_sup_sidebar:
        df_func = df_func[df_func['Supervisor'].isin(filtro_sup_sidebar)]
        # Se filtrou supervisor, reduz a lista de IDs válidos
        valid_ids = df_func['NRVINCULOM'].unique()
        if not df_oco.empty:
            df_oco['NRVINCULOM'] = df_oco['NRVINCULOM'].apply(clean_id)
            df_oco = df_oco[df_oco['NRVINCULOM'].isin(valid_ids)]

    # 3. PROCESSAMENTO
    hoje = datetime.now().strftime('%Y-%m-%d')
    
    # Cria Base Mestra com Todos os Funcionários do Filtro
    df_mestra = df_func[['NRVINCULOM', 'NMVINCULOM', 'Supervisor']].rename(columns={'NMVINCULOM':'Funcionario'}).copy()
    
    if not df_oco.empty:
        df_oco['DIFF_HOURS'] = pd.to_numeric(df_oco['DIFF_HOURS'], errors='coerce').fillna(0)
        df_oco['NRVINCULOM'] = df_oco['NRVINCULOM'].apply(clean_id)
        df_oco['DATA_INICIO_FILTER'] = df_oco['DATA_INICIO_FILTER'].astype(str)
        df_oco['TIPO_OCORRENCIA'] = df_oco['TIPO_OCORRENCIA'].str.strip().str.upper()

        # Filtros de Data
        df_oco = df_oco[df_oco['DATA_INICIO_FILTER'] != hoje].copy()
        df_oco['DT_OBJ'] = pd.to_datetime(df_oco['DATA_INICIO_FILTER'], errors='coerce')
        
        anos = df_oco['DT_OBJ'].dt.year.unique().tolist()
        feriados = get_feriados_set(anos)
        
        df_oco['DIA_SEMANA'] = df_oco['DT_OBJ'].dt.dayofweek 
        df_oco['IS_FERIADO'] = df_oco['DATA_INICIO_FILTER'].map(lambda x: x in feriados)
        
        # Ocorrências Válidas
        df_faltas = df_oco[
            (df_oco['TIPO_OCORRENCIA'] == 'FALTA') & 
            (df_oco['DIA_SEMANA'] < 5) & (df_oco['IS_FERIADO'] == False)
        ].copy()
        
        df_atrasos = df_oco[df_oco['TIPO_OCORRENCIA'] == 'ATRASO'].copy()

        # Agregações
        s_faltas = df_faltas.drop_duplicates(subset=['NRVINCULOM', 'DATA_INICIO']).groupby('NRVINCULOM').size().rename('Qtd_Faltas')
        s_atrasos = df_atrasos.groupby('NRVINCULOM')['DIFF_HOURS'].sum().rename('Total_Horas_Atraso')
        s_datas = df_oco.groupby('NRVINCULOM')['DATA_INICIO'].unique().apply(lambda x: ", ".join(sorted(x))).rename('Datas')

        # Join na Mestra
        df_mestra = df_mestra.set_index('NRVINCULOM')
        df_mestra = df_mestra.join(s_faltas).join(s_atrasos).join(s_datas).fillna(0).reset_index()
    else:
        df_mestra['Qtd_Faltas'] = 0
        df_mestra['Total_Horas_Atraso'] = 0.0
        df_mestra['Datas'] = ""

    # CÁLCULO DE CRITICIDADE (0 a 10)
    df_mestra['ScoreNum'] = (df_mestra['Qtd_Faltas'] * 10) + (df_mestra['Total_Horas_Atraso'] / 8.0 * 5)
    df_mestra['ScoreNum'] = df_mestra['ScoreNum'].apply(lambda x: 10 if x > 10 else x)
    
    def fmt_score(val):
        if val == 0: return "OK"
        return f"{val:.1f}"
    
    df_mestra['Criticidade Ponto'] = df_mestra['ScoreNum'].apply(fmt_score)

    # Colunas de Banco
    # AGORA O DICT_VALIDACOES E O DF_MESTRA USAM STRINGS LIMPAS PARA O MATCH
    df_mestra['Procedente'] = df_mestra['NRVINCULOM'].map(dict_validacoes).fillna(False)
    df_mestra['ValidadoPor'] = df_mestra['NRVINCULOM'].map(dict_usuarios).fillna("-")
    df_mestra['UltimaValidacao'] = df_mestra['NRVINCULOM'].map(dict_snapshots).fillna("-")
    
    df_mestra['Tempo_Atraso_Fmt'] = df_mestra['Total_Horas_Atraso'].apply(decimal_para_hora)

    # KPIs
    c1, c2, c3, c4 = st.columns(4)
    total_colab = len(df_mestra)
    
    df_ok = df_mestra[(df_mestra['ScoreNum'] == 0) | (df_mestra['Procedente'] == True)]
    df_critico = df_mestra[(df_mestra['ScoreNum'] > 0) & (df_mestra['Procedente'] == False)]
    
    c1.metric("Total Colaboradores", total_colab)
    c2.metric("✅ Validados / OK", len(df_ok))
    c3.metric("⚠️ Pendentes / Críticos", len(df_critico), delta_color="inverse")
    c4.metric("Índice Risco", f"{df_critico['ScoreNum'].mean():.1f}" if not df_critico.empty else "0.0", help="Média do score dos pendentes")

    # BOTÃO ALERTAS
    st.divider()
    c_alert, _ = st.columns([1, 4])
    with c_alert:
        if st.button("📢 Central de Alertas", use_container_width=True):
            dialog_alertas_ponto(df_mestra, mapa_tel, per_cache)

    # GRÁFICO EMPILHADO (AZUL E VERMELHO)
    st.subheader("📊 Status da Equipe por Supervisor")
    
    def categorizar_simples(row):
        if row['ScoreNum'] == 0 or row['Procedente']: 
            return "Resolvido/Ok"
        return "Pendência"
    
    df_mestra['StatusGrafico'] = df_mestra.apply(categorizar_simples, axis=1)
    
    df_chart = df_mestra.groupby(['Supervisor', 'StatusGrafico']).size().reset_index(name='Qtd')
    
    color_map = {
        "Resolvido/Ok": "#007bff", # Azul
        "Pendência": "#dc3545"     # Vermelho
    }
    
    fig = px.bar(
        df_chart, 
        x='Supervisor', 
        y='Qtd', 
        color='StatusGrafico',
        color_discrete_map=color_map,
        title="Pendências vs Resolvidos",
        text_auto=True
    )
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")

    # TABELA UNIFICADA
    st.subheader("📋 Painel de Controle Unificado")
    st.caption("Ordenado por criticidade. Use a caixa 'Ok?' para validar as pendências.")

    df_show = df_mestra.sort_values(by=['ScoreNum'], ascending=False).copy()
    
    with st.form("form_painel"):
        edited_df = st.data_editor(
            df_show[[
                'Procedente', 
                'Criticidade Ponto', 
                'Qtd_Faltas', 
                'Tempo_Atraso_Fmt', 
                'Funcionario', 
                'NRVINCULOM', 
                'ValidadoPor', 
                'UltimaValidacao',
                'Datas',
                'Total_Horas_Atraso', # Hidden
                'ScoreNum' # Hidden
            ]],
            use_container_width=True,
            hide_index=True,
            column_config={
                "Procedente": st.column_config.CheckboxColumn("Ok?", help="Marque para validar", default=False),
                "Criticidade Ponto": st.column_config.TextColumn("Criticidade", help="10 = Crítico (Falta). OK = Sem problemas."),
                "Qtd_Faltas": st.column_config.NumberColumn("Faltas", format="%d ❌"),
                "Tempo_Atraso_Fmt": st.column_config.TextColumn("Atrasos"),
                "Funcionario": st.column_config.TextColumn("Colaborador", width="medium"),
                "NRVINCULOM": st.column_config.TextColumn("Matrícula", disabled=True),
                "ValidadoPor": st.column_config.TextColumn("Validado Por", disabled=True),
                "UltimaValidacao": st.column_config.TextColumn("Snapshot", disabled=True),
                "Datas": st.column_config.TextColumn("Detalhe Datas", width="large"),
                "Total_Horas_Atraso": None,
                "ScoreNum": None
            },
            key="editor_painel"
        )
        
        if st.form_submit_button("💾 Salvar Alterações"):
            dict_changes = st.session_state.get("editor_painel", {}).get("edited_rows", {})
            
            if not dict_changes:
                st.info("Nenhuma alteração para salvar.")
            else:
                indices_modificados = list(dict_changes.keys())
                df_to_save = edited_df.iloc[indices_modificados].copy()
                
                conn = st.connection("postgres", type="sql")
                usuario_atual = st.session_state.get("name", "Usuario Desconhecido")
                
                save_validacao_batch_snapshot(conn, df_to_save, per_cache, usuario_atual)
                
                # A atualização do cache é feita no rerun, pois fetch_validacoes_completo está fora do cache congelado
                st.rerun()

    # DOWNLOAD
    csv = df_mestra.to_csv(index=False, sep=';', encoding='utf-8-sig')
    st.download_button("📥 Baixar Relatório Completo", csv, f"relatorio_diagnostico_{per_cache}.csv", "text/csv")