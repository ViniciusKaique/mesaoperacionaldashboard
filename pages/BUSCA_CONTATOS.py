import streamlit as st
import requests
import pandas as pd
import time
import pytz # Biblioteca de fuso horário
from datetime import datetime
from PIL import Image
from sqlalchemy import text

# ==============================================================================
# 1. CONFIGURAÇÃO DA PÁGINA
# ==============================================================================
st.set_page_config(page_title="Busca Contatos HCM", layout="wide", page_icon="📞")

# ==============================================================================
# 2. SEGURANÇA E ESTADO
# ==============================================================================
if not st.session_state.get("authentication_status"):
    st.warning("🔒 Acesso restrito. Faça login na página inicial.")
    st.stop()

# Recupera Credenciais do Secrets
try:
    SECRETS_HCM = st.secrets["hcm_api"]
    HCM_USER = SECRETS_HCM["usuario"]
    HCM_PASS = SECRETS_HCM["senha"]
    HCM_HASH = SECRETS_HCM["hash_sessao"]
    HCM_UID_BROWSER = SECRETS_HCM.get("user_id_browser", "lchp1n8y3ka")
    HCM_PROJECT = SECRETS_HCM.get("project_id", "750")
except Exception as e:
    st.error(f"⚠️ Erro de Configuração: {e}")
    st.stop()

# ==============================================================================
# 3. GERENCIAMENTO DE BANCO DE DADOS (TOKEN CACHE)
# ==============================================================================

def get_data_brasil():
    """Retorna a data e hora atuais no fuso de São Paulo"""
    fuso_br = pytz.timezone('America/Sao_Paulo')
    return datetime.now(fuso_br)

def init_db_token():
    """Cria a tabela HCMTokens se não existir"""
    conn = st.connection("postgres", type="sql")
    try:
        with conn.session as session:
            # Criação da tabela (Aspas duplas no nome para garantir Case Sensitive)
            session.execute(text("""
                CREATE TABLE IF NOT EXISTS public."HCMTokens" (
                    id VARCHAR(50) PRIMARY KEY,
                    access_token TEXT,
                    user_uid TEXT,
                    updated_at TIMESTAMP
                );
            """))
            session.commit()
    except Exception as e:
        st.error(f"Erro ao inicializar tabela de tokens: {e}")
    return conn

def get_token_db(conn):
    """Busca o token salvo no banco"""
    try:
        # Aspas duplas "HCMTokens" são OBRIGATÓRIAS se a tabela foi criada com maiúsculas
        query = 'SELECT access_token, user_uid, updated_at FROM public."HCMTokens" WHERE id = \'bot_hcm_contact\''
        df = conn.query(query, ttl=0)
        
        if not df.empty:
            token = df.iloc[0]['access_token']
            uid = df.iloc[0]['user_uid']
            data_salva = df.iloc[0]['updated_at']
            return token, uid, data_salva
            
    except Exception as e:
        # Mostra o erro para sabermos por que falhou a busca no banco
        st.warning(f"⚠️ Erro ao ler do banco (Ignorando cache): {e}")
        pass
        
    return None, None, None

def save_token_db(conn, token, uid):
    """Salva ou atualiza o token no banco com horário do Brasil"""
    agora_br = get_data_brasil()
    
    try:
        with conn.session as session:
            query = text("""
                INSERT INTO public."HCMTokens" (id, access_token, user_uid, updated_at)
                VALUES ('bot_hcm_contact', :token, :uid, :hora)
                ON CONFLICT (id) DO UPDATE 
                SET access_token = EXCLUDED.access_token,
                    user_uid = EXCLUDED.user_uid,
                    updated_at = EXCLUDED.updated_at;
            """)
            # Passamos a data do Python (:hora) em vez de usar NOW() do banco
            session.execute(query, {"token": token, "uid": uid, "hora": agora_br})
            session.commit()
    except Exception as e:
        st.error(f"Erro ao salvar token no banco: {e}")

# ==============================================================================
# 4. FUNÇÕES DE API
# ==============================================================================

def get_headers_base():
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://hcm.teknisa.com",
        "Referer": "https://hcm.teknisa.com/login/"
    }

