import streamlit as st
import pandas as pd
import altair as alt
import requests
import json
import time
import io
from datetime import datetime, timedelta
from PIL import Image

# ==============================================================================
# 1. CONFIGURAÇÃO DA PÁGINA
# ==============================================================================
st.set_page_config(page_title="Gestão de Ocorrências", layout="wide", page_icon="🔔")

# ==============================================================================
# 2. SEGURANÇA E ESTADO
# ==============================================================================
if not st.session_state.get("authentication_status"):
    st.warning("🔒 Acesso restrito. Faça login na página inicial.")
    st.stop()

keys = ['ocorrencias_df', 'msg_detalhe', 'id_selecionado', 'api_token']
for k in keys:
    if k not in st.session_state:
        st.session_state[k] = None

# ==============================================================================
# 3. API E HEADERS
# ==============================================================================
try:
    SECRETS = st.secrets["api_limpeza"]
except:
    st.error("Erro: Secrets não configurado.")
    st.stop()

def get_base_url():
    base = SECRETS.get('base_url_oc', "https://limpeza.sme.prefeitura.sp.gov.br/api/web/ocorrencia")
    if "/ocorrencia" in base: return base.split("/ocorrencia")[0]
    return base.rstrip('/')

BASE_URL_API = get_base_url()
URL_AUTH = f"{BASE_URL_API}/auth"
URL_TABELA = f"{BASE_URL_API}/ocorrencia/tabela"       # Fonte do Status/JSON
URL_EXPORT = f"{BASE_URL_API}/ocorrencia/exportar"     # Fonte do Texto/CSV
URL_MSG_BASE = f"{BASE_URL_API}/ocorrencia/ocorrencia-mensagem/buscar-por-ocorrencia"
URL_ENVIAR_MSG = f"{BASE_URL_API}/ocorrencia/ocorrencia-mensagem/"

HEADERS_CHROME = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Origin": "https://limpeza.sme.prefeitura.sp.gov.br",
    "sec-ch-ua": '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin"
}

# ==============================================================================
# 4. FUNÇÕES DE AUTENTICAÇÃO E ENVIO
# ==============================================================================
def carregar_logo():
    try: return Image.open("logo.png")
    except: return None

def autenticar_e_pegar_token():
    payload = {"email": SECRETS["email"], "senha": SECRETS["senha"]}
    h = HEADERS_CHROME.copy()
    h["Content-Type"] = "application/json;charset=UTF-8"
    h["Referer"] = "https://limpeza.sme.prefeitura.sp.gov.br/login"
    try:
        r = requests.post(URL_AUTH, json=payload, headers=h, timeout=15)
        if r.status_code == 200:
            data = r.json()
            token = None
            if "data" in data and isinstance(data["data"], dict): token = data["data"].get("token")
            elif "token" in data: token = data["token"]
            elif "data" in data and isinstance(data["data"], str): token = data["data"]
            
            if token:
                st.session_state['api_token'] = token
                return token
    except: pass
    return None

def get_header_request():
    token = st.session_state.get('api_token')
    if not token: token = autenticar_e_pegar_token()
    if token:
        h = HEADERS_CHROME.copy()
        h["Authorization"] = f"Bearer {token}"
        h["Referer"] = "https://limpeza.sme.prefeitura.sp.gov.br/ocorrencia/"
        return h
    return None

def enviar_resposta_api(id_oc, mensagem):
    """Envia a mensagem via POST para a API"""
    h = get_header_request()
    if not h: return False, "Falha na autenticação"
    
    # Header específico para envio de JSON
    h["Content-Type"] = "application/json;charset=UTF-8"
    
    payload = {
        "idOcorrencia": str(id_oc),
        "mensagem": mensagem
    }
    
    try:
        r = requests.post(URL_ENVIAR_MSG, json=payload, headers=h, timeout=15)
        if r.status_code == 200 or r.status_code == 201:
            return True, "Enviado"
        else:
            return False, f"Erro {r.status_code}: {r.text}"
    except Exception as e:
        return False, str(e)

