import streamlit as st
import requests
import pandas as pd
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==============================================================================
# 1. CONFIGURAÇÃO DA PÁGINA
# ==============================================================================
st.set_page_config(page_title="HCM - Apurador Turbo", layout="wide", page_icon="🚀")

# CSS para ajustar altura de logs e métricas (Estilo padrão)
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

# --- CARREGAR CREDENCIAIS (Padrão do arquivo DIAGNOSTICO_PONTO.py) ---
try:
    # Carrega secrets do Portal Gestor (usado para Apuração) 
    SECRETS_PG = st.secrets["api_portal_gestor"]
    PG_TOKEN_FIXO = SECRETS_PG["token_fixo"]
    PG_CD_OPERADOR_FIXO = SECRETS_PG["cd_operador"]
    PG_NR_ORG_FIXO = SECRETS_PG["nr_org"]
except Exception as e:
    st.error(f"⚠️ Erro ao carregar secrets.toml: {e}")
    st.stop()

# ==============================================================================
# 3. FUNÇÕES DE API (PORTAL GESTOR)
# ==============================================================================

def get_headers_portal(token, cd_operador, nr_org):
    """ Gera headers padronizados para o Portal Gestor [cite: 12] """
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "OAuth-Token": token,
        "OAuth-Cdoperador": cd_operador,
        "OAuth-Nrorg": nr_org
    }

def buscar_vinculos_para_apuracao(nr_periodo, nr_estrut, token, cd_op, nr_org):
    """ Busca todos os vínculos do gestor (Baseado em fetch_ids_portal_gestor [cite: 12]) """
    url = "https://portalgestor.teknisa.com/backend/index.php/getVinculosDoGestor"
    params = {
        "requestType": "FilterData",
        "NRPERIODOAPURACAO": nr_periodo,
        "NRESTRUTURAM": nr_estrut,
        "NRORG": nr_org,
        "CDOPERADOR": cd_op
    }
    headers = get_headers_portal(token, cd_op, nr_org)
    
    try:
        r = requests.get(url, params=params, headers=headers, timeout=30)
        if r.status_code == 200:
            data = r.json()
            # Tratamento robusto do retorno (Dictionary ou List) [cite: 13]
            dataset = data.get("dataset", {})
            if isinstance(dataset, dict):
                return dataset.get("getVinculosDoGestor", []) or dataset.get("data", [])
            elif isinstance(dataset, list):
                return dataset
    except Exception as e:
        st.error(f"Erro na busca: {e}")
    return []

def executar_apuracao_individual(session, url_base, headers, vinculo, nr_periodo, nr_org, cd_op):
    """ 
    Executa a apuração e trata erros lógicos/bloqueios (Lógica Turbo) 
    """
    endpoint = f"{url_base}/apurarPeriodo"
    payload = {
        "requestType": "Row",
        "row": {
            "NRORG": str(nr_org),
            "NRVINCULOM": int(vinculo),
            "NRPERIODOAPURACAO": int(nr_periodo),
            "CDOPERADOR": str(cd_op)
        }
    }
    
    try:
        # Timeout curto para garantir velocidade
        r = session.post(endpoint, headers=headers, json=payload, timeout=25)
        
        # CASO 1: SUCESSO (Verifica flag 'apurado')
        if r.status_code == 200:
            resp = r.json()
            dados = resp.get("dataset", {}).get("data", {}).get("apurarPeriodo", {})
            if dados.get("apurado") is True:
                return "SUCESSO", "Apuração Realizada", ""
            else:
                infos = resp.get("dataset", {}).get("data", {}).get("info", [])
                return "FALHA_LOGICA", "Não apurado (Flag False)", str(infos)

        # CASO 2: ERRO 500 (Bloqueio de Regra - Extração JSON)
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

# --- ESTADO PERSISTENTE ---
if "lista_funcionarios" not in st.session_state:
    st.session_state["lista_funcionarios"] = []
if "resultado_apuracao" not in st.session_state:
    st.session_state["resultado_apuracao"] = []

# --- SIDEBAR (Parâmetros) ---
with st.sidebar:
    st.header("Parâmetros")
    
    # Credenciais carregadas dos Secrets (Padrão do arquivo fonte )
    pg_nr_org = st.text_input("NRORG", value=PG_NR_ORG_FIXO)
    pg_cd_operador = st.text_input("CDOPERADOR", value=PG_CD_OPERADOR_FIXO)
    pg_token = st.text_input("Token (OAuth)", value=PG_TOKEN_FIXO, type="password")
    
    st.divider()
    
    # Inputs de Filtro
    nr_estrutura = st.text_input("Estrutura (NRESTRUTURAM)", value="101091998")
    nr_periodo = st.text_input("Período Apuração", value="1904")
    
    st.divider()
    
    # Controle de Velocidade
    threads = st.slider("Velocidade (Threads)", 1, 10, 5, help="Cuidado: >5 pode bloquear a sessão.")
    
    if st.button("🔄 Carregar Lista", use_container_width=True):
        with st.spinner("Buscando lista de vínculos..."):
            res = buscar_vinculos_para_apuracao(nr_periodo, nr_estrutura, pg_token, pg_cd_operador, pg_nr_org)
            st.session_state["lista_funcionarios"] = res
            st.session_state["resultado_apuracao"] = [] # Limpa resultado anterior
            
            if not res:
                st.error("Nenhum registro encontrado.")
            else:
                st.success(f"Encontrados: {len(res)}")