def login_teknisa_novo():
    """Realiza o login real na API e retorna Token + UID"""
    url_login = "https://hcm.teknisa.com/backend_login/index.php/login"
    headers = get_headers_base()
    headers["User-Id"] = HCM_UID_BROWSER

    payload = {
        "disableLoader": False,
        "filter": [
            {"name": "EMAIL", "operator": "=", "value": HCM_USER},
            {"name": "PASSWORD", "operator": "=", "value": HCM_PASS},
            {"name": "PRODUCT_ID", "operator": "=", "value": int(HCM_PROJECT)},
            {"name": "REQUESTER_URL", "operator": "=", "value": "https://hcm.teknisa.com/login/#/login#authentication"},
            {"name": "ATTEMPTS", "operator": "=", "value": 1},
            {"name": "SHOW_FULL_OPERATOR", "operator": "=", "value": False},
            {"name": "HASH", "operator": "=", "value": HCM_HASH},
            {"name": "SESSION_CHANGE", "operator": "=", "value": False},
            {"name": "KEEP_CONNECTED", "operator": "=", "value": "S"},
            {"name": "RC_URL", "operator": "=", "value": "https://rc-hcm.teknisa.com"},
            {"name": "NRORGOPER", "operator": "=", "value": False},
            {"name": "USE_ACCESS_TIME_CONTROL", "operator": "=", "value": True}
        ],
        "page": 1, "requestType": "FilterData",
        "origin": {"containerName": "AUTHENTICATION", "widgetName": "LOGIN"}
    }

    try:
        r = requests.post(url_login, headers=headers, json=payload, timeout=25)
        r.raise_for_status()
        data = r.json()
        
        if "dataset" in data and "userData" in data["dataset"]:
            return data["dataset"]["userData"].get("TOKEN"), data["dataset"]["userData"].get("USER_ID")
    except Exception as e:
        st.error(f"Erro na requisição de login: {e}")
        
    return None, None

def validar_token(token, uid):
    """Testa se o token atual ainda funciona"""
    headers = get_headers_base()
    headers.update({
        "OAuth-Token": token,
        "OAuth-Hash": HCM_HASH,
        "OAuth-Project": HCM_PROJECT,
        "User-Id": str(uid)
    })
    
    try:
        # Faz uma requisição leve para testar a validade
        r = requests.post(
            "https://hcm.teknisa.com/backend/index.php/getEmpresa", 
            headers=headers, 
            json={"filter": [], "page": 1, "itemsPerPage": 1, "requestType": "FilterData"},
            timeout=10 
        )
        return r.status_code == 200 and "dataset" in r.json()
    except:
        return False

def obter_sessao_valida():
    """
    Lógica de Prioridade:
    1. Banco de Dados
    2. Login Novo (apenas se BD falhar ou token inválido)
    """
    conn = init_db_token()
    
    # 1. TENTA BANCO PRIMEIRO
    token_db, uid_db, data_token = get_token_db(conn)
    
    if token_db:
        # Formata a data para exibir no log (apenas visual)
        try:
            data_fmt = pd.to_datetime(data_token).strftime('%d/%m %H:%M')
        except: 
            data_fmt = "?"

        st.caption(f"🔎 Token encontrado no BD (Gerado em: {data_fmt}). Testando validade...")
        
        if validar_token(token_db, uid_db):
            st.toast("Token do banco VÁLIDO! Usando cache.", icon="⚡")
            return token_db, uid_db, "Banco de Dados"
        else:
            st.caption("⚠️ Token do banco EXPIRADO. Gerando novo...")
    else:
        st.caption("ℹ️ Nenhum token no banco ou erro na leitura.")

    # 2. SE FALHOU ACIMA, GERA UM NOVO
    st.caption("🔄 Conectando API Login...")
    token_new, uid_new = login_teknisa_novo()
    
    if token_new:
        save_token_db(conn, token_new, uid_new)
        return token_new, uid_new, "Nova Autenticação"
        
    return None, None, "Falha Crítica"

def get_headers_request(token, uid):
    h = get_headers_base()
    h.update({
        "OAuth-Token": token,
        "OAuth-Hash": HCM_HASH,
        "OAuth-KeepConnected": "Yes",
        "OAuth-Project": HCM_PROJECT,
        "User-Id": str(uid),
        "Referer": "https://hcm.teknisa.com//"
    })
    return h

def formatar_data(data_str):
    if data_str and isinstance(data_str, str): return data_str.split(' ')[0]
    return data_str

# ==============================================================================
# 5. UI PRINCIPAL
# ==============================================================================
def carregar_logo():
    try: return Image.open("logo.png")
    except: return None

with st.sidebar:
    if logo := carregar_logo(): st.image(logo, use_container_width=True)
    st.divider()
    if "name" in st.session_state: st.write(f"👤 **{st.session_state['name']}**"); st.divider()

st.title("📡 Extrator de Contatos - HCM")
st.markdown("Busca inteligente com cache de sessão para máxima performance.")

nomes_input = st.text_area("📋 Lista de Nomes (Um por linha):", height=150)