# ==============================================================================
# 5. FETCHERS (JSON + CSV)
# ==============================================================================
def fetch_json_paginado(data_inicio, data_fim, headers):
    dt_ini = data_inicio.strftime("%Y-%m-%dT00:00:00.000Z")
    dt_fim = data_fim.strftime("%Y-%m-%dT23:59:59.999Z")
    filtros = {"dataInicial": dt_ini, "dataFinal": dt_fim, "flagSomenteAtivos": "true"}
    
    todos_registros = []
    start, length, total_records = 0, 100, 1 
    
    st.toast("Baixando estrutura (JSON)...", icon="⏳")
    
    while start < total_records:
        params = {"draw": "1", "filters": json.dumps(filtros), "length": length, "start": start}
        try:
            r = requests.get(URL_TABELA, params=params, headers=headers, timeout=20)
            if r.status_code == 200:
                body = r.json()
                data_list = body.get("datatables", {}).get("data", []) if "datatables" in body else body.get("data", [])
                total_n = body.get("datatables", {}).get("recordsTotal", 0) if "datatables" in body else body.get("recordsTotal", 0)
                
                if start == 0:
                    total_records = int(total_n)
                    if total_records == 0: return pd.DataFrame()
                
                if data_list: todos_registros.extend(data_list)
                else: break
                
                start += length
                time.sleep(0.05)
            else: break
        except: break
            
    if todos_registros:
        df = pd.json_normalize(todos_registros)
        rename_map = {
            'id': 'id', 'data': 'dataHoraOcorrencia', 'unidadeEscolar.descricao': 'ueNome',
            'tipo': 'Categoria', 'observacaoFinal': 'observacao_json', 
            'ocorrenciaRespondida': 'ocorrenciaRespondida', 'flagEncerrado': 'flagEncerrado'
        }
        df = df.rename(columns=rename_map)
        
        if 'id' in df.columns:
            df['id'] = df['id'].astype(str).str.replace('.', '', regex=False).str.replace(',', '', regex=False).str.strip()
        
        return df
    return pd.DataFrame()

def fetch_csv_export(data_inicio, data_fim, headers):
    dt_i = data_inicio.strftime("%Y-%m-%dT00:00:00.000Z")
    dt_f = data_fim.strftime("%Y-%m-%dT23:59:59.999Z")
    params = {"filtros": json.dumps({"dataInicial": dt_i, "dataFinal": dt_f, "flagSomenteAtivos": "true"})}
    
    st.toast("Preenchendo observações...", icon="📝")
    try:
        r = requests.get(URL_EXPORT, params=params, headers=headers, timeout=30)
        if r.status_code == 200:
            content = r.text
            try: 
                js = r.json()
                if "data" in js: content = js["data"]
            except: pass
            
            df = pd.read_csv(io.StringIO(content), sep=';')
            if 'id' in df.columns:
                df['id'] = df['id'].astype(str).str.replace('.', '', regex=False).str.replace(',', '', regex=False).str.strip()
            
            cols_csv = ['id', 'observacao', 'acaoCorretiva']
            return df[[c for c in cols_csv if c in df.columns]]
            
    except: pass
    return pd.DataFrame()

