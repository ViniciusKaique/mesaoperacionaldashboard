import streamlit as st
import streamlit_authenticator as stauth
import pandas as pd
import plotly.express as px
import numpy as np
from PIL import Image
from sqlalchemy import text

# =============================
# Configurações e Cache Base
# =============================

@st.cache_resource
def get_conn():
    return st.connection("postgres", type="sql")

@st.cache_resource
def carregar_logo():
    try:
        return Image.open("logo.png")
    except:
        return None


def configurar_pagina():
    st.set_page_config(page_title="Mesa Operacional", layout="wide", page_icon="📊")
    st.markdown("""
    <style>
        .block-container { padding-top: 1rem; }
        .stButton button { background-color: #ff4b4b; color: white; border-radius: 8px; }
        [data-testid="stMetricValue"] { font-size: 32px; font-weight: bold; }
        .dataframe { font-size: 14px !important; }
        th, td { text-align: center !important; }
        div[data-testid="stSpinner"] > div {
            font-size: 28px !important; font-weight: bold !important;
            color: #ff4b4b !important; white-space: nowrap;
        }
        div.stButton > button { width: 100%; }
    </style>
    """, unsafe_allow_html=True)

# =============================
# Autenticação
# =============================

def realizar_login():
    auth = st.secrets["auth"]
    config = {
        'credentials': {'usernames': {
            auth["username"]: {
                'name': auth["name"],
                'password': auth["password_hash"],
                'email': auth["email"]
            }}},
        'cookie': {
            'name': auth["cookie_name"],
            'key': auth["cookie_key"],
            'expiry_days': auth["cookie_expiry_days"]
        }
    }

    authenticator = stauth.Authenticate(
        config['credentials'],
        config['cookie']['name'],
        config['cookie']['key'],
        config['cookie']['expiry_days']
    )

    if not st.session_state.get("authentication_status"):
        col1, col2, col3 = st.columns([3, 2, 3])
        with col2:
            authenticator.login(location="main")
            if st.session_state.get("authentication_status") is False:
                st.error("Usuário ou senha incorretos")
        return None, None

    return authenticator, st.session_state.get("name")

# =============================
# Dados
# =============================

@st.cache_data(ttl=600, show_spinner=False)
def buscar_dados_auxiliares(conn):
    return (
        conn.query('SELECT "UnidadeID","NomeUnidade" FROM "Unidades" ORDER BY "NomeUnidade"'),
        conn.query('SELECT "CargoID","NomeCargo" FROM "Cargos" ORDER BY "NomeCargo"')
    )

@st.cache_data(ttl=600, show_spinner=False)
def buscar_dados_operacionais(conn):

    query = """
    WITH ContagemReal AS (
        SELECT "UnidadeID","CargoID",COUNT(*) as "QtdReal"
        FROM "Colaboradores"
        WHERE "Ativo"=TRUE
        GROUP BY "UnidadeID","CargoID"
    )
    SELECT 
        t."NomeTipo" AS "Tipo",
        u."UnidadeID",
        u."NomeUnidade" AS "Escola",
        u."DataConferencia",
        s."NomeSupervisor" AS "Supervisor",
        c."NomeCargo" AS "Cargo",
        q."Quantidade" AS "Edital",
        COALESCE(cr."QtdReal",0) AS "Real"
    FROM "QuadroEdital" q
    JOIN "Unidades" u ON q."UnidadeID"=u."UnidadeID"
    JOIN "Cargos" c ON q."CargoID"=c."CargoID"
    JOIN "TiposUnidades" t ON u."TipoID"=t."TipoID"
    JOIN "Supervisores" s ON u."SupervisorID"=s."SupervisorID"
    LEFT JOIN ContagemReal cr
      ON q."UnidadeID"=cr."UnidadeID" AND q."CargoID"=cr."CargoID"
    ORDER BY u."NomeUnidade", c."NomeCargo";
    """

    pessoas = """
    SELECT u."NomeUnidade" AS "Escola",
           c."NomeCargo" AS "Cargo",
           col."Nome" AS "Funcionario",
           col."ColaboradorID" AS "ID"
    FROM "Colaboradores" col
    JOIN "Unidades" u ON col."UnidadeID"=u."UnidadeID"
    JOIN "Cargos" c ON col."CargoID"=c."CargoID"
    WHERE col."Ativo"=TRUE
    ORDER BY u."NomeUnidade", c."NomeCargo", col."Nome";
    """

    df = conn.query(query)
    df_pessoas = conn.query(pessoas)

    df['Diferenca_num'] = df['Real'] - df['Edital']
    df['Status_Codigo'] = np.where(df['Diferenca_num'] < 0, 'FALTA',
                           np.where(df['Diferenca_num'] > 0, 'EXCEDENTE', 'OK'))

    df['Status_Display'] = np.select(
        [df['Status_Codigo']=='FALTA', df['Status_Codigo']=='EXCEDENTE'],
        ['🔴 FALTA','🔵 EXCEDENTE'], default='🟢 OK'
    )

    df['Diferenca_Display'] = np.where(
        df['Diferenca_num'] > 0,
        "+" + df['Diferenca_num'].astype(str),
        df['Diferenca_num'].astype(str)
    )

    df['Edital_num'] = df['Edital'].astype(int)
    df['Real_num'] = df['Real'].astype(int)
    df['DataConferencia'] = pd.to_datetime(df['DataConferencia'])

    return df, df_pessoas

