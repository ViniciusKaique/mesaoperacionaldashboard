import streamlit as st 
import streamlit_authenticator as stauth
import pandas as pd
import plotly.express as px
import numpy as np 
from PIL import Image
from sqlalchemy import text

# =========================
# CONFIG
# =========================
def configurar_pagina():
    st.set_page_config(page_title="Mesa Operacional", layout="wide", page_icon="📊")
    st.markdown("""
    <style>
        .block-container { padding-top: 1rem; }
        .stButton button { background-color: #ff4b4b; color: white; border-radius: 8px; }
        [data-testid="stMetricValue"] { font-size: 30px; font-weight: bold; }
        th, td { text-align: center !important; }
    </style>
    """, unsafe_allow_html=True)

def carregar_logo():
    try:
        return Image.open("logo.png")
    except:
        return None

# =========================
# LOGIN
# =========================
def realizar_login():
    try:
        auth_secrets = st.secrets["auth"]
        config = {
            'credentials': {'usernames': {
                auth_secrets["username"]: {
                    'name': auth_secrets["name"],
                    'password': auth_secrets["password_hash"],
                    'email': auth_secrets["email"]
                }}},
            'cookie': {
                'name': auth_secrets["cookie_name"],
                'key': auth_secrets["cookie_key"],
                'expiry_days': auth_secrets["cookie_expiry_days"]
            }
        }
        authenticator = stauth.Authenticate(
            config['credentials'],
            config['cookie']['name'],
            config['cookie']['key'],
            config['cookie']['expiry_days']
        )

        if not st.session_state.get("authentication_status"):
            col1, col2, col3 = st.columns([3,2,3])
            with col2:
                authenticator.login(location='main')
            if st.session_state.get("authentication_status") is False:
                st.error("Usuário ou senha incorretos")
            return None, None
        
        return authenticator, st.session_state.get("name")

    except:
        st.error("Erro de autenticação. Secrets não configurados.")
        st.stop()

# =========================
# DATA
# =========================
@st.cache_data(ttl=600, show_spinner=False)
def buscar_dados_auxiliares(_conn):
    df_unidades = _conn.query('SELECT "UnidadeID", "NomeUnidade" FROM "Unidades" ORDER BY "NomeUnidade"')
    df_cargos = _conn.query('SELECT "CargoID", "NomeCargo" FROM "Cargos" ORDER BY "NomeCargo"')
    return df_unidades, df_cargos

@st.cache_data(ttl=600, show_spinner=False)
def buscar_dados_operacionais(_conn):
    query_resumo = """
    WITH ContagemReal AS (
        SELECT "UnidadeID", "CargoID", COUNT(*) as "QtdReal"
        FROM "Colaboradores"
        WHERE "Ativo" = TRUE
        GROUP BY "UnidadeID", "CargoID"
    )
    SELECT 
        t."NomeTipo" AS "Tipo", 
        u."UnidadeID", 
        u."NomeUnidade" AS "Escola", 
        u."DataConferencia",
        s."NomeSupervisor" AS "Supervisor", 
        c."NomeCargo" AS "Cargo", 
        q."Quantidade" AS "Previsto",
        COALESCE(cr."QtdReal", 0) AS "Atual"
    FROM "QuadroEdital" q
    JOIN "Unidades" u ON q."UnidadeID" = u."UnidadeID"
    JOIN "Cargos" c ON q."CargoID" = c."CargoID"
    JOIN "TiposUnidades" t ON u."TipoID" = t."TipoID"
    JOIN "Supervisores" s ON u."SupervisorID" = s."SupervisorID"
    LEFT JOIN ContagemReal cr 
        ON q."UnidadeID" = cr."UnidadeID" 
       AND q."CargoID" = cr."CargoID"
    ORDER BY u."NomeUnidade", c."NomeCargo";
    """

    query_func = """
    SELECT u."NomeUnidade" AS "Escola", 
           c."NomeCargo" AS "Cargo", 
           col."Nome" AS "Funcionario", 
           col."ColaboradorID" AS "ID"
    FROM "Colaboradores" col
    JOIN "Unidades" u ON col."UnidadeID" = u."UnidadeID"
    JOIN "Cargos" c ON col."CargoID" = c."CargoID"
    WHERE col."Ativo" = TRUE
    ORDER BY u."NomeUnidade", c."NomeCargo", col."Nome";
    """

    df_resumo = _conn.query(query_resumo)
    df_pessoas = _conn.query(query_func)

    df_resumo['Saldo_num'] = df_resumo['Atual'] - df_resumo['Previsto']
    cond = [df_resumo['Saldo_num'] < 0, df_resumo['Saldo_num'] > 0]
    df_resumo['Status'] = np.select(cond, ['🔴 FALTA', '🔵 EXCEDENTE'], default='🟢 OK')
    df_resumo['Saldo'] = df_resumo['Saldo_num'].apply(lambda x: f"+{x}" if x > 0 else str(int(x)))
    df_resumo['DataConferencia'] = pd.to_datetime(df_resumo['DataConferencia'])

    return df_resumo, df_pessoas

