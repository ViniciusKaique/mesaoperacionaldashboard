import streamlit as st
import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==============================================================================
# 1. CONFIGURAÇÃO DA PÁGINA
# ==============================================================================
st.set_page_config(page_title="HCM - Apurador Turbo", layout="wide", page_icon="🚀")

st.markdown("""
    <style>
    div[data-testid="stMetricValue"] { font-size: 1.4rem; }
    .stCodeBlock { max-height: 300px; overflow-y: auto; }
    </style>
""", unsafe_allow_html=True)

# ==============================================================================
# 2. SEGURANÇA E CREDENCIAIS
# ==============================================================================
if not st.session_state.get("authentication_status"):
    st.warning("🔒 Acesso restrito. Faça login na página inicial.")
    st.stop()

# Carrega secrets
try:
    SECRETS_PG = st.secrets["api_portal_gestor"]
    PG_TOKEN = SECRETS_PG["token_fixo"]
    PG_CD_OPERADOR = SECRETS_PG["cd_operador"]
    PG_NR_ORG = SECRETS_PG["nr_org"]
except Exception as e:
    st.error(f"⚠️ Erro ao carregar secrets.toml: {e}")
    st.stop()

# ==============================================================================
# 3. FUNÇÕES DE API (MODO HAR/BROWSER)
# ==============================================================================

