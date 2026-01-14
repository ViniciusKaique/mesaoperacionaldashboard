import streamlit as st
import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==============================================================================
# 1. CONFIGURAÇÃO DA PÁGINA
# ==============================================================================
st.set_page_config(page_title="HCM - Apurador Turbo", layout="wide", page_icon="🚀")

# CSS Ajustado
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

# --- CARREGAR CREDENCIAIS (IGUAL AO DIAGNOSTICO_PONTO.py) ---
try:
    SECRETS_PG = st.secrets["api_portal_gestor"]
    PG_TOKEN = SECRETS_PG["token_fixo"]
    PG_CD_OPERADOR = SECRETS_PG["cd_operador"]
    PG_NR_ORG = SECRETS_PG["nr_org"]
except Exception as e:
    st.error(f"⚠️ Erro ao carregar secrets.toml: {e}")
    st.stop()

# ==============================================================================
# 3. FUNÇÕES DE API (BASEADAS NO DIAGNOSTICO)
# ==============================================================================

def get_headers():
    return {
        "OAuth-Token": PG_TOKEN, 
        "OAuth-Cdoperador": PG_CD_OPERADOR, 
        "OAuth-Nrorg": PG_NR_ORG, 
        "User-Agent": "Mozilla/5.0",
        "Content-Type": "application/json"
    }

@st.cache_data(ttl=3600) 
def fetch_periodos_apuracao():
    """ 
    Cópia EXATA da função do DIAGNOSTICO_PONTO.py 
    """
    url = "https://portalgestor.teknisa.com/backend/index.php/getPeriodosDemonstrativo"
    params = { 
        "requestType": "FilterData", 
        "NRORG": PG_NR_ORG, 
        "CDOPERADOR": PG_CD_OPERADOR 
    }
    # Headers explícitos igual ao arquivo de referência
    headers = { 
        "OAuth-Token": PG_TOKEN, 
        "OAuth-Cdoperador": PG_CD_OPERADOR, 
        "OAuth-Nrorg": PG_NR_ORG, 
        "User-Agent": "Mozilla/5.0" 
    }
    
    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if "dataset" in data and "data" in data["dataset"]:
                return pd.DataFrame(data["dataset"]["data"])
    except Exception as e:
        print(f"Erro ao buscar períodos: {e}")
        pass
    return pd.DataFrame()

def buscar_vinculos_para_apuracao(nr_periodo, nr_estrut):
    """
    Busca Vínculos. 
    DIFERENÇA: Usa getVinculosDoGestor (necessário p/ apuração) em vez de getMesaOperacoes.
    SEM FILTROS: Traz todo mundo independente da situação.
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
            dataset = data.get("dataset", {})
            
            lista = []
            # Tenta encontrar a lista onde quer que ela esteja no JSON
            if isinstance(dataset, dict):
                if "getVinculosDoGestor" in dataset:
                    lista = dataset["getVinculosDoGestor"]
                elif "data" in dataset:
                    lista = dataset["data"]
            elif isinstance(dataset, list):
                lista = dataset

            # Retorna a lista crua, sem filtrar 'Atividade Normal'
            return lista if lista else []
            
    except Exception as e:
        st.error(f"Erro técnico na busca: {e}")
    return []

def executar_apuracao_individual(session, url_base, headers, vinculo, nr_periodo):
    """ Executa a apuração """
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
            # Caminho seguro para ler o flag de sucesso
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
# 4. INTERFACE E CONTROLES (MOLDE DIAGNOSTICO)
# ==============================================================================

st.title("🚀 Apurador Turbo (Massa)")

if "lista_funcionarios" not in st.session_state:
    st.session_state["lista_funcionarios"] = []
if "resultado_apuracao" not in st.session_state:
    st.session_state["resultado_apuracao"] = []

# --- SIDEBAR IGUAL AO DIAGNOSTICO ---
with st.sidebar:
    st.header("Parâmetros")
    
    # 1. Busca e Lista Períodos
    df_periodos = fetch_periodos_apuracao()
    
    if not df_periodos.empty:
        # Lógica do Diagnóstico: Selectbox com nome e código oculto
        periodos_dict = dict(zip(df_periodos['DSPERIODOAPURACAO'], df_periodos['NRPERIODOAPURACAO']))
        opcao = st.selectbox("Selecione o Período:", list(periodos_dict.keys()))
        nr_periodo = periodos_dict[opcao] # Pega o ID correspondente
    else:
        # Fallback se a API falhar (exibe erro visual para ajudar)
        st.error("⚠️ Não foi possível carregar a lista de períodos.")
        nr_periodo = st.text_input("Período Apuração (Cód. Manual)", value="1904")
    
    st.divider()
    
    # Outros inputs
    nr_estrutura = st.text_input("Estrutura (NRESTRUTURAM)", value="101091998")
    threads = st.slider("Velocidade (Threads)", 1, 10, 5)
    
    st.divider()
    
    if st.button("🔄 Carregar Lista do Quadro", use_container_width=True):
        st.session_state["lista_funcionarios"] = []
        st.session_state["resultado_apuracao"] = []
        
        with st.spinner(f"Buscando lista completa (Período {nr_periodo})..."):
            res = buscar_vinculos_para_apuracao(nr_periodo, nr_estrutura)
            st.session_state["lista_funcionarios"] = res
            
            if not res:
                st.error("Nenhum registro encontrado.")
                st.markdown("""
                **Possíveis causas:**
                1. Token/Operador incorretos no `secrets.toml`.
                2. Código da Estrutura errado.
                3. Período selecionado não tem funcionários vinculados a este gestor.
                """)
            else:
                st.success(f"Encontrados: {len(res)} funcionários (Ativos e Inativos)")

# ==============================================================================
# 5. EXECUÇÃO
# ==============================================================================

if st.session_state["lista_funcionarios"]:
    df_lista = pd.DataFrame(st.session_state["lista_funcionarios"])
    
    # Mostra tabela simples
    with st.expander(f"📋 Visualizar Lista ({len(df_lista)} vínculos)", expanded=False):
        cols_possiveis = ['NRVINCULOM', 'NMVINCULOM', 'NMSITUFUNCH', 'NMFUNCAO']
        cols_show = [c for c in cols_possiveis if c in df_lista.columns]
        st.dataframe(df_lista[cols_show] if cols_show else df_lista, use_container_width=True, hide_index=True)

    st.markdown("---")
    
    if st.button("🔥 DISPARAR APURAÇÃO EM MASSA", type="primary", use_container_width=True):
        
        session = requests.Session()
        url_base = "https://portalgestor.teknisa.com/backend/index.php"
        headers = get_headers() # Usa mesmos headers da busca
        
        total_items = len(df_lista)
        results = []
        
        prog_bar = st.progress(0)
        status_text = st.empty()
        suc, blk, err = 0, 0, 0
        
        # Execução Paralela
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
                    "Situação": row.get('NMSITUFUNCH', '-'),
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
        if df_err.empty:
            st.info("Nenhum erro encontrado.")
        else:
            st.dataframe(df_err, use_container_width=True, hide_index=True)
            
    with tab3:
        df_suc = df_res[df_res['Status'] == 'SUCESSO']
        st.dataframe(df_suc, use_container_width=True, hide_index=True)