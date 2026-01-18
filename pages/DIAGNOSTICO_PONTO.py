import streamlit as st
import requests
import pandas as pd
import pytz
import urllib.parse
from datetime import datetime
from sqlalchemy import text
import plotly.express as px

# ==============================================================================
# 1. CONFIGURAÇÃO E SEGURANÇA
# ==============================================================================
st.set_page_config(page_title="HCM - Diagnóstico (Rollback)", layout="wide", page_icon="⚡")

if not st.session_state.get("authentication_status"):
    st.warning("🔒 Faça login na página inicial.")
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
    st.error(f"Erro Secrets: {e}")
    st.stop()

# ==============================================================================
# 2. BANCO DE DADOS (LÓGICA SIMPLES QUE FUNCIONAVA)
# ==============================================================================

def salvar_no_banco(conn, df_alterado, periodo_int, usuario):
    """
    Salva as alterações. Simples e direto.
    """
    if df_alterado.empty: return
    
    user_name = usuario if usuario else "Sistema"
    
    try:
        with conn.session as session:
            for index, row in df_alterado.iterrows():
                # Conversão básica para garantir integridade
                try:
                    c_id = int(float(row['NRVINCULOM'])) # Garante 123
                    p_id = int(periodo_int)              # Garante 1904
                except:
                    continue # Se não tiver ID, pula

                proc = bool(row['Procedente'])
                
                # Dados do momento (Snapshot)
                snap_f = int(row.get('Qtd_Faltas', 0))
                snap_h = float(row.get('Total_Horas_Atraso', 0.0))

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
                    'cid': c_id,
                    'per': p_id,
                    'proc': proc,
                    'user': user_name,
                    'sf': snap_f,
                    'sh': snap_h
                })
            session.commit()
        st.toast("✅ Salvo com sucesso!", icon="💾")
    except Exception as e:
        st.error(f"Erro ao salvar: {e}")

def buscar_do_banco(conn, periodo_int):
    """
    Busca tudo do banco para este período.
    Retorna um DataFrame para fazermos o MERGE (cruzamento) depois.
    """
    try:
        p_id = int(periodo_int)
        query = text('SELECT * FROM "ValidacaoPonto" WHERE "Periodo" = :per')
        # TTL=0 obriga a buscar dados frescos
        df = conn.query(query, params={'per': str(p_id)}, ttl=0) # Tente mandar como string pro parametro, postgres as vezes prefere
        
        if not df.empty:
            # Garante que o ID de ligação seja do mesmo tipo da API (Int)
            df['ColaboradorID'] = pd.to_numeric(df['ColaboradorID'], errors='coerce').fillna(0).astype(int)
            return df
    except Exception as e:
        # st.write(f"Debug DB: {e}") 
        pass
    
    # Retorna vazio mas com colunas certas para não quebrar
    return pd.DataFrame(columns=["ColaboradorID", "Procedente", "UsuarioResponsavel", "QtdFaltasSnapshot", "HorasAtrasoSnapshot"])

# ==============================================================================
# 3. HELPERS DE SESSÃO HCM
# ==============================================================================
def get_data_brasil(): return datetime.now(pytz.timezone('America/Sao_Paulo'))

