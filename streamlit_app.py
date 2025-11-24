import streamlit as st
import streamlit_authenticator as stauth
import pandas as pd
import plotly.express as px
from PIL import Image
import psycopg2

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Mesa Operacional", layout="wide", page_icon="📊")

# --- CSS PERSONALIZADO ---
st.markdown("""
<style>
    .block-container { padding-top: 1rem; }
    .stButton button { background-color: #ff4b4b; color: white; border-radius: 8px; }
    [data-testid="stMetricValue"] { font-size: 32px; font-weight: bold; }
    .dataframe { font-size: 14px !important; }
    th, td { text-align: center !important; }
    .stDataFrame div[data-testid="stDataFrame"] div[role="grid"] div[role="row"] div {
        justify-content: center !important;
        text-align: center !important;
    }
</style>
""", unsafe_allow_html=True)

# --- FUNÇÃO PARA CARREGAR LOGO ---
def carregar_logo():
    try:
        return Image.open("logo.png")
    except:
        return None

# --- CONFIGURAÇÃO DE AUTENTICAÇÃO ---
auth_config = st.secrets["auth"]

config = {
    'credentials': {
        'usernames': {
            auth_config["username"]: {
                'name': auth_config["name"],
                'password': auth_config["password_hash"],
                'email': auth_config["email"]
            }
        }
    },
    'cookie': {
        'name': auth_config["cookie_name"],
        'key': auth_config["cookie_key"],
        'expiry_days': auth_config["cookie_expiry_days"]
    }
}

authenticator = stauth.Authenticate(
    config['credentials'],
    config['cookie']['name'],
    config['cookie']['key'],
    config['cookie']['expiry_days']
)

# --- TELA DE LOGIN ---
if st.session_state.get("authentication_status") is None or st.session_state.get("authentication_status") is False:
    col_esq, col_centro, col_dir = st.columns([1, 1.5, 1])
    with col_centro:
        logo = carregar_logo()
        if logo:
            c1, c2, c3 = st.columns([1,2,1])
            with c2:
                st.image(logo, use_container_width=True)
        try:
            authenticator.login(location='main')
        except:
            authenticator.login()
    
    if st.session_state.get("authentication_status") is False:
        with col_centro:
            st.error('Usuário ou senha incorretos')