def fetch_dados_mesclados(d_ini, d_fim):
    headers = get_header_request()
    if not headers: return None

    # 1. Busca JSON
    df_json = fetch_json_paginado(d_ini, d_fim, headers)
    if df_json.empty: return None

    # 2. Busca CSV
    df_csv = fetch_csv_export(d_ini, d_fim, headers)

    # 3. Mesclagem
    if not df_csv.empty:
        df_final = pd.merge(df_json, df_csv, on='id', how='left', suffixes=('', '_csv'))
        if 'observacao' in df_final.columns:
            df_final['observacao'] = df_final['observacao'].fillna(df_final.get('observacao_json', '-'))
        elif 'observacao_json' in df_final.columns:
            df_final['observacao'] = df_final['observacao_json']
        
        for c in ['observacao', 'acaoCorretiva', 'ueNome']:
            if c in df_final.columns:
                df_final[c] = df_final[c].fillna('-').astype(str)
    else:
        df_final = df_json
        if 'observacao_json' in df_final.columns:
            df_final['observacao'] = df_final['observacao_json']
            
    # 4. Processamento
    if 'dataHoraOcorrencia' in df_final.columns:
        df_final['dataHoraOcorrencia'] = pd.to_datetime(df_final['dataHoraOcorrencia'], errors='coerce')
        df_final['Data'] = df_final['dataHoraOcorrencia'].dt.date
    
    def definir_status(row):
        if 'ocorrenciaRespondida' in row.index:
            val = str(row['ocorrenciaRespondida']).lower()
            if val == 'true': return '✅ Respondido'
            if val == 'false': return '🚨 Sem Resposta'
        if str(row.get('flagEncerrado')).lower() == 'true': return '✅ Respondido'
        return '🚨 Sem Resposta'

    df_final['Status_Resposta'] = df_final.apply(definir_status, axis=1)

    if 'Categoria' not in df_final.columns: df_final['Categoria'] = 'Geral'
    def cat_visual(val):
        v = str(val).lower()
        if 'insumo' in v or 'material' in v: return '🛠️ Insumos'
        if 'equipe' in v or 'falta' in v or 'rh' in v: return '👥 Equipe'
        return '📝 Outros'
    df_final['Categoria_Visual'] = df_final['Categoria'].apply(cat_visual)
    
    return df_final

def fetch_mensagens(id_oc):
    id_clean = str(id_oc).replace('.', '').replace(',', '').strip()
    url = f"{URL_MSG_BASE}/{id_clean}"
    try:
        h = get_header_request()
        r = requests.get(url, headers=h, timeout=15)
        if r.status_code in [401, 403]:
             st.session_state['api_token'] = None
             h = get_header_request()
             r = requests.get(url, headers=h, timeout=15)
        if r.status_code == 200: return r.json().get("data", [])
        return []
    except: return []

# ==============================================================================
# UI COMPONENTS (POPUP)
# ==============================================================================
@st.dialog("Histórico da Ocorrência", width="large")
def exibir_modal_chat(titulo, msgs):
    st.caption(titulo)
    if not msgs:
        st.info("Nenhuma mensagem encontrada para esta ocorrência.")
        return

    with st.container(height=400, border=True):
        for m in msgs:
            nome = m.get("usuario", {}).get("nome", "Sistema")
            txt = m.get("mensagem", "")
            origem = m.get("usuario", {}).get("origem", "")
            try: dt = pd.to_datetime(m.get("dataHora")).strftime('%d/%m %H:%M')
            except: dt = ""
            av = "👷" if origem=='ps' or 'Prestador' in str(m.get("usuario")) else "🏛️"
            
            with st.chat_message("user" if av=="🏛️" else "assistant", avatar=av):
                st.markdown(f"**{nome}** <span style='color:grey; font-size:0.8em'>{dt}</span>", unsafe_allow_html=True)
                st.write(txt)

def plot_top10(df_source, color_hex):
    if df_source.empty: return None
    top = df_source['ueNome'].value_counts().nlargest(10).reset_index()
    top.columns = ['Escola', 'Qtd']
    chart = alt.Chart(top).mark_bar().encode(
        x=alt.X('Qtd', title=None),
        y=alt.Y('Escola', sort='-x', title=None),
        color=alt.value(color_hex),
        tooltip=['Escola', 'Qtd']
    )
    return chart

