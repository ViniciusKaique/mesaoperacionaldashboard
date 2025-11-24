# streamlit_app.py
import streamlit as st
import streamlit_authenticator as stauth
import psycopg2
import pandas as pd

# -----------------------------
# CONFIGURAÇÕES DE AUTENTICAÇÃO
# -----------------------------
auth_config = {
    'credentials': {
        'usernames': {
            st.secrets["auth"]["username"]: {
                'name': st.secrets["auth"]["name"],
                'password': st.secrets["auth"]["password_hash"],
                'email': st.secrets["auth"]["email"]
            }
        }
    },
    'cookie': {
        'name': st.secrets["auth"]["cookie_name"],
        'key': st.secrets["auth"]["cookie_key"],
        'expiry_days': st.secrets["auth"]["cookie_expiry_days"]
    }
}

authenticator = stauth.Authenticate(
    credentials=auth_config['credentials'],
    cookie_name=auth_config['cookie']['name'],
    key=auth_config['cookie']['key'],
    cookie_expiry_days=auth_config['cookie']['expiry_days'],
)

name, authentication_status, username = authenticator.login("Login", "main")

if authentication_status:
    st.sidebar.success(f"Logado como {name}")
elif authentication_status is False:
    st.error("Usuário ou senha incorretos")
elif authentication_status is None:
    st.warning("Por favor insira suas credenciais")

# -----------------------------
# FUNÇÃO DE CONEXÃO COM POSTGRES
# -----------------------------
def get_connection():
    db_conf = {
        "host": st.secrets["postgres"]["host"],
        "port": st.secrets["postgres"]["port"],
        "user": st.secrets["postgres"]["user"],
        "password": st.secrets["postgres"]["password"],
        "dbname": st.secrets["postgres"]["dbname"],
        "sslmode": st.secrets["postgres"].get("sslmode", "require"),
    }
    return psycopg2.connect(**db_conf)

# -----------------------------
# FUNÇÕES DO APP
# -----------------------------
if authentication_status:
    st.title("📊 Mesa Operacional")

    try:
        conn = get_connection()
        st.success("Conectado ao banco de dados com sucesso!")
    except Exception as e:
        st.error(f"Erro ao conectar ao banco: {e}")
        st.stop()

    # Exemplo: listar tabelas
    st.subheader("Tabelas disponíveis")
    try:
        query = """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema='public'
        ORDER BY table_name;
        """
        df_tables = pd.read_sql(query, conn)
        st.dataframe(df_tables)
    except Exception as e:
        st.error(f"Erro ao buscar tabelas: {e}")

    # Exemplo: visualizar dados de uma tabela
    st.subheader("Visualizar dados da tabela Unidades")
    try:
        query = "SELECT * FROM \"Unidades\" LIMIT 50;"
        df_unidades = pd.read_sql(query, conn)
        st.dataframe(df_unidades)
    except Exception as e:
        st.error(f"Erro ao buscar dados da tabela Unidades: {e}")

    conn.close()

    authenticator.logout("Logout", "sidebar")
