import streamlit as st
import requests
import pandas as pd
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==============================================================================
# 1. CONFIGURAÇÃO DA PÁGINA
# ==============================================================================
st.set_page_config(page_title="HCM - Apurador Turbo", layout="wide", page_icon="🚀")

# CSS para melhor visualização
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

# Carrega secrets (Exatamente como no Diagnóstico)
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
    return {
        "User-Agent": "Mozilla/5.0",
        "Content-Type": "application/json",
        "OAuth-Token": PG_TOKEN,
        "OAuth-Cdoperador": PG_CD_OPERADOR,
        "OAuth-Nrorg": PG_NR_ORG
    }

@st.cache_data(ttl=3600) 
def fetch_periodos_apuracao():
    """ Busca lista de períodos igual ao Diagnóstico """
    url = "https://portalgestor.teknisa.com/backend/index.php/getPeriodosDemonstrativo"
    params = { "requestType": "FilterData", "NRORG": PG_NR_ORG, "CDOPERADOR": PG_CD_OPERADOR }
    try:
        r = requests.get(url, params=params, headers=get_headers(), timeout=10)
        if r.status_code == 200:
            data = r.json()
            if "dataset" in data and "data" in data["dataset"]:
                return pd.DataFrame(data["dataset"]["data"])
    except: pass
    return pd.DataFrame()

def buscar_quadro_mesa(data_ref, nr_estrutura):
    """
    Lógica idêntica ao fetch_ids_portal_gestor do Diagnóstico.
    Usa getMesaOperacoes que sabemos que funciona.
    """
    url = "https://portalgestor.teknisa.com/backend/index.php/getMesaOperacoes"
    params = {
        "requestType": "FilterData",
        "DIA": data_ref.strftime("%d/%m/%Y"), # Ex: 14/01/2026
        "NRESTRUTURAM": nr_estrutura,
        "NRORG": PG_NR_ORG, 
        "CDOPERADOR": PG_CD_OPERADOR
    }
    
    try:
        # Timeout um pouco maior pois a Mesa pode ser lenta
        r = requests.get(url, params=params, headers=get_headers(), timeout=30)
        
        if r.status_code == 200:
            data = r.json()
            if "dataset" in data and "data" in data["dataset"]:
                lista = data["dataset"]["data"]
                
                # Retorna a lista crua (sem filtrar Atividade Normal, para pegar todos)
                return lista
            else:
                # Se não tiver 'data', tenta 'dataset' direto caso mude o padrão
                return data.get("dataset", [])
    except Exception as e:
        st.error(f"Erro ao buscar quadro: {e}")
    
    return []

def executar_apuracao_individual(session, url_base, headers, vinculo, nr_periodo):
    """ Executa a apuração e trata o retorno """
    endpoint = f"{url_base}/apurarPeriodo"
    
    # Payload validado por você
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
                return "FALHA_LOGICA", "Flag 'apurado' False", str(infos)

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
# 4. INTERFACE
# ==============================================================================

st.title("🚀 Apurador Turbo (Base: Mesa Operacional)")

if "lista_funcionarios" not in st.session_state:
    st.session_state["lista_funcionarios"] = []
if "resultado_apuracao" not in st.session_state:
    st.session_state["resultado_apuracao"] = []

with st.sidebar:
    st.header("Parâmetros")
    
    # 1. DATA REFERÊNCIA (Necessário para a Mesa Operacional)
    data_ref = st.date_input("Data Referência (Para buscar o quadro)", datetime.now())
    st.caption("A data serve apenas para listar quem pertence à equipe.")
    
    st.divider()

    # 2. PERÍODO APURAÇÃO
    df_periodos = fetch_periodos_apuracao()
    if not df_periodos.empty:
        # Cria label amigável
        periodo_fmt = df_periodos.apply(lambda x: f"{x['DSPERIODOAPURACAO']} (Cód: {x['NRPERIODOAPURACAO']})", axis=1)
        opcao = st.selectbox("Selecione o Período:", periodo_fmt)
        idx = periodo_fmt[periodo_fmt == opcao].index[0]
        nr_periodo = df_periodos.iloc[idx]['NRPERIODOAPURACAO']
    else:
        nr_periodo = st.text_input("Período Apuração (Cód)", value="1904")
    
    st.divider()
    
    # 3. ESTRUTURA E VELOCIDADE
    nr_estrutura = st.text_input("Estrutura (NRESTRUTURAM)", value="101091998")
    threads = st.slider("Velocidade (Threads)", 1, 10, 5)
    
    st.divider()
    
    # 4. BOTÃO CARREGAR
    if st.button("🔄 Carregar Lista (Mesa)", use_container_width=True):
        st.session_state["lista_funcionarios"] = []
        st.session_state["resultado_apuracao"] = []
        
        with st.spinner(f"Buscando quadro de {data_ref.strftime('%d/%m/%Y')}..."):
            res = buscar_quadro_mesa(data_ref, nr_estrutura)
            st.session_state["lista_funcionarios"] = res
            
            if not res:
                st.error("Nenhum registro encontrado na Mesa Operacional.")
                st.info("Verifique se a Data Referência e a Estrutura estão corretas.")
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
                    "Situação": row.get('NMSITUFUNCH', '-'),
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
    
    tab1, tab2, tab3 = st.tabs(["📊 Geral", "⛔ Erros/Bloqueios", "✅ Sucesso"])
    
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