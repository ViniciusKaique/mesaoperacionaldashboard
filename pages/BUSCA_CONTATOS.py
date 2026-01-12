import streamlit as st
import requests
import pandas as pd
import time
from PIL import Image

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
    st.error(f"⚠️ Erro de Configuração: Credenciais [hcm_api] não encontradas no secrets.toml. Erro: {e}")
    st.stop()

# ==============================================================================
# 3. FUNÇÕES AUXILIARES E API
# ==============================================================================

def carregar_logo():
    try: return Image.open("logo.png")
    except: return None

def formatar_data(data_str):
    """Remove o horário das datas do Teknisa (ex: 11/06/1992 00:00:00 -> 11/06/1992)"""
    if data_str and isinstance(data_str, str):
        return data_str.split(' ')[0]
    return data_str

def get_headers_base():
    """Headers comuns para evitar bloqueio"""
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://hcm.teknisa.com",
        "Referer": "https://hcm.teknisa.com/login/"
    }

def autenticar_hcm_auto():
    """Realiza o login automático e retorna o Token e o UID real"""
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
        "page": 1,
        "requestType": "FilterData",
        "origin": {
            "containerName": "AUTHENTICATION",
            "widgetName": "LOGIN",
            "containerLabel": "Autenticação",
            "widgetLabel": "Login"
        }
    }

    try:
        r = requests.post(url_login, headers=headers, json=payload, timeout=15)
        r.raise_for_status()
        data = r.json()
        
        if "dataset" in data and "userData" in data["dataset"]:
            token = data["dataset"]["userData"].get("TOKEN")
            uid_retornado = data["dataset"]["userData"].get("USER_ID", HCM_UID_BROWSER)
            return token, uid_retornado
        return None, None
    except Exception as e:
        st.error(f"Erro na conexão de login: {e}")
        return None, None

def get_headers_autenticados(token, uid):
    """Gera headers para as requisições de dados"""
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

# ==============================================================================
# 4. SIDEBAR
# ==============================================================================
with st.sidebar:
    if logo := carregar_logo(): 
        st.image(logo, use_container_width=True)
    st.divider()
    
    if "name" in st.session_state: 
        st.write(f"👤 **{st.session_state['name']}**")
        st.divider()
    
    st.info("ℹ️ Insira um nome por linha na caixa de texto principal.")

# ==============================================================================
# 5. CORPO PRINCIPAL
# ==============================================================================
st.title("📡 Extrator de Contatos - HCM Teknisa")
st.markdown("Busca automática de telefones e e-mails de colaboradores ativos.")

nomes_input = st.text_area("📋 Lista de Nomes (Um por linha):", height=200, placeholder="Ex:\nJOAO DA SILVA\nMARIA OLIVEIRA")