# ==============================================================================
# 5. LÓGICA PRINCIPAL DA PÁGINA
# ==============================================================================

# Se houver lista carregada, mostra opções de execução
if st.session_state["lista_funcionarios"]:
    df_lista = pd.DataFrame(st.session_state["lista_funcionarios"])
    
    # Exibe resumo da lista carregada
    with st.expander(f"📋 Lista Carregada ({len(df_lista)} vínculos)", expanded=False):
        cols_show = [c for c in ['NRVINCULOM', 'NMVINCULOM', 'NMSITUFUNCH'] if c in df_lista.columns]
        st.dataframe(df_lista[cols_show], use_container_width=True, hide_index=True)

    st.markdown("---")
    
    col_act, col_info = st.columns([1, 2])
    with col_act:
        if st.button("🔥 DISPARAR APURAÇÃO", type="primary", use_container_width=True):
            
            # Preparação para execução em Threads
            session = requests.Session()
            url_base = "https://portalgestor.teknisa.com/backend/index.php"
            headers = get_headers_portal(pg_token, pg_cd_operador, pg_nr_org)
            
            total_items = len(df_lista)
            results = []
            
            # Elementos de UI para progresso
            prog_bar = st.progress(0)
            status_text = st.empty()
            
            suc, blk, err = 0, 0, 0
            
            with ThreadPoolExecutor(max_workers=threads) as executor:
                # Submete tarefas
                futures = {
                    executor.submit(
                        executar_apuracao_individual, 
                        session, url_base, headers, 
                        row['NRVINCULOM'], nr_periodo, pg_nr_org, pg_cd_operador
                    ): row 
                    for row in st.session_state["lista_funcionarios"]
                }
                
                # Processa conforme completa
                for i, future in enumerate(as_completed(futures), 1):
                    row = futures[future]
                    status_cod, msg, det = future.result()
                    
                    if status_cod == "SUCESSO": suc += 1
                    elif status_cod == "BLOQUEADO": blk += 1
                    else: err += 1
                    
                    results.append({
                        "Matrícula": row.get('NRVINCULOM'),
                        "Nome": row.get('NMVINCULOM'),
                        "Status": status_cod,
                        "Mensagem": msg,
                        "Detalhes": det
                    })
                    
                    # Atualiza UI
                    prog_bar.progress(i / total_items)
                    status_text.markdown(f"**Progresso:** ✅ {suc} | ⛔ {blk} | ❌ {err}")
            
            st.session_state["resultado_apuracao"] = results
            st.success("Processamento finalizado!")
            st.rerun() # Recarrega para exibir resultados nas abas

# ==============================================================================
# 6. EXIBIÇÃO DE RESULTADOS (Abas e Dataframes)
# ==============================================================================

if st.session_state["resultado_apuracao"]:
    df_res = pd.DataFrame(st.session_state["resultado_apuracao"])
    
    # Layout de abas igual ao arquivo DIAGNOSTICO_PONTO [cite: 39]
    tab1, tab2, tab3 = st.tabs(["📊 Geral", "⛔ Bloqueios/Erros", "✅ Sucesso"])
    
    with tab1:
        st.dataframe(
            df_res, 
            use_container_width=True, 
            hide_index=True,
            selection_mode="single-row", # Padrão do molde [cite: 40, 47]
            key="grid_geral_apur"
        )
        csv = df_res.to_csv(index=False, sep=';', encoding='utf-8-sig')
        st.download_button("📥 Baixar Relatório", csv, "relatorio_apuracao.csv", "text/csv")
        
    with tab2:
        df_err = df_res[df_res['Status'] != 'SUCESSO']
        if not df_err.empty:
            st.warning("Estes registros retornaram erro ou bloqueio de regra de negócio.")
            st.dataframe(df_err, use_container_width=True, hide_index=True)
        else:
            st.info("Nenhum erro encontrado.")
            
    with tab3:
        df_suc = df_res[df_res['Status'] == 'SUCESSO']
        st.dataframe(df_suc, use_container_width=True, hide_index=True)