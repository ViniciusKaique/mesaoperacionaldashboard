import streamlit as st
import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==============================================================================
# 1. CONFIGURAÇÃO DA PÁGINA
# ==============================================================================
st.set_page_config(page_title="HCM - Apurador Turbo", layout="wide", page_icon="🚀")

# CSS para ajustar visualização
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

# Carrega secrets (Oculto do usuário) 
try:
    SECRETS_PG = st.secrets["api_portal_gestor"]
    PG_TOKEN = SECRETS_PG["token_fixo"]
    PG_CD_OPERADOR = SECRETS_PG["cd_operador"]
    PG_NR_ORG = SECRETS_PG["nr_org"]
except Exception as e:
    st.error(f"⚠️ Erro ao carregar secrets.toml: {e}")
    st.stop()

# ==============================================================================
# 3. FUNÇÕES DE API
# ==============================================================================

def get_headers():
    """ Headers padronizados conforme DIAGNOSTICO_PONTO [cite: 12] """
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "OAuth-Token": PG_TOKEN,
        "OAuth-Cdoperador": PG_CD_OPERADOR,
        "OAuth-Nrorg": PG_NR_ORG
    }

@st.cache_data(ttl=3600) 
def fetch_periodos_apuracao():
    """ Busca períodos disponíveis (Igual ao Diagnóstico)  """
    url = "https://portalgestor.teknisa.com/backend/index.php/getPeriodosDemonstrativo"
    params = { 
        "requestType": "FilterData", 
        "NRORG": PG_NR_ORG, 
        "CDOPERADOR": PG_CD_OPERADOR 
    }
    try:
        r = requests.get(url, params=params, headers=get_headers(), timeout=10)
        if r.status_code == 200:
            data = r.json()
            # Padrão de retorno Teknisa [cite: 15]
            if "dataset" in data and "data" in data["dataset"]:
                return pd.DataFrame(data["dataset"]["data"])
    except: pass
    return pd.DataFrame()

def buscar_vinculos_para_apuracao(nr_periodo, nr_estrut):
    """ 
    Busca vínculos. Usa getVinculosDoGestor para garantir o período todo,
    mas aplica o parser genérico do Diagnóstico ('dataset' -> 'data') para corrigir o erro.
    """
    url = "https://portalgestor.teknisa.com/backend/index.php/getVinculosDoGestor"
    params = {
        "requestType": "FilterData",
        "NRPERIODOAPURACAO": nr_periodo,
        "NRESTRUTURAM": nr_estrut,
        "NRORG": PG_NR_ORG,
        "CDOPERADOR": PG_CD_OPERADOR
    }
    
    try:
        r = requests.get(url, params=params, headers=get_headers(), timeout=30)
        if r.status_code == 200:
            data = r.json()
            
            # Tenta extrair lista de várias formas comuns da API Teknisa
            dataset = data.get("dataset", {})
            
            # 1. Tentativa padrão 'getVinculosDoGestor'
            if isinstance(dataset, dict) and "getVinculosDoGestor" in dataset:
                 lista = dataset["getVinculosDoGestor"]
            # 2. Tentativa padrão Diagnóstico 'data' [cite: 13]
            elif isinstance(dataset, dict) and "data" in dataset:
                 lista = dataset["data"]
            # 3. Se o dataset já for a lista
            elif isinstance(dataset, list):
                 lista = dataset
            else:
                 lista = []

            # Retorna sem filtro de atividade normal (conforme solicitado)
            return lista
            
    except Exception as e:
        st.error(f"Erro na busca: {e}")
    return []

def executar_apuracao_individual(session, url_base, headers, vinculo, nr_periodo):
    """ Executa a apuração e trata o erro 500 JSON """
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
                return "FALHA_LOGICA", "Não apurado (Flag False)", str(infos)

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

st.title("🚀 Apurador Turbo (Massa)")

if "lista_funcionarios" not in st.session_state:
    st.session_state["lista_funcionarios"] = []
if "resultado_apuracao" not in st.session_state:
    st.session_state["resultado_apuracao"] = []

# --- SIDEBAR LIMPA ---
with st.sidebar:
    st.header("Parâmetros")
    
    # Seleção de Período (Igual Diagnóstico) 
    df_periodos = fetch_periodos_apuracao()
    if not df_periodos.empty:
        # Cria label amigável
        periodo_fmt = df_periodos.apply(lambda x: f"{x['DSPERIODOAPURACAO']} (Cód: {x['NRPERIODOAPURACAO']})", axis=1)
        opcao = st.selectbox("Selecione o Período:", periodo_fmt)
        
        # Extrai o código do período da seleção
        idx = periodo_fmt[periodo_fmt == opcao].index[0]
        nr_periodo = df_periodos.iloc[idx]['NRPERIODOAPURACAO']
    else:
        nr_periodo = st.text_input("Período Apuração (Cód)", value="1904")
    
    st.divider()
    
    nr_estrutura = st.text_input("Estrutura (NRESTRUTURAM)", value="101091998")
    threads = st.slider("Velocidade (Threads)", 1, 200, 5)
    
    st.divider()
    
    if st.button("🔄 Carregar Lista", use_container_width=True):
        st.session_state["lista_funcionarios"] = []
        st.session_state["resultado_apuracao"] = []
        
        with st.spinner(f"Buscando vínculos no período {nr_periodo}..."):
            res = buscar_vinculos_para_apuracao(nr_periodo, nr_estrutura)
            st.session_state["lista_funcionarios"] = res
            
            if not res:
                st.error("Nenhum registro encontrado.")
                st.info("Dica: Verifique se o código da Estrutura (NRESTRUTURAM) está correto para o Gestor configurado.")
            else:
                st.success(f"Encontrados: {len(res)}")

# ==============================================================================
# 5. EXECUÇÃO
# ==============================================================================

if st.session_state["lista_funcionarios"]:
    df_lista = pd.DataFrame(st.session_state["lista_funcionarios"])
    
    with st.expander(f"📋 Lista Carregada ({len(df_lista)} vínculos) - Clique para ver", expanded=False):
        # Tenta exibir colunas amigáveis se existirem
        cols_possiveis = ['NRVINCULOM', 'NMVINCULOM', 'NMSITUFUNCH', 'NMFUNCAO']
        cols_show = [c for c in cols_possiveis if c in df_lista.columns]
        st.dataframe(df_lista[cols_show] if cols_show else df_lista, use_container_width=True, hide_index=True)

    st.markdown("---")
    
    if st.button("🔥 DISPARAR APURAÇÃO", type="primary", use_container_width=True):
        
        session = requests.Session()
        url_base = "https://portalgestor.teknisa.com/backend/index.php"
        headers = get_headers()
        
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
                    "Mensagem": msg,
                    "Detalhes": det
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
    
    tab1, tab2, tab3 = st.tabs(["📊 Geral", "⛔ Bloqueios/Erros", "✅ Sucesso"])
    
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