if st.button("🚀 Iniciar Busca", use_container_width=True):
    if not nomes_input.strip():
        st.warning("⚠️ A lista de nomes está vazia.")
    else:
        lista_nomes = [n.strip() for n in nomes_input.split('\n') if n.strip()]
        total = len(lista_nomes)
        
        # --- 1. LOGIN AUTOMÁTICO ---
        with st.status("🔐 Autenticando no sistema...", expanded=True) as status:
            token_auth, uid_auth = autenticar_hcm_auto()
            
            if not token_auth:
                status.update(label="❌ Falha no Login! Verifique credenciais no secrets.", state="error")
                st.stop()
            
            status.update(label="✅ Login realizado com sucesso! Iniciando extração...", state="complete", expanded=False)
        
        # --- 2. EXTRAÇÃO ---
        headers = get_headers_autenticados(token_auth, uid_auth)
        relatorio = []
        
        col_bar, col_txt = st.columns([3, 1])
        progress_bar = col_bar.progress(0)
        status_text = col_txt.empty()
        table_placeholder = st.empty()

        for i, nome in enumerate(lista_nomes):
            status_text.caption(f"Processando: {i+1}/{total}")
            try:
                # A. Busca Pessoa
                payload_p = {
                    "disableLoader": False,
                    "filter": [
                        # Filtro de data genérico para pegar ativos recentes ou histórico
                        {"name": "P_DTMESCOMPETENC", "operator": "=", "value": "01/12/2025"}, 
                        {"name": "P_NRORG", "operator": "=", "value": "3260"},
                        {"name": "NMPESSOA", "value": f"%{nome}%", "operator": "LIKE_I", "isCustomFilter": True}
                    ],
                    "page": 1, "itemsPerPage": 50, "requestType": "FilterData"
                }

                r = requests.post("https://hcm.teknisa.com/backend/index.php/getPessoa", headers=headers, json=payload_p, timeout=10)
                
                pessoas = []
                try: pessoas = r.json().get("dataset", {}).get("getPessoa", [])
                except: pass

                if pessoas:
                    for p_data in pessoas:
                        nome_encontrado = p_data.get("NMPESSOA")
                        id_v = p_data.get("NRPARCNEGOCIO")
                        org_v = p_data.get("NRORG")
                        vinculo = p_data.get("NRVINCULOM")
                        cpf = p_data.get("NRCPFPESSOA")
                        admissao = formatar_data(p_data.get("DTADMISSAOPRE"))
                        nascimento = formatar_data(p_data.get("DTNASCPESSOA"))

                        # B. Busca Contatos
                        payload_c = {
                            "filter": [
                                {"name": "P_NRPARCNEGOCIO", "value": id_v},
                                {"name": "P_NRORG", "value": org_v},
                                {"name": "P_NRORGPADRAO", "value": "0"}
                            ],
                            "requestType": "FilterData"
                        }

                        r_c = requests.post("https://hcm.teknisa.com/backend/index.php/getFormaComunicacaoParc", headers=headers, json=payload_c, timeout=10)
                        contatos = []
                        try: contatos = r_c.json().get("dataset", {}).get("comunicaparc_get", [])
                        except: pass

                        # Fallback: Tenta buscar sem organização se falhar
                        if not contatos:
                            payload_c["filter"] = [{"name": "P_NRPARCNEGOCIO", "value": id_v}]
                            try:
                                r_c = requests.post("https://hcm.teknisa.com/backend/index.php/getFormaComunicacaoParc", headers=headers, json=payload_c, timeout=10)
                                contatos = r_c.json().get("dataset", {}).get("comunicaparc_get", [])
                            except: pass

                        # Processa Lista de Contatos
                        info_list = []
                        termos_interesse = ["MAIL", "CEL", "FONE", "MOV", "WHATS", "TEL"]
                        
                        for c in contatos:
                            tipo = str(c.get('NMFORMACOMU') or "").upper()
                            valor = c.get('DSCOMUNICAPARC') or c.get('CDCOMUNICAPARC')
                            
                            # Filtra apenas contatos úteis
                            if valor and any(t in tipo for t in termos_interesse):
                                info_list.append(f"🔹 {tipo}: {valor}")
                        
                        relatorio.append({
                            "Busca": nome,
                            "Nome Completo": nome_encontrado,
                            "CPF": cpf,
                            "Admissão": admissao,
                            "Nascimento": nascimento,
                            "Contatos": "  ".join(info_list) if info_list else "⚠️ Sem contato cadastrado"
                        })
                else:
                    relatorio.append({"Busca": nome, "Nome Completo": "❌ NÃO LOCALIZADO", "Contatos": "-"})

            except Exception as e:
                relatorio.append({"Busca": nome, "Nome Completo": "❌ ERRO API", "Contatos": str(e)})

            # Atualiza UI
            if relatorio:
                df_temp = pd.DataFrame(relatorio)
                table_placeholder.dataframe(
                    df_temp, 
                    use_container_width=True,
                    column_config={
                        "Contatos": st.column_config.TextColumn("Meios de Contato", width="large"),
                        "Nome Completo": st.column_config.TextColumn("Nome no Sistema", width="medium"),
                    }
                )
            
            progress_bar.progress((i + 1) / total)
            time.sleep(0.1) # Pequeno delay para não sobrecarregar API visualmente

        st.success("✅ Busca Finalizada!")
        
        if relatorio:
            df_final = pd.DataFrame(relatorio)
            csv = df_final.to_csv(index=False, sep=';').encode('utf-8-sig')
            st.download_button(
                label="📥 Baixar Planilha (Excel/CSV)",
                data=csv,
                file_name="contatos_hcm_teknisa.csv",
                mime="text/csv",
                use_container_width=True
            )