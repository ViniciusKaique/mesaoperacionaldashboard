import streamlit as st
import requests
import json
import pandas as pd
from datetime import datetime, date
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image
from dateutil import tz

# ==============================================================================
# 1. CONFIGURAÇÃO DA PÁGINA
# ==============================================================================
st.set_page_config(page_title="Aprovação Turbo", layout="wide", page_icon="🚀")

# ==============================================================================
# 2. SEGURANÇA E AUTENTICAÇÃO
# ==============================================================================
if not st.session_state.get("authentication_status"):
    st.warning("🔒 Acesso restrito. Faça login na página inicial.")
    st.stop()

# Recupera Credenciais do Secrets
try:
    SECRETS_API = st.secrets["api_portal_gestor"]
    TOKEN = SECRETS_API["token_fixo"]
    CD_OPERADOR = SECRETS_API["cd_operador"] 
    NR_ORG = SECRETS_API["nr_org"]           
except Exception as e:
    st.error(f"⚠️ Erro de configuração: {e}. Verifique o arquivo .streamlit/secrets.toml")
    st.stop()

# ==============================================================================
# 3. FUNÇÕES DE SUPORTE (API & LÓGICA)
# ==============================================================================
BASE_URL = "https://portalgestor.teknisa.com/backend/index.php"

def get_headers():
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "OAuth-Cdoperador": CD_OPERADOR,
        "OAuth-Nrorg": NR_ORG,
        "OAuth-Token": TOKEN
    }

def carregar_logo():
    try: return Image.open("logo.png")
    except: return None

# --- CARREGAMENTO DE LISTAS (Dropdowns) ---
@st.cache_data(ttl=3600)
def fetch_estruturas():
    url = f"{BASE_URL}/getEstruturasGerenciais"
    params = {
        "requestType": "FilterData",
        "NRORG": NR_ORG,
        "CDOPERADOR": CD_OPERADOR
    }
    try:
        r = requests.get(url, params=params, headers=get_headers(), timeout=15)
        if r.status_code == 200:
            data = r.json()
            items = (data.get("dataset", {}) or {}).get("data", [])
            # Retorna lista de tuplas (Nome Amigável, ID)
            return [(i.get("NMESTRUTURA", "Sem Nome"), i.get("NRESTRUTURAM")) for i in items]
    except Exception as e:
        st.error(f"Erro ao buscar estruturas: {e}")
    return []

@st.cache_data(ttl=3600)
def fetch_periodos():
    url = f"{BASE_URL}/getPeriodosDemonstrativo"
    params = {
        "requestType": "FilterData",
        "NRORG": NR_ORG,
        "CDOPERADOR": CD_OPERADOR
    }
    try:
        r = requests.get(url, params=params, headers=get_headers(), timeout=15)
        if r.status_code == 200:
            data = r.json()
            items = (data.get("dataset", {}) or {}).get("data", [])
            return [(i.get("DSPERIODOAPURACAO", "Periodo"), i.get("NRPERIODOAPURACAO")) for i in items]
    except Exception as e:
        st.error(f"Erro ao buscar períodos: {e}")
    return []

# --- BUSCA DE OCORRÊNCIAS ---
def fetch_ocorrencias(session, nrestrut, nrperiodo):
    url = f"{BASE_URL}/getOcorrenciasPendentesPeriodoVinculosGestor"
    params = {
        "requestType": "FilterData",
        "NRORG": NR_ORG,
        "NRESTRUTURAM": nrestrut,
        "NRPERIODOAPURACAO": nrperiodo,
        "CDOPERADOR": CD_OPERADOR,
    }
    r = session.get(url, params=params, headers=get_headers())
    r.raise_for_status()
    data = r.json()
    arr = (data.get("dataset", {}) or {}).get("getOcorrenciasPendentesPeriodoVinculosGestor", []) or []
    return arr