# --- SISTEMA PRINCIPAL (PÓS-LOGIN) ---
if st.session_state.get("authentication_status") is True:
    name = st.session_state.get("name")
    
    # --- SIDEBAR ---
    with st.sidebar:
        logo = carregar_logo()
        if logo:
            st.image(logo, use_container_width=True)
            st.divider()
        st.write(f"👤 **{name}**")
        authenticator.logout(location='sidebar')
        st.divider()
        st.info("Painel Gerencial + Detalhe")

    # --- CONEXÃO COM POSTGRES / SUPABASE ---
    db = st.secrets["postgres"]
    conn = psycopg2.connect(
        host=db["host"],
        port=db["port"],
        dbname=db["dbname"],
        user=db["user"],
        password=db["password"],
        sslmode=db["sslmode"]
    )

    # --- CONSULTAS ---
    query_resumo = """
        SELECT 
            t.NomeTipo AS Tipo,
            u.NomeUnidade AS Escola,
            s.NomeSupervisor AS Supervisor, 
            c.NomeCargo AS Cargo,
            q.Quantidade AS Edital,
            (SELECT COUNT(*) FROM Colaboradores col WHERE col.UnidadeID = u.UnidadeID AND col.CargoID = c.CargoID AND col.Ativo = 1) AS Real,
            ((SELECT COUNT(*) FROM Colaboradores col WHERE col.UnidadeID = u.UnidadeID AND col.CargoID = c.CargoID AND col.Ativo = 1) - q.Quantidade) AS Diferenca,
            CASE 
                WHEN ((SELECT COUNT(*) FROM Colaboradores col WHERE col.UnidadeID = u.UnidadeID AND col.CargoID = c.CargoID AND col.Ativo = 1) - q.Quantidade) < 0 THEN 'FALTA'
                WHEN ((SELECT COUNT(*) FROM Colaboradores col WHERE col.UnidadeID = u.UnidadeID AND col.CargoID = c.CargoID AND col.Ativo = 1) - q.Quantidade) > 0 THEN 'EXCEDENTE'
                ELSE 'OK'
            END AS Status
        FROM QuadroEdital q
        JOIN Unidades u ON q.UnidadeID = u.UnidadeID
        JOIN Cargos c ON q.CargoID = c.CargoID
        JOIN TiposUnidades t ON u.TipoID = t.TipoID
        JOIN Supervisores s ON u.SupervisorID = s.SupervisorID
        ORDER BY u.NomeUnidade, c.NomeCargo;
    """

    query_funcionarios = """
        SELECT 
            u.NomeUnidade AS Escola,
            c.NomeCargo AS Cargo,
            col.Nome AS Funcionario,
            col.ColaboradorID AS ID
        FROM Colaboradores col
        JOIN Unidades u ON col.UnidadeID = u.UnidadeID
        JOIN Cargos c ON col.CargoID = c.CargoID
        WHERE col.Ativo = 1
        ORDER BY u.NomeUnidade, c.NomeCargo, col.Nome;
    """

    df_resumo = pd.read_sql(query_resumo, conn)
    df_pessoas = pd.read_sql(query_funcionarios, conn)
    conn.close()

    # --- PRÉ-PROCESSAMENTO ---
    df_resumo['Diferenca_num'] = pd.to_numeric(df_resumo.get('Diferenca', 0), errors='coerce').fillna(0).astype(int)
    df_resumo['Diferenca_display'] = df_resumo['Diferenca_num'].apply(lambda x: f"+{x}" if x > 0 else str(int(x)))

    def status_with_emoji(s):
        if s == 'FALTA': return '🔴 FALTA'
        elif s == 'EXCEDENTE': return '🔵 EXCEDENTE'
        elif s == 'OK': return '🟢 OK'
        return s
    
    df_resumo['Status_display'] = df_resumo['Status'].apply(status_with_emoji)

    # --- DASHBOARD ---
    st.title("📊 Mesa Operacional")
    total_edital = df_resumo['Edital'].sum()
    total_real = df_resumo['Real'].sum()
    saldo_geral = int(total_real - total_edital)

    col_m1, col_m2, col_m3 = st.columns(3)
    col_m1.metric("📋 Total Edital", total_edital)
    col_m2.metric("👥 Efetivo Atual", total_real)
    col_m3.metric("⚖️ Saldo Geral", saldo_geral, delta_color="normal")

    st.markdown("---")

    # --- FILTROS POR ESCOLA, CARGO E FUNCIONÁRIO ---
    st.subheader("🔍 Filtros")
    escolas = ["Todas"] + sorted(df_resumo['Escola'].unique().tolist())
    cargos = ["Todos"] + sorted(df_resumo['Cargo'].unique().tolist())
    funcionarios = ["Todos"] + sorted(df_pessoas['Funcionario'].unique().tolist())

    escola_selec = st.selectbox("Escola", escolas)
    cargo_selec = st.selectbox("Cargo", cargos)
    funcionario_selec = st.selectbox("Funcionário", funcionarios)

    df_filtrado = df_resumo.copy()

    if escola_selec != "Todas":
        df_filtrado = df_filtrado[df_filtrado['Escola'] == escola_selec]
    if cargo_selec != "Todos":
        df_filtrado = df_filtrado[df_filtrado['Cargo'] == cargo_selec]

    st.markdown("---")
    st.subheader("📈 Gráficos e Resumo Filtrado")
    
    df_por_cargo = df_filtrado.groupby('Cargo')[['Edital','Real']].sum().reset_index()
    df_por_cargo['Diferenca_num'] = df_por_cargo['Real'] - df_por_cargo['Edital']
    df_por_cargo['Diferenca_display'] = df_por_cargo['Diferenca_num'].apply(lambda x: f"+{x}" if x > 0 else str(x))
    
    col_g1, col_g2 = st.columns([2,1])
    with col_g1:
        df_grafico = df_por_cargo.melt(id_vars=['Cargo'], value_vars=['Edital','Real'], var_name='Tipo', value_name='Quantidade')
        fig = px.bar(df_grafico, x='Cargo', y='Quantidade', color='Tipo', barmode='group',
                     color_discrete_map={'Edital': '#808080','Real': '#00bfff'}, text_auto=True, template="seaborn")
        st.plotly_chart(fig, use_container_width=True)

    with col_g2:
        display_df_geral = df_por_cargo[['Cargo','Edital','Real','Diferenca_display']].rename(columns={'Diferenca_display':'Diferenca'})
        display_df_geral['Edital'] = display_df_geral['Edital'].astype(str)
        display_df_geral['Real'] = display_df_geral['Real'].astype(str)
        st.dataframe(display_df_geral, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("🏫 Detalhe por Escola / Cargo / Funcionário")
    df_detalhe = df_pessoas.copy()
    if escola_selec != "Todas":
        df_detalhe = df_detalhe[df_detalhe['Escola'] == escola_selec]
    if cargo_selec != "Todos":
        df_detalhe = df_detalhe[df_detalhe['Cargo'] == cargo_selec]
    if funcionario_selec != "Todos":
        df_detalhe = df_detalhe[df_detalhe['Funcionario'] == funcionario_selec]

    st.dataframe(df_detalhe[['Escola','Cargo','Funcionario','ID']], use_container_width=True, hide_index=True)