# ==============================================================================
# MAIN
# ==============================================================================
if logo := carregar_logo(): st.sidebar.image(logo, use_container_width=True)
st.sidebar.divider()
if "name" in st.session_state: st.sidebar.write(f"👤 **{st.session_state['name']}**"); st.sidebar.divider()

st.sidebar.title("Filtros")
hoje = datetime.now()
d_ini = st.sidebar.date_input("Início", hoje)
d_fim = st.sidebar.date_input("Fim", hoje)

# === NOVO: Filtro por Escola ===
df_raw = st.session_state['ocorrencias_df']
lista_escolas = []
if df_raw is not None and not df_raw.empty:
    lista_escolas = sorted(df_raw['ueNome'].unique().tolist())

filtro_escola = st.sidebar.multiselect("Filtrar Escola(s)", options=lista_escolas)

if st.sidebar.button("🔄 Buscar Ocorrências", use_container_width=True):
    st.session_state['ocorrencias_df'] = fetch_dados_mesclados(d_ini, d_fim)
    st.session_state['msg_detalhe'] = None
    st.session_state['id_selecionado'] = None
    st.rerun()

st.title("🔔 Monitoramento de Ocorrências")
df = st.session_state['ocorrencias_df']

if df is not None and not df.empty:
    # Filtro de Data
    if 'Data' in df.columns:
        mask = (df['Data'] >= d_ini) & (df['Data'] <= d_fim)
        df_v = df[mask].copy()
    else: df_v = df.copy()

    # Aplica Filtro de Escola se houver seleção
    if filtro_escola:
        df_v = df_v[df_v['ueNome'].isin(filtro_escola)]

    st.caption(f"Período: **{d_ini.strftime('%d/%m')}** a **{d_fim.strftime('%d/%m')}** | Total: {len(df_v)}")
    
    # KPIs
    k1, k2, k3 = st.columns(3)
    k1.metric("Total", len(df_v))
    k2.metric("✅ Respondidas", len(df_v[df_v['Status_Resposta'] == '✅ Respondido']))
    k3.metric("🚨 Sem Resposta", len(df_v[df_v['Status_Resposta'] == '🚨 Sem Resposta']))
    st.divider()

    # Gráficos Gerais
    c_g1, c_g2 = st.columns(2)
    with c_g1:
        st.subheader("Distribuição Geral")
        if not df_v.empty:
            pie = alt.Chart(df_v).encode(theta=alt.Theta("count()", stack=True)).mark_arc(innerRadius=60).encode(
                color=alt.Color("Categoria_Visual", scale=alt.Scale(scheme='category20')), tooltip=["Categoria_Visual", "count()"])
            st.altair_chart(pie, use_container_width=True)
    with c_g2:
        st.subheader("10 Escolas com mais ocorrências")
        if not df_v.empty:
            st.altair_chart(plot_top10(df_v, '#ff4b4b'), use_container_width=True)
    st.divider()

    # Abas
    tab_eq, tab_in, tab_out = st.tabs(["👥 Equipe/RH", "🛠️ Insumos", "📝 Outros"])
    
    # ---------------- FUNÇÃO PARA RENDERIZAR ABA COM MULTI-SELEÇÃO E RESPOSTA EM MASSA ----------------
    def render_aba(df_filtrado, titulo_grafico, cor_grafico, chave_btn):
        st.subheader(titulo_grafico)
        if not df_filtrado.empty:
            st.altair_chart(plot_top10(df_filtrado, cor_grafico), use_container_width=True)
            st.markdown(f"**Detalhamento ({len(df_filtrado)})**")
            
            # Prepara DF
            cols_orig = ['id', 'Data', 'Status_Resposta', 'ueNome', 'observacao']
            cols_ok = [c for c in cols_orig if c in df_filtrado.columns]
            
            df_show = df_filtrado[cols_ok].rename(columns={
                'id': 'ID', 'Status_Resposta': 'Status', 'ueNome': 'Nome', 'observacao': 'Observações'
            })
            
            # Tabela com seleção MÚLTIPLA
            evt = st.dataframe(
                df_show,
                use_container_width=True, hide_index=True, 
                selection_mode="multi-row", # <--- MUDANÇA IMPORTANTE
                on_select="rerun",
                column_config={"Data": st.column_config.DateColumn("Data", format="DD/MM/YYYY")},
                key=f"data_table_{chave_btn}"
            )
            
            sel_indices = []
            try: sel_indices = evt.selection.rows
            except: 
                try: sel_indices = evt["selection"]["rows"]
                except: pass
            
            # === ÁREA DE AÇÃO (Chat Individual ou Resposta em Massa) ===
            if sel_indices:
                selected_rows = df_show.iloc[sel_indices]
                qtd_selecionada = len(selected_rows)
                ids_selecionados = selected_rows['ID'].tolist()

                st.write(f"🔵 **{qtd_selecionada} item(ns) selecionado(s)**")

                # Se apenas 1 selecionado -> Opção de ver Chat
                if qtd_selecionada == 1:
                    r = selected_rows.iloc[0]
                    curr_id = str(r['ID'])
                    curr_nome = r['Nome']
                    if st.button(f"💬 Abrir Chat: {curr_nome}", key=f"chat_{chave_btn}"):
                         with st.spinner("Carregando..."):
                             msgs = fetch_mensagens(curr_id)
                             exibir_modal_chat(f"📍 {curr_nome} (ID: {curr_id})", msgs)
                
                # Se 1 ou mais selecionados -> Opção de Responder em Massa
                with st.expander("✉️ Enviar Resposta (Individual ou em Massa)", expanded=True):
                    with st.form(key=f"form_massa_{chave_btn}"):
                        st.write(f"Você está prestes a responder para os IDs: {', '.join(map(str, ids_selecionados[:5]))} {'...' if len(ids_selecionados) > 5 else ''}")
                        txt_resposta = st.text_area("Mensagem de Resposta:", height=150)
                        btn_enviar = st.form_submit_button(f"Enviar para {qtd_selecionada} ocorrência(s)")
                        
                        if btn_enviar and txt_resposta:
                            progress_bar = st.progress(0)
                            sucessos = 0
                            erros = 0
                            
                            for idx, id_oc in enumerate(ids_selecionados):
                                ok, msg_retorno = enviar_resposta_api(id_oc, txt_resposta)
                                if ok: sucessos += 1
                                else: erros += 1
                                progress_bar.progress((idx + 1) / qtd_selecionada)
                                time.sleep(0.1) # Pequeno delay para não sobrecarregar
                            
                            progress_bar.empty()
                            if erros == 0:
                                st.success(f"✅ Sucesso! {sucessos} mensagens enviadas.")
                            else:
                                st.warning(f"⚠️ Finalizado. Sucessos: {sucessos}, Erros: {erros}.")
        else:
            st.info("Nenhuma ocorrência nesta categoria.")

    # 1. EQUIPE
    with tab_eq:
        df_rh = df_v[df_v['Categoria_Visual'].str.contains("Equipe")]
        render_aba(df_rh, "10 Escolas com mais ocorrências - Equipe", "#d32f2f", "rh")

    # 2. INSUMOS
    with tab_in:
        df_ins = df_v[df_v['Categoria_Visual'].str.contains("Insumos")]
        render_aba(df_ins, "10 Escolas com mais ocorrências - Insumos", "#f57c00", "in")

    # 3. OUTROS
    with tab_out:
        df_out = df_v[df_v['Categoria_Visual'].str.contains("Outros")]
        render_aba(df_out, "10 Escolas com mais ocorrências - Outros", "#607d8b", "out")

else:
    st.info("👈 Clique em Buscar.")
    if st.button("Carregar Agora"):
        st.session_state['ocorrencias_df'] = fetch_dados_mesclados(hoje, hoje)
        st.rerun()