# --- APROVAÇÃO ---
def aprovar_single_ocorrencia(session, oc):
    url = f"{BASE_URL}/aprovarOcorrencia"
    nr_prog = oc.get("NRPROGOCORRENCIA")
    
    nome = (oc.get("NMVINCULOM") or oc.get("NMOPERINCLUSAO") or oc.get("NMFUNCIONARIO") or "Desconhecido")
    
    if not nr_prog:
        return False, f"⚠️ {nome}: Sem ID (NRPROGOCORRENCIA)", oc

    body = {
        "requestType": "Row",
        "row": {
            "NRPROGOCORRENCIA": str(nr_prog),
            "NRORG": str(NR_ORG),
            "CDOPERADOR": str(CD_OPERADOR)
        },
    }
    
    headers_post = get_headers().copy()
    headers_post["Content-Type"] = "application/json"
    
    try:
        r = session.post(url, headers=headers_post, data=json.dumps(body), timeout=15)
        if not r.ok:
            return False, f"❌ {nome}: Erro API {r.status_code}", oc
        return True, f"✅ {nome}: Aprovado", oc
    except Exception as e:
        return False, f"❌ {nome}: Erro de Conexão - {str(e)}", oc

# --- HELPERS DATA ---
def parse_br_date(s: str):
    if not s: return None
    try:
        dd, mm, yyyy = s[:10].split("/")
        return date(int(yyyy), int(mm), int(dd))
    except: return None

def eh_ate_hoje(oc) -> bool:
    dt_str = oc.get("DTINICIOPROGOCOR") or oc.get("DTFREQ") or oc.get("DTINI")
    d = parse_br_date(dt_str)
    if not d: return False
    hoje = datetime.now(tz=tz.gettz("America/Sao_Paulo")).date()
    return d <= hoje

# ==============================================================================
# 4. SIDEBAR (Apenas Logo e Usuário)
# ==============================================================================
with st.sidebar:
    if logo := carregar_logo(): 
        st.image(logo, use_container_width=True)
    st.divider()
    
    if "name" in st.session_state: 
        st.write(f"👤 **{st.session_state['name']}**")
        st.divider()
        
    if st.button("🧹 Limpar Lista", use_container_width=True):
        st.session_state.pop("ocorrencias_raw", None)
        st.session_state.pop("ocorrencias_filtradas", None)
        st.rerun()

# ==============================================================================
# 5. CORPO PRINCIPAL
# ==============================================================================
st.title("🚀 Aprova Turbo")
st.markdown("Busque ocorrências pendentes e aprove em lote com alta velocidade.")

# Estado da Sessão Requests
if "session_api" not in st.session_state:
    st.session_state["session_api"] = requests.Session()

# --- ÁREA DE FILTROS (MOVIDA PARA CÁ) ---
with st.container(border=True):
    st.subheader("⚙️ Filtros de Busca e Aprovação")
    
    c1, c2 = st.columns(2)
    
    # Selectbox de Estruturas
    estruturas_opcoes = fetch_estruturas()
    with c1:
        estrutura_selecionada = st.selectbox(
            "🏢 Selecione a Estrutura:",
            options=estruturas_opcoes,
            format_func=lambda x: x[0],
            index=0 if estruturas_opcoes else None
        )
        nrestrut_val = estrutura_selecionada[1] if estrutura_selecionada else ""

    # Selectbox de Períodos
    periodos_opcoes = fetch_periodos()
    with c2:
        periodo_selecionado = st.selectbox(
            "📅 Selecione o Período:",
            options=periodos_opcoes,
            format_func=lambda x: x[0],
            index=0 if periodos_opcoes else None
        )
        nrperiodo_val = periodo_selecionado[1] if periodo_selecionado else ""

    st.divider()
    
    c3, c4, c5 = st.columns([2, 1, 1])
    with c3:
        motivo_alvo = st.text_input("📝 Motivo (Palavra-chave):", value="ausência de marcação / entrada e saída")
    with c4:
        st.write("") # Espaçamento
        st.write("") 
        somente_ate_hoje = st.checkbox("Apenas até Hoje?", value=True)
    with c5:
        max_workers = st.slider("Threads (Velocidade)", 1, 50, 10)

    # --- BOTÃO DE BUSCA (Neutro) ---
    if st.button("🔎 Buscar Ocorrências", use_container_width=True):
        if not nrestrut_val or not nrperiodo_val:
            st.warning("Selecione Estrutura e Período acima.")
        else:
            with st.spinner("Consultando Teknisa..."):
                try:
                    lista = fetch_ocorrencias(st.session_state["session_api"], nrestrut_val, nrperiodo_val)
                    st.session_state["ocorrencias_raw"] = lista
                    
                    if not lista:
                        st.warning("Nenhuma ocorrência encontrada neste período/estrutura.")
                    else:
                        st.success(f"{len(lista)} registros baixados.")
                except Exception as e:
                    st.error(f"Erro na busca: {e}")