# =========================
# SIDEBAR
# =========================
def exibir_sidebar(authenticator, nome_usuario):
    with st.sidebar:
        if logo := carregar_logo():
            st.image(logo, use_container_width=True)
        st.write(f"👤 **{nome_usuario}**")
        authenticator.logout(location='sidebar')
        st.divider()
        st.info("Painel Gerencial")

# =========================
# METRICAS
# =========================
def exibir_metricas(df):
    c1, c2, c3 = st.columns(3)
    total_prev = int(df['Previsto'].sum())
    total_atual = int(df['Atual'].sum())
    saldo = total_atual - total_prev

    with c1: st.metric("📋 Previsto", total_prev)
    with c2: st.metric("👥 Atual", total_atual)
    with c3: st.metric("⚖️ Saldo Geral", saldo)

# =========================
# MAIN
# =========================
def main():
    configurar_pagina()
    authenticator, nome_usuario = realizar_login()

    if not authenticator:
        return

    exibir_sidebar(authenticator, nome_usuario)

    conn = st.connection("postgres", type="sql")
    df_unidades, df_cargos = buscar_dados_auxiliares(conn)
    df_resumo, df_pessoas = buscar_dados_operacionais(conn)

    st.title("📊 Mesa Operacional")
    st.caption("🔵 Excedente | 🔴 Falta | 🟢 OK")
    exibir_metricas(df_resumo)
    st.divider()

    # =========================
    # FILTROS
    # =========================
    with st.expander("🔎 Filtros", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            filtro_escola = st.selectbox("🏫 Escola", ["Todas"] + sorted(df_resumo['Escola'].unique().tolist()))
        with c2:
            filtro_supervisor = st.selectbox("👔 Supervisor", ["Todos"] + sorted(df_resumo['Supervisor'].unique().tolist()))
        with c3:
            filtro_status = st.selectbox("🚦 Situação", ["Todas", "🔴 FALTA", "🔵 EXCEDENTE", "🟢 OK"])
        with c4:
            termo_busca = st.text_input("👤 Buscar colaborador")

    mask = pd.Series(True, index=df_resumo.index)
    if filtro_escola != "Todas":
        mask &= df_resumo['Escola'] == filtro_escola
    if filtro_supervisor != "Todos":
        mask &= df_resumo['Supervisor'] == filtro_supervisor
    if filtro_status != "Todas":
        mask &= df_resumo['Status'] == filtro_status

    if termo_busca:
        escolas_match = df_pessoas[
            df_pessoas['Funcionario'].str.contains(termo_busca, case=False, na=False) |
            df_pessoas['ID'].astype(str).str.contains(termo_busca, na=False)
        ]['Escola'].unique()
        mask &= df_resumo['Escola'].isin(escolas_match)

    df_final = df_resumo[mask]

    # =========================
    # ABAS
    # =========================
    tab1, tab2 = st.tabs(["🚨 Pendências", "📋 Todas as Escolas"])

    def render_escolas(df):
        for escola, df_e in df.groupby('Escola'):
            saldo = int(df_e['Saldo_num'].sum())
            icone = "🟢" if saldo == 0 else "🔵" if saldo > 0 else "🔴"

            with st.expander(f"{icone} {escola}", expanded=False):
                c_q, c_p = st.columns([1.2, 1])

                with c_q:
                    st.markdown("#### 📊 Quadro de Vagas")
                    st.dataframe(
                        df_e[['Cargo','Previsto','Atual','Saldo','Status']],
                        use_container_width=True,
                        hide_index=True
                    )

                with c_p:
                    st.markdown("#### 👥 Colaboradores")
                    df_p = df_pessoas[df_pessoas['Escola'] == escola]
                    if not df_p.empty:
                        st.dataframe(df_p[['ID','Funcionario','Cargo']], use_container_width=True, hide_index=True)
                    else:
                        st.caption("Sem colaboradores.")

    with tab1:
        df_pend = df_final[df_final['Status'] != '🟢 OK']
        if df_pend.empty:
            st.success("Nenhuma pendência encontrada 🎉")
        else:
            render_escolas(df_pend)

    with tab2:
        if df_final.empty:
            st.warning("Nenhuma escola encontrada.")
        else:
            render_escolas(df_final)

if __name__ == "__main__":
    main()
