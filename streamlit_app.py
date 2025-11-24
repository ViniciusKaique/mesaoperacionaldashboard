import streamlit as st
import streamlit_authenticator as stauth
import psycopg2
import pandas as pd
from psycopg2.extras import RealDictCursor
import yaml

# --- CONFIGURAÇÕES ---
st.set_page_config(page_title="Mesa Operacional", layout="wide", page_icon="📊")

# --- CARREGAR SECRETS ---
secrets = st.secrets

# Autenticação
config = {
    "credentials": {
        "usernames": {
            secrets["auth"]["username"]: {
                "name": secrets["auth"]["name"],
                "password": secrets["auth"]["password_hash"],
                "email": secrets["auth"]["email"]
            }
        }
    },
    "cookie": {
        "name": secrets["auth"]["cookie_name"],
        "key": secrets["auth"]["cookie_key"],
        "expiry_days": secrets["auth"]["cookie_expiry_days"]
    }
}

authenticator = stauth.Authenticate(
    credentials=config["credentials"],
    cookie_name=config["cookie"]["name"],
    key=config["cookie"]["key"],
    cookie_expiry_days=config["cookie"]["expiry_days"]
)

# --- LOGIN ---
name, authentication_status, username = authenticator.login("Login", location="main")

if authentication_status is False:
    st.error("Usuário ou senha incorretos")
    st.stop()
elif authentication_status is None:
    st.warning("Por favor insira seu usuário e senha")
    st.stop()
elif authentication_status:
    authenticator.logout("Logout", location="sidebar")
    st.sidebar.write(f"👤 {name}")

# --- CONEXÃO COM POSTGRES ---
@st.cache_data(ttl=3600)
def get_connection():
    db_conf = secrets["postgres"]
    try:
        conn = psycopg2.connect(
            host=db_conf["host"],
            port=db_conf.get("port", 5432),
            dbname=db_conf["dbname"],
            user=db_conf["user"],
            password=db_conf["password"],
            sslmode=db_conf.get("sslmode", "require"),
            cursor_factory=RealDictCursor
        )
        return conn
    except Exception as e:
        st.error(f"Erro ao conectar: {e}")
        return None

conn = get_connection()
if conn is None:
    st.stop()

# --- FUNÇÕES AUXILIARES ---
def load_table(table_name):
    query = f'SELECT * FROM "{table_name}" LIMIT 100;'
    df = pd.read_sql(query, conn)
    return df

# --- DASHBOARD ---
st.title("Mesa Operacional")

# Exemplo: seleção de tabela
tabela_selecionada = st.selectbox("Escolha a tabela", ["Cargos", "Colaboradores", "QuadroEdital", "Supervisores", "TiposUnidades", "Unidades"])
df = load_table(tabela_selecionada)
st.dataframe(df)