# ==============================================================================
# 6. EXIBIÇÃO DE RESULTADOS
# ==============================================================================
st.divider()

raw_data = st.session_state.get("ocorrencias_raw", [])

if raw_data:
    # --- APLICAÇÃO DOS FILTROS ---
    motivo_norm = motivo_alvo.strip().lower()
    
    def filtro_custom(oc):
        # 1. Filtro de Motivo
        txt_motivo = (oc.get("DSMOTIVOOCORFREQ") or "").lower()
        txt_tipo = (oc.get("NMTIPOPROGOCORRENCIA") or "").lower()
        txt_obs = (oc.get("DSOBSERVACAO") or "").lower()
        
        match_motivo = (motivo_norm in txt_motivo) or (motivo_norm in txt_tipo) or (motivo_norm in txt_obs)
        
        # 2. Filtro de Data
        match_data = eh_ate_hoje(oc) if somente_ate_hoje else True
        
        return match_motivo and match_data

    filtradas = [x for x in raw_data if filtro_custom(x)]
    st.session_state["ocorrencias_filtradas"] = filtradas

    # --- TABELA E AÇÃO ---
    if filtradas:
        st.markdown(f"### 📋 Registros Prontos para Aprovação: **{len(filtradas)}**")
        
        df_view = pd.DataFrame(filtradas)
        cols_show = ["NMVINCULOM", "DTINICIOPROGOCOR", "DSMOTIVOOCORFREQ", "DSOBSERVACAO"]
        cols_exist = [c for c in cols_show if c in df_view.columns]
        
        st.dataframe(
            df_view[cols_exist],
            use_container_width=True,
            hide_index=True
        )
        
        st.warning("⚠️ Atenção: Ao clicar abaixo, o sistema iniciará a aprovação em massa.")
        
        # --- BOTÃO TURBO (NEUTRO) ---
        if st.button(f"🚀 APROVAR {len(filtradas)} OCORRÊNCIAS AGORA", use_container_width=True):
            logs_container = st.container(height=300)
            progress_bar = st.progress(0)
            
            total = len(filtradas)
            concluidos = 0
            sucessos = 0
            
            with requests.Session() as s:
                # Configura Retry
                adapter = requests.adapters.HTTPAdapter(max_retries=2)
                s.mount('https://', adapter)
                
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = {
                        executor.submit(aprovar_single_ocorrencia, s, item): item 
                        for item in filtradas
                    }
                    
                    for future in as_completed(futures):
                        concluidos += 1
                        is_ok, msg, _ = future.result()
                        
                        if is_ok:
                            sucessos += 1
                            logs_container.success(msg)
                        else:
                            logs_container.error(msg)
                        
                        progress_bar.progress(concluidos / total)
            
            st.success(f"Processo finalizado! {sucessos}/{total} aprovados.")
            st.balloons()
    else:
        st.info("Nenhuma ocorrência da lista corresponde aos filtros de Motivo/Data informados.")

elif st.session_state.get("ocorrencias_raw") is not None:
    # Lista vazia retornada da API
    pass
else:
    st.info("👈 Configure os filtros acima e clique em 'Buscar Ocorrências' para começar.")