def obter_sessao_hcm():
    # Simplificado para focar no problema principal
    conn = st.connection("postgres", type="sql")
    try:
        # Tenta pegar token salvo
        df = conn.query("SELECT access_token FROM public.\"HCMTokens\" WHERE id = 'bot_hcm_contact'", ttl=0)
        if not df.empty:
            token = df.iloc[0]['access_token']
            # Teste rápido
            headers = {"OAuth-Token": token, "OAuth-Hash": HCM_HASH, "User-Id": HCM_UID_BROWSER, "OAuth-Project": HCM_PROJECT, "Content-Type": "application/json"}
            r = requests.post("https://hcm.teknisa.com/backend/index.php/getPessoa", headers=headers, json={"page":1,"itemsPerPage":1,"requestType":"FilterData"}, timeout=5)
            if r.status_code == 200: return token
    except: pass

    # Login novo se falhar
    url = "https://hcm.teknisa.com/backend_login/index.php/login"
    payload = {
        "disableLoader": False,
        "filter": [
            {"name": "EMAIL", "operator": "=", "value": HCM_USER},
            {"name": "PASSWORD", "operator": "=", "value": HCM_PASS},
            {"name": "PRODUCT_ID", "operator": "=", "value": int(HCM_PROJECT)},
            {"name": "HASH", "operator": "=", "value": HCM_HASH},
            {"name": "KEEP_CONNECTED", "operator": "=", "value": "S"}
        ],
        "page": 1, "requestType": "FilterData"
    }
    try:
        r = requests.post(url, json=payload, timeout=20)
        data = r.json()
        if "dataset" in data and "userData" in data["dataset"]:
            new_token = data["dataset"]["userData"].get("TOKEN")
            new_uid = data["dataset"]["userData"].get("USER_ID")
            # Salva
            with conn.session as session:
                session.execute(text("""
                    CREATE TABLE IF NOT EXISTS public."HCMTokens" (id VARCHAR(50) PRIMARY KEY, access_token TEXT, user_uid TEXT, updated_at TIMESTAMP);
                    INSERT INTO public."HCMTokens" (id, access_token, user_uid, updated_at) VALUES ('bot_hcm_contact', :t, :u, :h)
                    ON CONFLICT (id) DO UPDATE SET access_token = :t, updated_at = :h;
                """), {"t": new_token, "u": new_uid, "h": get_data_brasil()})
                session.commit()
            return new_token
    except: pass
    return None

# ==============================================================================
# 4. APIs DE DADOS (HCM e PORTAL)
# ==============================================================================
@st.cache_data(ttl=600)
def fetch_dados_base_completa():
    # Busca Supervisores
    conn = st.connection("postgres", type="sql")
    try:
        q = 'SELECT "ColaboradorID", "NomeSupervisor", "Celular" FROM "Supervisores" s JOIN "Unidades" u ON s."SupervisorID" = u."SupervisorID" JOIN "Colaboradores" c ON u."UnidadeID" = c."UnidadeID" WHERE c."Ativo" = TRUE'
        df = conn.query(q)
        if not df.empty:
            df['ColaboradorID'] = pd.to_numeric(df['ColaboradorID'], errors='coerce').fillna(0).astype(int)
            # Cria mapas
            map_sup = dict(zip(df['ColaboradorID'], df['NomeSupervisor'].str.upper()))
            map_tel = dict(zip(df['NomeSupervisor'].str.upper(), df['Celular']))
            return map_sup, map_tel
    except: pass
    return {}, {}

def fetch_ids_portal(data_ref, est_id):
    url = "https://portalgestor.teknisa.com/backend/index.php/getMesaOperacoes"
    params = {"requestType": "FilterData", "DIA": data_ref.strftime("%d/%m/%Y"), "NRESTRUTURAM": est_id, "NRORG": PG_NR_ORG, "CDOPERADOR": PG_CD_OPERADOR}
    headers = { "OAuth-Token": PG_TOKEN, "OAuth-Cdoperador": PG_CD_OPERADOR, "OAuth-Nrorg": PG_NR_ORG }
    try:
        r = requests.get(url, params=params, headers=headers, timeout=20)
        df = pd.DataFrame(r.json()["dataset"]["data"])
        if not df.empty and 'NMSITUFUNCH' in df.columns:
            return df[df['NMSITUFUNCH'].str.strip() == 'Atividade Normal']
    except: pass
    return pd.DataFrame()

def fetch_ocorrencias(token, lista_ids, periodo, mes):
    url = "https://hcm.teknisa.com/backend/index.php/getMarcacaoPontoOcorrencias"
    headers = {"OAuth-Token": token, "OAuth-Hash": HCM_HASH, "OAuth-Project": HCM_PROJECT, "User-Id": HCM_UID_BROWSER}
    payload = {
        "filter": [
            {"name": "P_NRORG", "value": "3260", "operator": "="},
            {"name": "P_DTMESCOMPETENC", "value": mes, "operator": "="},
            {"name": "NRPERIODOAPURACAO", "value": int(periodo), "operator": "=", "isCustomFilter": True},
            {"name": "NRVINCULOM_LIST", "value": lista_ids, "operator": "IN", "isCustomFilter": True},
            {"name": "P_TIPOOCORRENCIA", "value": ["ATRASO", "FALTA"], "operator": "IN", "isCustomFilter": True}
        ],
        "requestType": "FilterData"
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=60)
        return pd.DataFrame(r.json()["dataset"]["getMarcacaoPontoOcorrencias"])
    except: pass
    return pd.DataFrame()

