# streamlit_app.py

import streamlit as st
import psycopg2
import pandas as pd
import streamlit_authenticator as stauth
from psycopg2.extras import RealDictCursor

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Mesa Operacional", layout="wide", page_icon="📊")

# --- CARREGAR CONFIGURAÇÃO DO SECRETS ---
db_conf = st.secrets["postgres"]
auth_conf = st.secrets["auth"]

# --- AUTENTICAÇÃO ---
credentials = {
    "usernames": {
        auth_conf["username"]: {
            "name": auth_conf["name"],
            "password": auth_conf["password_hash"],
            "email": auth_conf["email"]
        }
    }
}

cookie = {
    "name": auth_conf["cookie_name"],
    "key": auth_conf["cookie_key"],
    "expiry_days": auth_conf["cookie_expiry_days"]
}

authenticator = stauth.Authenticate(
    credentials=credentials,
    cookie_name=cookie["name"],
    key=cookie["key"],
    cookie_expiry_days=cookie["expiry_days"]
)

# --- LOGIN ---
name, authentication_status, username = authenticator.login("Login", "main")

if authentication_status is None:
    st.warning("Por favor insira seu usuário e senha")
elif authentication_status is False:
    st.error("Usuário ou senha incorretos")
else:
    # --- BOTÃO DE LOGOUT ---
    authenticator.logout("Logout", "sidebar")

    st.sidebar.write(f"👤 {name}")

    st.title("Mesa Operacional")

    # --- CONEXÃO COM POSTGRESQL ---
    @st.cache_data(show_spinner=False)
    def get_connection():
        try:
            conn = psycopg2.connect(
                host=db_conf["host"],
                port=db_conf["port"],
                user=db_conf["user"],
                password=db_conf["password"],
                dbname=db_conf["dbname"],
                sslmode=db_conf.get("sslmode", "require"),
                cursor_factory=RealDictCursor
            )
            return conn
        except Exception as e:
            st.error(f"Erro ao conectar: {e}")
            return None

    conn = get_connection()

    if conn:
        # --- CONSULTA DE EXEMPLO ---
        st.subheader("Tabela de Unidades")
        try:
            query = "SELECT * FROM Unidades LIMIT 50;"
            df = pd.read_sql(query, conn)
            st.dataframe(df)
        except Exception as e:
            st.error(f"Erro ao executar consulta: {e}")
