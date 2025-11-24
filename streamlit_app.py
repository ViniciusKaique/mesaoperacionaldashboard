import streamlit as st
import streamlit_authenticator as stauth
import pandas as pd
import plotly.express as px
import psycopg2
from PIL import Image

# --- FUNÇÃO PARA LOGO ---
def carregar_logo():
    try:
        return Image.open("logo.png")
    except:
        return None

# --- AUTENTICAÇÃO ---
auth_conf = st.secrets["auth"]

credentials = {
    "usernames": {
        auth_conf["username"]: {
            "name": auth_conf["name"],
            "password": auth_conf["password_hash"],
            "email": auth_conf["email"],
        }
    }
}

authenticator = stauth.Authenticate(
    credentials,
    auth_conf["cookie_name"],
    auth_conf["cookie_key"],
    auth_conf["cookie_expiry_days"],
)

# LOGIN
if "authentication_status" not in st.session_state:
    st.session_state["authentication_status"] = None

if st.session_state["authentication_status"] is None or st.session_state["authentication_status"] is False:
    col_esq, col_centro, col_dir = st.columns([1, 1.5, 1])
    with col_centro:
        logo = carregar_logo()
        if logo:
            st.image(logo, use_container_width=True)
        try:
            authenticator.login(location='main')
        except:
            authenticator.login()

    if st.session_state["authentication_status"] is False:
        st.error("Usuário ou senha incorretos")

# PÓS LOGIN
if st.session_state["authentication_status"] is True:
    name = st.session_state["name"]

    # --- SIDEBAR ---
    with st.sidebar:
        logo = carregar_logo()
        if logo:
            st.image(logo, use_container_width=True)
        st.divider()
        st.write(f"👤 **{name}**")
        authenticator.logout(location="sidebar")
        st.divider()
        st.info("Mesa Operacional")

    # --- CONEXÃO COM POSTGRES ---
    db_conf = st.secrets["postgres"]

    @st.cache_resource(ttl=3600)
    def get_connection():
        conn = psycopg2.connect(
            host=db_conf["host"],
            port=db_conf["port"],
            user=db_conf["user"],
            password=db_conf["password"],
            dbname=db_conf["dbname"],
            sslmode=db_conf.get("sslmode", "require")
        )
        return conn

    conn = get_connection()

    # --- FUNÇÃO PARA CARREGAR TABELAS ---
    @st.cache_data(ttl=600)
    def carregar_tabela(nome_tabela):
        query = f'SELECT * FROM "{nome_tabela}"'
        return pd.read_sql(query, conn)

    # --- SELEÇÃO DE TABELAS ---
    tabelas = ["Cargos", "Colaboradores", "QuadroEdital", "Supervisores", "TiposUnidades", "Unidades"]
    tabela_selecionada = st.selectbox("Escolha a tabela para visualizar", tabelas)

    df = carregar_tabela(tabela_selecionada)
    st.subheader(f"Tabela: {tabela_selecionada}")
    st.dataframe(df)

    # --- DASHBOARD SIMPLES ---
    if tabela_selecionada == "Colaboradores":
        st.subheader("Distribuição por Unidade")
        if "UnidadeID" in df.columns:
            fig = px.histogram(df, x="UnidadeID", title="Colaboradores por Unidade")
            st.plotly_chart(fig, use_container_width=True)

        st.subheader("Distribuição por Cargo")
        if "CargoID" in df.columns:
            fig2 = px.histogram(df, x="CargoID", title="Colaboradores por Cargo")
            st.plotly_chart(fig2, use_container_width=True)

    elif tabela_selecionada == "QuadroEdital":
        st.subheader("Quantidade por Unidade e Cargo")
        if all(col in df.columns for col in ["UnidadeID", "CargoID", "Quantidade"]):
            fig = px.bar(df, x="UnidadeID", y="Quantidade", color="CargoID", barmode="group",
                         title="Quadro por Unidade e Cargo")
            st.plotly_chart(fig, use_container_width=True)

    st.success("Dados carregados com sucesso!")