# ==============================================================================
# 5. UI - TELA
# ==============================================================================
if "busca_realizada" not in st.session_state: st.session_state["busca_realizada"] = False
if "dados_cache" not in st.session_state: st.session_state["dados_cache"] = {}

with st.sidebar:
    st.header("Filtros")
    # Estrutura Fixa para simplificar
    est_id = "101091998"
    
    # Período (Input Numérico para forçar INT)
    per_id = st.number_input("Período (Cód)", value=1904, step=1)
    
    mes_hcm = st.text_input("Mês (DD/MM/AAAA)", value=datetime.now().replace(day=1).strftime("%d/%m/%Y"))
    data_ref = st.date_input("Data Ref", datetime.now())
    
    if st.button("🚀 Processar", type="primary"):
        st.session_state["busca_realizada"] = True
        st.session_state["dados_cache"] = {} # Limpa cache antigo
        st.rerun()

# --- LÓGICA PRINCIPAL ---
if st.session_state["busca_realizada"]:
    
    # 1. BUSCA API (Só roda se não tiver cache)
    if not st.session_state["dados_cache"]:
        with st.status("Buscando dados...", expanded=True) as status:
            df_func = fetch_ids_portal(data_ref, est_id)
            if df_func.empty:
                st.error("Ninguém encontrado no Portal Gestor."); st.stop()
                
            mapa_sup, mapa_tel = fetch_dados_base_completa()
            
            # Garante INT nos IDs
            df_func['NRVINCULOM'] = pd.to_numeric(df_func['NRVINCULOM'], errors='coerce').fillna(0).astype(int)
            ids = df_func['NRVINCULOM'].unique().tolist()
            
            token = obter_sessao_hcm()
            df_oco = fetch_ocorrencias(token, ids, per_id, mes_hcm)
            
            if not df_oco.empty:
                df_oco['NRVINCULOM'] = pd.to_numeric(df_oco['NRVINCULOM'], errors='coerce').fillna(0).astype(int)
                df_oco['DIFF_HOURS'] = pd.to_numeric(df_oco['DIFF_HOURS'], errors='coerce').fillna(0)
            
            st.session_state["dados_cache"] = {
                "func": df_func, "oco": df_oco, 
                "sup": mapa_sup, "tel": mapa_tel,
                "periodo": int(per_id)
            }
            status.update(label="Dados carregados!", state="complete", expanded=False)

    # 2. RECUPERA DO CACHE
    df_func = st.session_state["dados_cache"]["func"].copy()
    df_oco = st.session_state["dados_cache"]["oco"].copy()
    mapa_sup = st.session_state["dados_cache"]["sup"]
    periodo_atual = st.session_state["dados_cache"]["periodo"]

    # 3. BUSCA VALIDAÇÕES DO BANCO (SEMPRE FRESCO)
    conn = st.connection("postgres", type="sql")
    df_db = buscar_do_banco(conn, periodo_atual)

    # 4. CRIA TABELA MESTRA
    # Base: Funcionários
    df_mestra = df_func[['NRVINCULOM', 'NMVINCULOM']].copy()
    df_mestra.columns = ['NRVINCULOM', 'Funcionario']
    df_mestra['Supervisor'] = df_mestra['NRVINCULOM'].map(mapa_sup).fillna("NAO IDENTIFICADO")

    # Junta Ocorrências
    if not df_oco.empty:
        # Filtra hoje
        hoje = datetime.now().strftime('%Y-%m-%d')
        df_oco = df_oco[df_oco['DATA_INICIO_FILTER'] != hoje]
        
        # Agrega Faltas e Atrasos
        resumo_oco = df_oco.groupby('NRVINCULOM').agg(
            Qtd_Faltas=('TIPO_OCORRENCIA', lambda x: (x.str.upper().str.strip() == 'FALTA').sum()),
            Total_Horas_Atraso=('DIFF_HOURS', lambda x: x[df_oco['TIPO_OCORRENCIA'].str.upper().str.strip() == 'ATRASO'].sum()),
            Datas=('DATA_INICIO', lambda x: ", ".join(sorted(set(x))))
        ).reset_index()
        
        df_mestra = pd.merge(df_mestra, resumo_oco, on='NRVINCULOM', how='left').fillna(0)
        df_mestra['Datas'] = df_mestra['Datas'].replace(0, "")
    else:
        df_mestra['Qtd_Faltas'] = 0
        df_mestra['Total_Horas_Atraso'] = 0.0
        df_mestra['Datas'] = ""

    # 5. O GRANDE MERGE (API + BANCO)
    # Aqui a mágica acontece. Cruzamos ID (int) com ID (int)
    if not df_db.empty:
        # Garante nome da coluna para o merge
        df_db = df_db.rename(columns={'ColaboradorID': 'NRVINCULOM'})
        df_final = pd.merge(df_mestra, df_db[['NRVINCULOM', 'Procedente', 'UsuarioResponsavel', 'QtdFaltasSnapshot', 'HorasAtrasoSnapshot']], on='NRVINCULOM', how='left')
    else:
        df_final = df_mestra.copy()
        df_final['Procedente'] = False
        df_final['UsuarioResponsavel'] = "-"
        df_final['QtdFaltasSnapshot'] = 0
        df_final['HorasAtrasoSnapshot'] = 0

    # Limpeza final
    df_final['Procedente'] = df_final['Procedente'].fillna(False)
    df_final['UsuarioResponsavel'] = df_final['UsuarioResponsavel'].fillna("-")

    # Score
    df_final['Score'] = (df_final['Qtd_Faltas'] * 10) + (df_final['Total_Horas_Atraso'] / 8.0 * 5)
    df_final['Score'] = df_final['Score'].apply(lambda x: 10 if x > 10 else x)
    
    # 6. EXIBIÇÃO
    c1, c2, c3 = st.columns(3)
    c1.metric("Total", len(df_final))
    pendentes = len(df_final[(df_final['Score'] > 0) & (df_final['Procedente'] == False)])
    c2.metric("Pendentes", pendentes)
    c3.metric("Validados", len(df_final[df_final['Procedente'] == True]))

    # EDITOR
    st.subheader("Validação de Ponto")
    
    # Ordena: Pendentes com maior score primeiro
    df_show = df_final.sort_values(by=['Procedente', 'Score'], ascending=[True, False])

    with st.form("form_val"):
        edited = st.data_editor(
            df_show[[
                'Procedente', 'Funcionario', 'Supervisor', 'Qtd_Faltas', 'Total_Horas_Atraso', 
                'Score', 'UsuarioResponsavel', 'NRVINCULOM'
            ]],
            column_config={
                "Procedente": st.column_config.CheckboxColumn("Validar?", default=False),
                "NRVINCULOM": st.column_config.TextColumn("Matrícula", disabled=True),
                "Score": st.column_config.ProgressColumn("Criticidade", min_value=0, max_value=10, format="%.1f"),
                "UsuarioResponsavel": st.column_config.TextColumn("Quem Validou", disabled=True),
            },
            use_container_width=True,
            hide_index=True,
            key="editor_principal"
        )

        if st.form_submit_button("💾 Salvar Alterações"):
            # Pega as alterações do estado do editor
            changes = st.session_state["editor_principal"]["edited_rows"]
            
            if changes:
                # Reconstrói o DF apenas com as linhas alteradas
                indices = list(changes.keys())
                df_to_save = edited.iloc[indices].copy()
                
                # Nome do usuario logado
                user_now = st.session_state.get("name", "Usuario Streamlit")
                
                salvar_no_banco(conn, df_to_save, periodo_atual, user_now)
                
                # Rerun para atualizar a tabela visualmente (fazendo o fetch novamente)
                st.rerun()
            else:
                st.info("Nenhuma alteração detectada.")