def get_headers_har():
    """ 
    Headers copiados exatamente do fetch do navegador (HAR).
    """
    return {
        "accept": "application/json, text/plain, */*",
        "oauth-cdoperador": str(PG_CD_OPERADOR),
        "oauth-nrorg": str(PG_NR_ORG),
        "oauth-token": str(PG_TOKEN),
        "referrer": "https://portalgestor.teknisa.com/",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

@st.cache_data(ttl=3600) 
def fetch_periodos_apuracao():
    url = "https://portalgestor.teknisa.com/backend/index.php/getPeriodosDemonstrativo"
    params = { "requestType": "FilterData", "NRORG": PG_NR_ORG, "CDOPERADOR": PG_CD_OPERADOR }
    try:
        r = requests.get(url, params=params, headers=get_headers_har(), timeout=10)
        if r.status_code == 200:
            data = r.json()
            if "dataset" in data and "data" in data["dataset"]:
                return pd.DataFrame(data["dataset"]["data"])
    except: pass
    return pd.DataFrame()

def buscar_vinculos_exatos(nr_periodo, nr_estrut):
    """
    Replica a requisição getVinculosDoGestor do log HAR.
    """
    url = "https://portalgestor.teknisa.com/backend/index.php/getVinculosDoGestor"
    
    # Parâmetros na URL (Query String) igual ao fetch
    params = {
        "requestType": "FilterData",
        "NRPERIODOAPURACAO": nr_periodo,
        "NRESTRUTURAM": nr_estrut,
        "NRORG": PG_NR_ORG,
        "CDOPERADOR": PG_CD_OPERADOR
    }
    
    # Debug: Mostra o que está sendo enviado
    st.session_state["last_request_debug"] = {
        "url": url,
        "params": params,
        "headers": get_headers_har()
    }

    try:
        r = requests.get(url, params=params, headers=get_headers_har(), timeout=30)
        
        # Salva o RAW response para debug se falhar
        st.session_state["last_response_json"] = r.text
        
        if r.status_code == 200:
            data = r.json()
            dataset = data.get("dataset", {})
            
            # --- PARSER ROBUSTO ---
            # 1. Tenta pegar a lista em 'getVinculosDoGestor' (Padrão HAR)
            if isinstance(dataset, dict) and "getVinculosDoGestor" in dataset:
                return dataset["getVinculosDoGestor"]
            
            # 2. Tenta pegar em 'data' (Padrão Diagnostico)
            elif isinstance(dataset, dict) and "data" in dataset:
                return dataset["data"]
            
            # 3. Se o dataset já for a lista
            elif isinstance(dataset, list):
                return dataset
                
            return []
            
        else:
            st.error(f"Erro HTTP {r.status_code}")
            
    except Exception as e:
        st.error(f"Erro técnico: {e}")
    return []

def executar_apuracao_individual(session, url_base, headers, vinculo, nr_periodo):
    endpoint = f"{url_base}/apurarPeriodo"
    payload = {
        "requestType": "Row",
        "row": {
            "NRORG": str(PG_NR_ORG),
            "NRVINCULOM": int(vinculo),
            "NRPERIODOAPURACAO": int(nr_periodo),
            "CDOPERADOR": str(PG_CD_OPERADOR)
        }
    }
    
    try:
        r = session.post(endpoint, headers=headers, json=payload, timeout=25)
        
        if r.status_code == 200:
            resp = r.json()
            dados = resp.get("dataset", {}).get("data", {}).get("apurarPeriodo", {})
            if dados.get("apurado") is True:
                return "SUCESSO", "Apuração Realizada", ""
            else:
                infos = resp.get("dataset", {}).get("data", {}).get("info", [])
                return "FALHA_LOGICA", "Não apurado", str(infos)

        elif r.status_code == 500:
            try:
                err_json = r.json()
                if "error" in err_json:
                    msg = err_json["error"].replace("<br>", " ").replace("(HCMSERVICES)", "").strip()
                    return "BLOQUEADO", msg, ""
            except: pass
            return "ERRO_SERVIDOR", f"HTTP {r.status_code}", r.text[:100]
        else:
            return "ERRO_REQ", f"Status {r.status_code}", ""

    except Exception as e:
        return "CRITICO", "Erro Python", str(e)

# ==============================================================================
# 4. INTERFACE E CONTROLES
# ==============================================================================

st.title("🚀 Apurador Turbo (Modo HAR)")

if "lista_funcionarios" not in st.session_state:
    st.session_state["lista_funcionarios"] = []
if "resultado_apuracao" not in st.session_state:
    st.session_state["resultado_apuracao"] = []

with st.sidebar:
    st.header("Parâmetros")
    
    # Período
    df_periodos = fetch_periodos_apuracao()
    if not df_periodos.empty:
        periodo_fmt = df_periodos.apply(lambda x: f"{x['DSPERIODOAPURACAO']} (Cód: {x['NRPERIODOAPURACAO']})", axis=1)
        opcao = st.selectbox("Selecione o Período:", periodo_fmt)
        idx = periodo_fmt[periodo_fmt == opcao].index[0]
        nr_periodo = df_periodos.iloc[idx]['NRPERIODOAPURACAO']
    else:
        nr_periodo = st.text_input("Período Apuração (Cód)", value="1904")
    
    st.divider()
    
    # Estrutura
    nr_estrutura = st.text_input("Estrutura (NRESTRUTURAM)", value="101091998")
    threads = st.slider("Velocidade (Threads)", 1, 200, 100)
    
    st.divider()
    
    if st.button("🔄 Carregar Lista (Via Vínculos)", use_container_width=True):
        st.session_state["lista_funcionarios"] = []
        st.session_state["resultado_apuracao"] = []
        st.session_state["last_response_json"] = "" # Limpa debug anterior
        
        with st.spinner(f"Buscando no período {nr_periodo} para estrutura {nr_estrutura}..."):
            res = buscar_vinculos_exatos(nr_periodo, nr_estrutura)
            st.session_state["lista_funcionarios"] = res
            
            if not res:
                st.error("Nenhum registro encontrado.")
                # --- ÁREA DE DEBUG AUTOMÁTICA ---
                st.warning("⚠️ O retorno da API veio vazio ou inválido. Veja abaixo o que o servidor respondeu:")
                with st.expander("🕵️‍♂️ Ver Resposta RAW do Servidor (Debug)", expanded=True):
                    st.json(st.session_state.get("last_request_debug", {}))
                    st.text_area("JSON Retornado:", st.session_state.get("last_response_json", "Sem resposta"), height=300)
            else:
                st.success(f"Encontrados: {len(res)} vínculos.")

# ==============================================================================
# 5. EXECUÇÃO
# ==============================================================================

if st.session_state["lista_funcionarios"]:
    df_lista = pd.DataFrame(st.session_state["lista_funcionarios"])
    
    with st.expander(f"📋 Lista Carregada ({len(df_lista)} vínculos)", expanded=False):
        cols_possiveis = ['NRVINCULOM', 'NMVINCULOM', 'NMSITUFUNCH', 'NMFUNCAO']
        cols_show = [c for c in cols_possiveis if c in df_lista.columns]
        st.dataframe(df_lista[cols_show] if cols_show else df_lista, use_container_width=True, hide_index=True)

    st.markdown("---")
    
    if st.button("🔥 DISPARAR APURAÇÃO EM MASSA", type="primary", use_container_width=True):
        
        session = requests.Session()
        url_base = "https://portalgestor.teknisa.com/backend/index.php"
        headers = get_headers_har()
        
        total_items = len(df_lista)
        results = []
        
        prog_bar = st.progress(0)
        status_text = st.empty()
        suc, blk, err = 0, 0, 0
        
        with ThreadPoolExecutor(max_workers=threads) as executor:
            futures = {
                executor.submit(
                    executar_apuracao_individual, 
                    session, url_base, headers, 
                    row.get('NRVINCULOM'), nr_periodo
                ): row 
                for row in st.session_state["lista_funcionarios"]
            }
            
            for i, future in enumerate(as_completed(futures), 1):
                row = futures[future]
                status_cod, msg, det = future.result()
                
                if status_cod == "SUCESSO": suc += 1
                elif status_cod == "BLOQUEADO": blk += 1
                else: err += 1
                
                results.append({
                    "Matrícula": row.get('NRVINCULOM'),
                    "Nome": row.get('NMVINCULOM', 'Desconhecido'),
                    "Status": status_cod,
                    "Mensagem": msg
                })
                
                prog_bar.progress(i / total_items)
                status_text.markdown(f"**Progresso:** ✅ {suc} | ⛔ {blk} | ❌ {err}")
        
        st.session_state["resultado_apuracao"] = results
        st.success("Processamento finalizado!")
        st.rerun()

# ==============================================================================
# 6. RESULTADOS
# ==============================================================================

if st.session_state["resultado_apuracao"]:
    df_res = pd.DataFrame(st.session_state["resultado_apuracao"])
    
    tab1, tab2, tab3 = st.tabs(["📊 Geral", "⛔ Bloqueios", "✅ Sucesso"])
    
    with tab1:
        st.dataframe(df_res, use_container_width=True, hide_index=True, selection_mode="single-row")
        csv = df_res.to_csv(index=False, sep=';', encoding='utf-8-sig')
        st.download_button("📥 Baixar Relatório", csv, "relatorio_apuracao.csv", "text/csv")
        
    with tab2:
        df_err = df_res[df_res['Status'] != 'SUCESSO']
        st.dataframe(df_err, use_container_width=True, hide_index=True)
            
    with tab3:
        df_suc = df_res[df_res['Status'] == 'SUCESSO']
        st.dataframe(df_suc, use_container_width=True, hide_index=True)