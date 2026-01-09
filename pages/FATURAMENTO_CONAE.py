import streamlit as st
import pandas as pd
import altair as alt
import requests
import io
import json
from datetime import datetime, timedelta
from PIL import Image

# ==============================================================================
# CONFIGURAÇÃO DA PÁGINA
# ==============================================================================
st.set_page_config(page_title="Monitoramento de Contratos", layout="wide", page_icon="📈")

# ==============================================================================
# VERIFICAÇÃO DE SEGURANÇA
# ==============================================================================
if not st.session_state.get("authentication_status"):
    st.warning("🔒 Acesso restrito. Por favor, faça login na página inicial.")
    st.stop()

# ==============================================================================
# 🔐 CARREGAMENTO DOS SEGREDOS
# ==============================================================================
try:
    SECRETS = st.secrets["api_limpeza"]
except Exception as e:
    st.error("❌ Erro de Configuração: Segredos da API ('api_limpeza') não encontrados.")
    st.stop()

# Inicializa token na sessão se não existir
if 'api_token' not in st.session_state:
    st.session_state['api_token'] = SECRETS.get('token', '')

# ==============================================================================
# ESTADO
# ==============================================================================
keys_to_init = ['monit_df_dashboard', 'monit_df_comp1', 'monit_df_comp2', 
                'dashboard_ano', 'dashboard_mes', 
                'comp1_ano', 'comp1_mes', 'comp2_ano', 'comp2_mes']

for key in keys_to_init:
    if key not in st.session_state:
        st.session_state[key] = None

# ==============================================================================
# HEADERS DE NAVEGADOR (CORREÇÃO DE BLOQUEIO)
# ==============================================================================
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
# FUNÇÕES DE PROCESSAMENTO
# ==============================================================================
def carregar_logo():
    try: return Image.open("logo.png")
    except: return None

def processar_dataframe(df):
    if df is None or df.empty: return None
    df.columns = df.columns.str.strip()
    
    numeric_cols = [
        'totalContrato', 'descontoContrato', 'liquidoContrato',
        'totalUnidade', 'glosaImrUnidade', 'glosaRhUnidade', 
        'liquidoUnidade', 'percentualImrUnidade', 'pontuacaoUnidade'
    ]
    
    for col in numeric_cols:
        if col in df.columns:
            df[col] = df[col].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            
    if 'glosaImrUnidade' in df.columns and 'glosaRhUnidade' in df.columns:
        df['Total Glosas'] = df['glosaImrUnidade'] + df['glosaRhUnidade']
    
    if 'nomeFiscal' in df.columns:
        df['nomeFiscal'] = df['nomeFiscal'].fillna('').astype(str).str.strip()

    return df