@st.cache_data(ttl=600)
def resumo_por_escola(df):
    agg = df.groupby('Escola').agg({
        'Edital_num':'sum',
        'Real_num':'sum',
        'Status_Codigo':list
    }).reset_index()

    agg['Saldo'] = agg['Real_num'] - agg['Edital_num']

    cond = [
        agg['Saldo'] > 0,
        agg['Saldo'] < 0,
        (agg['Saldo']==0) & agg['Status_Codigo'].apply(lambda x: any(s!='OK' for s in x))
    ]

    agg['Status_Calculado'] = np.select(
        cond, ["🔵 EXCEDENTE","🔴 FALTA","🟡 AJUSTE"], default="🟢 OK"
    )
    return agg

# =============================
# Helpers
# =============================

def estilo_linha(row):
    styles = ['text-align: center;'] * len(row)
    val = str(row.iloc[3])
    if '-' in val: styles[3] += 'color:#ff4b4b;font-weight:bold;'
    elif '+' in val: styles[3] += 'color:#29b6f6;font-weight:bold;'
    else: styles[3] += 'color:#00c853;font-weight:bold;'

    stt = str(row.iloc[4])
    if '🔴' in stt: styles[4] += 'color:#ff4b4b;font-weight:bold;'
    elif '🔵' in stt: styles[4] += 'color:#29b6f6;font-weight:bold;'
    else: styles[4] += 'color:#00c853;font-weight:bold;'
    return styles

def limpar_cache():
    buscar_dados_operacionais.clear()
    buscar_dados_auxiliares.clear()
    resumo_por_escola.clear()

# =============================
# Ações
# =============================

def acao_atualizar_data(uid, data, conn):
    with conn.session as session:
        session.execute(
            text("""UPDATE "Unidades"
                    SET "DataConferencia"=:data
                    WHERE "UnidadeID"=:id"""),
            {"data": data, "id": uid}
        )
        session.commit()
    limpar_cache()
    st.toast("Data salva!", icon="✅")
    st.rerun()

# =============================
# Sidebar
# =============================

def exibir_sidebar(authenticator, nome):
    with st.sidebar:
        if logo := carregar_logo():
            st.image(logo, use_container_width=True)
        st.write(f"👤 **{nome}**")
        authenticator.logout(location='sidebar')
        st.divider()
        st.info("Painel Gerencial + Detalhe")

# =============================
# Main
# =============================

def main():
    configurar_pagina()
    authenticator, nome = realizar_login()
    if not authenticator:
        return

    exibir_sidebar(authenticator, nome)
    conn = get_conn()

    df, df_pessoas = buscar_dados_operacionais(conn)

    st.title("📊 Mesa Operacional")

    total_edital = df['Edital_num'].sum()
    total_real = df['Real_num'].sum()

    c1,c2,c3 = st.columns(3)
    c1.metric("📋 Total Edital", total_edital)
    c2.metric("👥 Efetivo Atual", total_real)
    c3.metric("⚖️ Saldo Geral", total_real-total_edital)

    st.markdown("---")
    st.subheader("🏫 Detalhe por Escola")

    escolas = ["Todas"] + sorted(df['Escola'].unique().tolist())
    supervisores = ["Todos"] + sorted(df['Supervisor'].unique().tolist())

    f1,f2,f3,f4 = st.columns([1.2,1.2,1,1])
    with f1: filtro_escola = st.selectbox("🔍 Escola:", escolas)
    with f2: filtro_sup = st.selectbox("👔 Supervisor:", supervisores)
    with f3: filtro_sit = st.selectbox("🚦 Situação:", ["Todas","🔴 FALTA","🔵 EXCEDENTE","🟡 AJUSTE","🟢 OK"])
    with f4: termo = st.text_input("👤 Buscar Colaborador:", "")

    mask = pd.Series(True, index=df.index)
    if filtro_escola!="Todas": mask &= df['Escola']==filtro_escola
    if filtro_sup!="Todos": mask &= df['Supervisor']==filtro_sup

    if filtro_sit!="Todas":
        agg = resumo_por_escola(df)
        escolas_ok = agg[agg['Status_Calculado']==filtro_sit]['Escola']
        mask &= df['Escola'].isin(set(escolas_ok))

    if termo:
        esc = df_pessoas[
            df_pessoas['Funcionario'].str.contains(termo, case=False, na=False) |
            df_pessoas['ID'].astype(str).str.contains(termo)
        ]['Escola'].unique()
        mask &= df['Escola'].isin(set(esc))

    df_final = df[mask]
    st.info(f"**Encontradas {df_final['Escola'].nunique()} escolas.**")

    for escola, dfe in df_final.groupby('Escola'):
        saldo = dfe['Real_num'].sum() - dfe['Edital_num'].sum()
        icone = "🔵" if saldo>0 else "🔴" if saldo<0 else "🟢"

        with st.expander(f"{icone} {escola}", expanded=False):
            df_tab = dfe[['Cargo','Edital','Real','Diferenca_Display','Status_Display']]
            df_tab.columns = ['Cargo','Edital','Real','Diferenca','Status']
            st.dataframe(df_tab.style.apply(estilo_linha, axis=1),
                         use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