if st.button("🚀 Iniciar Busca", use_container_width=True):
    if not nomes_input.strip():
        st.warning("Lista vazia.")
    else:
        lista_nomes = [n.strip() for n in nomes_input.split('\n') if n.strip()]
        
        # --- AUTENTICAÇÃO INTELIGENTE ---
        with st.status("🔐 Verificando autenticação...", expanded=True) as status:
            token, uid, origem_auth = obter_sessao_valida()
            
            if not token:
                status.update(label="❌ Falha crítica de login. Verifique as credenciais.", state="error")
                st.stop()
            
            label_auth = "Cache DB (Rápido) ⚡" if origem_auth == "Banco de Dados" else "Login Realizado 🔄"
            status.update(label=f"✅ Autenticado! {label_auth}", state="complete", expanded=False)

        # --- LOOP DE BUSCA ---
        headers = get_headers_request(token, uid)
        relatorio = []
        
        col_prog, col_txt = st.columns([3, 1])
        bar = col_prog.progress(0)
        txt = col_txt.empty()
        table_place = st.empty()
        
        total = len(lista_nomes)
        
        for i, nome in enumerate(lista_nomes):
            txt.caption(f"Processando {i+1}/{total}...")
            
            try:
                # 1. Buscar Pessoa
                pl_pessoa = {
                    "disableLoader": False,
                    "filter": [
                        {"name": "P_DTMESCOMPETENC", "operator": "=", "value": "01/12/2025"},
                        {"name": "P_NRORG", "operator": "=", "value": "3260"},
                        {"name": "NMPESSOA", "value": f"%{nome}%", "operator": "LIKE_I", "isCustomFilter": True}
                    ],
                    "page": 1, "itemsPerPage": 50, "requestType": "FilterData"
                }
                
                # Retry simples
                try:
                    r = requests.post("https://hcm.teknisa.com/backend/index.php/getPessoa", headers=headers, json=pl_pessoa, timeout=10)
                except:
                    time.sleep(1) 
                    r = requests.post("https://hcm.teknisa.com/backend/index.php/getPessoa", headers=headers, json=pl_pessoa, timeout=10)

                # Tratamento para JSON inválido
                try: resp_json = r.json()
                except: resp_json = {}
                
                pessoas = resp_json.get("dataset", {}).get("getPessoa", [])
                
                if pessoas:
                    for p in pessoas:
                        # 2. Buscar Contatos
                        pl_contato = {
                            "filter": [
                                {"name": "P_NRPARCNEGOCIO", "value": p.get("NRPARCNEGOCIO")},
                                {"name": "P_NRORG", "value": p.get("NRORG")},
                                {"name": "P_NRORGPADRAO", "value": "0"}
                            ], "requestType": "FilterData"
                        }
                        
                        r_c = requests.post("https://hcm.teknisa.com/backend/index.php/getFormaComunicacaoParc", headers=headers, json=pl_contato)
                        try: contatos = r_c.json().get("dataset", {}).get("comunicaparc_get", [])
                        except: contatos = []
                        
                        if not contatos:
                            pl_contato["filter"] = [{"name": "P_NRPARCNEGOCIO", "value": p.get("NRPARCNEGOCIO")}]
                            r_c = requests.post("https://hcm.teknisa.com/backend/index.php/getFormaComunicacaoParc", headers=headers, json=pl_contato)
                            try: contatos = r_c.json().get("dataset", {}).get("comunicaparc_get", [])
                            except: contatos = []

                        lista_contatos = []
                        termos = ["MAIL", "CEL", "FONE", "WHATS", "TEL"]
                        for c in contatos:
                            t = str(c.get('NMFORMACOMU') or "").upper()
                            v = c.get('DSCOMUNICAPARC') or c.get('CDCOMUNICAPARC')
                            if any(x in t for x in termos): lista_contatos.append(f"{t}: {v}")

                        relatorio.append({
                            "Busca": nome,
                            "Nome": p.get("NMPESSOA"),
                            "CPF": p.get("NRCPFPESSOA"),
                            "Admissão": formatar_data(p.get("DTADMISSAOPRE")),
                            "Nascimento": formatar_data(p.get("DTNASCPESSOA")),
                            "Contatos": " | ".join(lista_contatos) if lista_contatos else "Sem contato"
                        })
                else:
                    relatorio.append({"Busca": nome, "Nome": "NÃO ENCONTRADO", "Contatos": "-"})
            
            except Exception as e:
                relatorio.append({"Busca": nome, "Nome": "ERRO API", "Contatos": str(e)})
            
            if relatorio:
                table_place.dataframe(pd.DataFrame(relatorio), use_container_width=True)
            
            bar.progress((i + 1) / total)
        
        st.success("Finalizado!")
        if relatorio:
            csv = pd.DataFrame(relatorio).to_csv(index=False, sep=';').encode('utf-8-sig')
            st.download_button("📥 Baixar CSV", csv, "contatos_hcm.csv", "text/csv")