# --- AUTENTICAÇÃO API (Funcional) ---
def autenticar_api():
    """Faz login na API e extrai o token corretamente do JSON aninhado"""
    base = SECRETS['base_url'].replace('/ocorrencia', '').replace('/auth', '')
    url_auth = f"{base}/auth"
    if url_auth.endswith("//auth"): url_auth = url_auth.replace("//auth", "/auth")
    
    payload = {
        "email": SECRETS["email"],
        "senha": SECRETS["senha"]
    }
    
    h_login = HEADERS_CHROME.copy()
    h_login["Content-Type"] = "application/json;charset=UTF-8"
    h_login["Referer"] = "https://limpeza.sme.prefeitura.sp.gov.br/login"
    
    try:
        response = requests.post(url_auth, json=payload, headers=h_login, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            # Extração correta (data -> data -> token)
            token = None
            if "data" in data and isinstance(data["data"], dict):
                token = data["data"].get("token")
            elif "token" in data:
                token = data["token"]
            elif "data" in data and isinstance(data["data"], str):
                token = data["data"]
            
            if token:
                st.session_state['api_token'] = token
                return token
    except:
        pass
    return None

def fetch_api_data(ano, mes, silent=False):
    """Busca na API com Retry de Autenticação"""
    
    if "exportar" in SECRETS["base_url"]:
         url = SECRETS["base_url"]
    else:
         base = SECRETS['base_url'].rstrip('/')
         url = f"{base}/relatorio/relatorio-contrato/exportar/"
    
    params = {
        "ano": ano,
        "mes": mes,
        "idContrato": SECRETS["id_contrato"],
        "idPrestadorServico": SECRETS["id_prestador"]
    }
    
    def _make_request(token):
        h = HEADERS_CHROME.copy()
        h["Authorization"] = f"Bearer {token}"
        h["Referer"] = "https://limpeza.sme.prefeitura.sp.gov.br/dashboard"
        return requests.get(url, params=params, headers=h, timeout=25)

    if not silent:
        st.toast(f"Sincronizando: {mes}/{ano}...", icon="⏳")
    
    try:
        token_atual = st.session_state.get('api_token')
        if not token_atual:
            token_atual = autenticar_api()
            
        if not token_atual: return None

        response = _make_request(token_atual)
        
        # Retry se token expirou
        if response.status_code in [401, 403]:
            if not silent: st.toast("Renovando token...", icon="🔑")
            novo_token = autenticar_api()
            if novo_token:
                response = _make_request(novo_token)
            else:
                if not silent: st.error("Falha na renovação do token.")
                return None

        if response.status_code == 200:
            try:
                try:
                    json_response = response.json()
                    if "data" in json_response and json_response["data"]:
                        df = pd.read_csv(io.StringIO(json_response["data"]), sep=';')
                        return processar_dataframe(df)
                except: pass
                
                df = pd.read_csv(io.StringIO(response.text), sep=';')
                return processar_dataframe(df)
            except:
                if not silent: st.error("Erro ao processar dados.")
                return None
        else:
            if not silent: st.warning(f"Sem dados ({response.status_code})")
            return None

    except Exception as e:
        if not silent: st.error(f"Erro Conexão: {e}")
        return None

# --- RESTAURADA A LÓGICA DE RETROCESSO ---
def obter_dados(ano_alvo, mes_alvo):
    """
    Tenta buscar o mês alvo. 
    Se falhar (API retornou vazio/None), recua 1 mês automaticamente.
    """
    # 1. Tentativa Oficial
    df = fetch_api_data(ano_alvo, mes_alvo, silent=True)
    
    if df is not None and not df.empty:
        return df, ano_alvo, mes_alvo
    
    # 2. Cálculo do Mês Anterior
    data_alvo = datetime(ano_alvo, mes_alvo, 1)
    data_anterior = data_alvo - timedelta(days=1)
    
    ano_fallback = data_anterior.year
    mes_fallback = data_anterior.month
    
    st.toast(f"Mês {mes_alvo}/{ano_alvo} sem dados. Buscando {mes_fallback}/{ano_fallback}...", icon="🔄")
    
    # 3. Tentativa Fallback
    df_fallback = fetch_api_data(ano_fallback, mes_fallback, silent=False)
    
    if df_fallback is not None and not df_fallback.empty:
        st.warning(f"⚠️ Dados de **{mes_alvo}/{ano_alvo}** indisponíveis. Exibindo competência **{mes_fallback}/{ano_fallback}**.")
        return df_fallback, ano_fallback, mes_fallback
    
    st.error("Não foi possível obter dados (nem atual, nem anterior).")
    return None, ano_alvo, mes_alvo

# ==============================================================================
# UI & NAVEGAÇÃO
# ==============================================================================

if logo := carregar_logo():
    st.sidebar.image(logo, use_container_width=True)
    st.sidebar.divider()

if "name" in st.session_state:
    st.sidebar.write(f"👤 **{st.session_state['name']}**")
    st.sidebar.divider()

st.sidebar.title("Menu Monitoramento")
page_mode = st.sidebar.radio("Selecione a Visão:", ["Dashboard Geral", "Comparador (Mês a Mês)"])

hoje = datetime.now()

# ------------------------------------------------------------------------------
# DASHBOARD GERAL
# ------------------------------------------------------------------------------
if page_mode == "Dashboard Geral":
    st.title("📊 Dashboard: Monitoramento Mensal")
    
    if st.session_state['monit_df_dashboard'] is None:
        with st.spinner("Sincronizando dados..."):
            df_auto, a_final, m_final = obter_dados(hoje.year, hoje.month)
            if df_auto is not None:
                st.session_state['monit_df_dashboard'] = df_auto
                st.session_state['dashboard_ano'] = a_final
                st.session_state['dashboard_mes'] = m_final
                st.rerun()

    st.sidebar.markdown("---")
    st.sidebar.subheader("📅 Período")
    
    padrao_ano = st.session_state.get('dashboard_ano') or hoje.year
    padrao_mes = st.session_state.get('dashboard_mes') or hoje.month
    
    c1, c2 = st.sidebar.columns(2)
    ano_sel = c1.number_input("Ano", 2024, 2030, padrao_ano)
    mes_sel = c2.number_input("Mês", 1, 12, padrao_mes)
    
    if st.sidebar.button("🔄 Atualizar", use_container_width=True):
        df_new, a_new, m_new = obter_dados(ano_sel, mes_sel)
        if df_new is not None:
            st.session_state['monit_df_dashboard'] = df_new
            st.session_state['dashboard_ano'] = a_new
            st.session_state['dashboard_mes'] = m_new
            st.rerun()

    df = st.session_state['monit_df_dashboard']
    
    if df is not None:
        mes_txt = st.session_state.get('dashboard_mes')
        ano_txt = st.session_state.get('dashboard_ano')
        st.caption(f"📅 Dados de: **{mes_txt}/{ano_txt}**")
        st.markdown("---")

        df_f = df.copy()
        total = len(df_f)
        sem_fiscal = df_f[df_f['nomeFiscal'].isin(['-', '', 'nan'])].shape[0]
        
        st.markdown("### Indicadores Gerais")
        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("Valor Total", f"R$ {df_f['totalUnidade'].sum():,.2f}")
        k2.metric("Glosa IMR", f"R$ {df_f['glosaImrUnidade'].sum():,.2f}", delta_color="inverse")
        k3.metric("Glosa RH", f"R$ {df_f['glosaRhUnidade'].sum():,.2f}", delta_color="inverse")
        k4.metric("Pontuação", f"{df_f['pontuacaoUnidade'].mean():.2f}")
        k5.metric("Aguardando Fiscal", f"{sem_fiscal}", help="Unidades sem fiscal")
        
        st.divider()
        
        if sem_fiscal > 0:
            with st.expander(f"⚠️ Ver {sem_fiscal} Unidades sem Fiscal"):
                st.dataframe(df_f[df_f['nomeFiscal'].isin(['-', '', 'nan'])][['nomeUnidadeEscolar', 'nomeLote', 'totalUnidade']], use_container_width=True, hide_index=True)

        c1, c2 = st.columns(2)
        with c1:
            st.subheader("10 Maiores - Glosa IMR")
            if df_f['glosaImrUnidade'].sum() > 0:
                top = df_f.nlargest(10, 'glosaImrUnidade')
                st.altair_chart(alt.Chart(top).mark_bar().encode(x='glosaImrUnidade', y=alt.Y('nomeUnidadeEscolar', sort='-x'), color=alt.value('#f57c00')), use_container_width=True)
            else: st.info("Sem dados de IMR.")
            
        with c2:
            st.subheader("10 Maiores - Glosa RH")
            if df_f['glosaRhUnidade'].sum() > 0:
                top = df_f.nlargest(10, 'glosaRhUnidade')
                st.altair_chart(alt.Chart(top).mark_bar().encode(x='glosaRhUnidade', y=alt.Y('nomeUnidadeEscolar', sort='-x'), color=alt.value('#d32f2f')), use_container_width=True)
            else: st.info("Sem dados de RH.")
    else:
        st.info("Iniciando sistema...")

# ------------------------------------------------------------------------------
# COMPARADOR
# ------------------------------------------------------------------------------
elif page_mode == "Comparador (Mês a Mês)":
    st.title("⚖️ Comparativo Mensal")
    
    if st.session_state['monit_df_comp2'] is None:
        with st.spinner("Preparando comparação..."):
            df2, a2, m2 = obter_dados(hoje.year, hoje.month)
            if df2 is not None:
                st.session_state['monit_df_comp2'] = df2
                st.session_state['comp2_ano'] = a2
                st.session_state['comp2_mes'] = m2
                
                dt_b2 = datetime(a2, m2, 1)
                dt_b1 = dt_b2 - timedelta(days=1)
                
                df1 = fetch_api_data(dt_b1.year, dt_b1.month, silent=False)
                if df1 is not None:
                    st.session_state['monit_df_comp1'] = df1
                    st.session_state['comp1_ano'] = dt_b1.year
                    st.session_state['comp1_mes'] = dt_b1.month
                st.rerun()

    st.sidebar.markdown("---")
    st.sidebar.subheader("🎛️ Configurar Comparação")
    
    st.sidebar.markdown("**Base 1 (Referência)**")
    a1_d = st.session_state.get('comp1_ano') or hoje.year
    m1_d = st.session_state.get('comp1_mes') or 1
    ca1, cm1 = st.sidebar.columns(2)
    a1 = ca1.number_input("Ano 1", 2024, 2030, a1_d, key="a1")
    m1 = cm1.number_input("Mês 1", 1, 12, m1_d, key="m1")
    
    if st.sidebar.button("Buscar Base 1", use_container_width=True):
        st.session_state['monit_df_comp1'] = fetch_api_data(a1, m1)
        st.session_state['comp1_ano'] = a1
        st.session_state['comp1_mes'] = m1
        st.rerun()

    st.sidebar.markdown("---")
    st.sidebar.markdown("**Base 2 (Atual)**")
    a2_d = st.session_state.get('comp2_ano') or hoje.year
    m2_d = st.session_state.get('comp2_mes') or hoje.month
    ca2, cm2 = st.sidebar.columns(2)
    a2 = ca2.number_input("Ano 2", 2024, 2030, a2_d, key="a2")
    m2 = cm2.number_input("Mês 2", 1, 12, m2_d, key="m2")
    
    if st.sidebar.button("Buscar Base 2", use_container_width=True):
        df_new, a_new, m_new = obter_dados(a2, m2)
        if df_new is not None:
            st.session_state['monit_df_comp2'] = df_new
            st.session_state['comp2_ano'] = a_new
            st.session_state['comp2_mes'] = m_new
            st.rerun()

    df1 = st.session_state['monit_df_comp1']
    df2 = st.session_state['monit_df_comp2']

    if df1 is not None and df2 is not None:
        st.info(f"Comparando: **{st.session_state['comp1_mes']}/{st.session_state['comp1_ano']}** vs **{st.session_state['comp2_mes']}/{st.session_state['comp2_ano']}**")
        st.divider()
        
        fat1, fat2 = df1['totalUnidade'].sum(), df2['totalUnidade'].sum()
        rh1, rh2 = df1['glosaRhUnidade'].sum(), df2['glosaRhUnidade'].sum()
        
        k1, k2, k3 = st.columns(3)
        delta = fat2 - fat1
        perc = (delta / fat1 * 100) if fat1 > 0 else 0
        
        k1.metric("Fat. Base 1", f"R$ {fat1:,.2f}")
        k2.metric("Fat. Base 2", f"R$ {fat2:,.2f}")
        k3.metric("Variação", f"R$ {delta:,.2f}", f"{perc:.2f}%", delta_color="normal")
        
        st.divider()
        st.subheader("2. Performance de RH")
        
        prh1 = (rh1 / fat1 * 100) if fat1 > 0 else 0
        prh2 = (rh2 / fat2 * 100) if fat2 > 0 else 0
        delta_rh = prh2 - prh1
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Glosa RH (Atual)", f"R$ {rh2:,.2f}", f"{rh2-rh1:,.2f}", delta_color="inverse")
        c2.metric("Representatividade (%)", f"{prh2:.2f}%", f"{delta_rh:+.2f} p.p", delta_color="inverse")
        
        with c3:
            if delta_rh > 0: st.warning(f"⚠️ PIORA: +{abs(delta_rh):.2f} p.p")
            elif delta_rh < 0: st.success(f"✅ MELHORA: -{abs(delta_rh):.2f} p.p")
            else: st.info("Estável")

        st.divider()
        st.subheader("🏫 Comparativo Detalhado")
        q = st.text_input("Buscar Escola:", placeholder="Digite o nome...")
        
        cols = ['nomeUnidadeEscolar', 'totalUnidade', 'glosaRhUnidade']
        g1 = df1[cols].groupby('nomeUnidadeEscolar').sum().reset_index()
        g2 = df2[cols].groupby('nomeUnidadeEscolar').sum().reset_index()
        
        merged = pd.merge(g1, g2, on='nomeUnidadeEscolar', how='outer', suffixes=('_1', '_2')).fillna(0)
        merged['Dif Fat'] = merged['totalUnidade_2'] - merged['totalUnidade_1']
        merged['Dif RH'] = merged['glosaRhUnidade_2'] - merged['glosaRhUnidade_1']
        
        if q: merged = merged[merged['nomeUnidadeEscolar'].str.contains(q, case=False)]
        merged = merged.sort_values('Dif RH', ascending=False)

        st.dataframe(
            merged[['nomeUnidadeEscolar', 'totalUnidade_1', 'totalUnidade_2', 'Dif Fat', 'glosaRhUnidade_1', 'glosaRhUnidade_2', 'Dif RH']],
            use_container_width=True,
            column_config={
                "nomeUnidadeEscolar": "Escola",
                "totalUnidade_1": st.column_config.NumberColumn("Fat 1", format="R$ %.2f"),
                "totalUnidade_2": st.column_config.NumberColumn("Fat 2", format="R$ %.2f"),
                "Dif Fat": st.column_config.NumberColumn("Δ Fat", format="R$ %.2f"),
                "glosaRhUnidade_1": st.column_config.NumberColumn("RH 1", format="R$ %.2f"),
                "glosaRhUnidade_2": st.column_config.NumberColumn("RH 2", format="R$ %.2f"),
                "Dif RH": st.column_config.NumberColumn("Δ RH", format="R$ %.2f"),
            },
            hide_index=True
        )