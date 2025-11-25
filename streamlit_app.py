import streamlit as st 
import streamlit_authenticator as stauth
import pandas as pd
import plotly.express as px
from PIL import Image

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Mesa Operacional", layout="wide", page_icon="📊")

# --- CSS PERSONALIZADO ---
st.markdown("""
<style>
    .block-container { padding-top: 1rem; }
    .stButton button { background-color: #ff4b4b; color: white; border-radius: 8px; }
    [data-testid="stMetricValue"] { font-size: 32px; font-weight: bold; }
    .dataframe { font-size: 14px !important; }
    
    /* Centralização Geral de Tabelas */
    th, td { text-align: center !important; }
    .stDataFrame div[data-testid="stDataFrame"] div[role="grid"] div[role="row"] div {
        justify-content: center !important;
        text-align: center !important;
    }

    /* --- CORREÇÃO DO LOGO (Mínimo de Código) --- */
    /* Isso centraliza qualquer imagem dentro da coluna */
    [data-testid="stImage"] {
        display: flex;
        justify-content: center;
    }
</style>
""", unsafe_allow_html=True)

def carregar_logo():
    try: return Image.open("logo.png")
    except: return None

# --- AUTH CONFIG ---
try:
    auth_secrets = st.secrets["auth"]
    config = {
        'credentials': {
            'usernames': {
                auth_secrets["username"]: {
                    'name': auth_secrets["name"],
                    'password': auth_secrets["password_hash"],
                    'email': auth_secrets["email"]
                }
            }
        },
        'cookie': {
            'name': auth_secrets["cookie_name"],
            'key': auth_secrets["cookie_key"],
            'expiry_days': auth_secrets["cookie_expiry_days"]
        }
    }
except:
    st.error("Configure o arquivo .streamlit/secrets.toml")
    st.stop()

authenticator = stauth.Authenticate(
    config['credentials'],
    config['cookie']['name'],
    config['cookie']['key'],
    config['cookie']['expiry_days']
)

# --- LOGIN ---
if not st.session_state.get("authentication_status"):
    col_esq, col_centro, col_dir = st.columns([1, 1.5, 1])
    with col_centro:
        if logo := carregar_logo(): 
            # AQUI: Mudei para width=200 (menor) e o CSS acima centraliza
            st.image(logo, width=200) 
        try: authenticator.login(location='main')
        except: authenticator.login()
    
    if st.session_state.get("authentication_status") is False:
        with col_centro: st.error('Usuário ou senha incorretos')

# --- SISTEMA PRINCIPAL ---
if st.session_state.get("authentication_status"):
    name = st.session_state.get("name")
    
    # --- SIDEBAR ---
    with st.sidebar:
        if logo := carregar_logo(): st.image(logo, use_container_width=True); st.divider()
        st.write(f"👤 **{name}**")
        authenticator.logout(location='sidebar')
        st.divider()
        st.info("Painel Gerencial + Detalhe")

    try:
        # --- CONEXÃO INTELIGENTE (SQLAlchemy + Pooler) ---
        conn = st.connection("postgres", type="sql")

        # --- QUERIES ---
        query_resumo = """
        SELECT 
            t."NomeTipo" AS "Tipo",
            u."NomeUnidade" AS "Escola",
            s."NomeSupervisor" AS "Supervisor", 
            c."NomeCargo" AS "Cargo",
            q."Quantidade" AS "Edital",
            (SELECT COUNT(*) FROM "Colaboradores" col WHERE col."UnidadeID" = u."UnidadeID" AND col."CargoID" = c."CargoID" AND col."Ativo" = TRUE) AS "Real"
        FROM "QuadroEdital" q
        JOIN "Unidades" u ON q."UnidadeID" = u."UnidadeID"
        JOIN "Cargos" c ON q."CargoID" = c."CargoID"
        JOIN "TiposUnidades" t ON u."TipoID" = t."TipoID"
        JOIN "Supervisores" s ON u."SupervisorID" = s."SupervisorID"
        ORDER BY u."NomeUnidade", c."NomeCargo";
        """

        query_funcionarios = """
        SELECT 
            u."NomeUnidade" AS "Escola",
            c."NomeCargo" AS "Cargo",
            col."Nome" AS "Funcionario",
            col."ColaboradorID" AS "ID"
        FROM "Colaboradores" col
        JOIN "Unidades" u ON col."UnidadeID" = u."UnidadeID"
        JOIN "Cargos" c ON col."CargoID" = c."CargoID"
        WHERE col."Ativo" = TRUE
        ORDER BY u."NomeUnidade", c."NomeCargo", col."Nome";
        """

        # Executa as queries
        with st.spinner("Consultando o efetivo..."):
            df_resumo = conn.query(query_resumo, ttl=0)
            df_pessoas = conn.query(query_funcionarios, ttl=0)

        # --- PROCESSAMENTO PYTHON ---
        df_resumo['Diferenca_num'] = df_resumo['Real'] - df_resumo['Edital']
        df_resumo['Diferenca_display'] = df_resumo['Diferenca_num'].apply(lambda x: f"+{x}" if x > 0 else str(int(x)))

        def define_status(row):
            diff = row['Diferenca_num']
            if diff < 0: return '🔴 FALTA'
            elif diff > 0: return '🔵 EXCEDENTE'
            return '🟢 OK'
        
        df_resumo['Status_display'] = df_resumo.apply(define_status, axis=1)
        df_resumo['Status'] = df_resumo['Status_display'].apply(lambda x: x.split(' ')[1])

        # === DASHBOARD GERAL ===
        st.title("📊 Mesa Operacional")
        
        total_edital = df_resumo['Edital'].sum()
        total_real = df_resumo['Real'].sum()
        saldo_geral = int(total_real - total_edital)

        c1, c2, c3 = st.columns(3)
        with c1: st.markdown("**<div style='font-size:18px'>📋 Total Edital</div>**", unsafe_allow_html=True); st.metric("", int(total_edital))
        with c2: st.markdown("**<div style='font-size:18px'>👥 Efetivo Atual</div>**", unsafe_allow_html=True); st.metric("", int(total_real))
        with c3: st.markdown("**<div style='font-size:18px'>⚖️ Saldo Geral</div>**", unsafe_allow_html=True); st.metric("", saldo_geral)

        st.markdown("---")

        # === RESUMO ===
        with st.expander("📈 Ver Gráficos e Resumo Geral", expanded=True):
            df_por_cargo = df_resumo.groupby('Cargo')[['Edital','Real']].sum().reset_index()
            df_por_cargo['Diferenca_num'] = df_por_cargo['Real'] - df_por_cargo['Edital']
            df_por_cargo['Diferenca_display'] = df_por_cargo['Diferenca_num'].apply(lambda x: f"+{x}" if x > 0 else str(x))

            col_g1, col_g2 = st.columns([2,1])
            with col_g1:
                df_melt = df_por_cargo.melt(id_vars=['Cargo'], value_vars=['Edital','Real'], var_name='Tipo', value_name='Quantidade')
                fig = px.bar(df_melt, x='Cargo', y='Quantidade', color='Tipo', barmode='group',
                             color_discrete_map={'Edital': '#808080','Real': '#00bfff'}, text_auto=True, template="seaborn")
                st.plotly_chart(fig, use_container_width=True)
            
            with col_g2:
                display_df = df_por_cargo[['Cargo','Edital','Real','Diferenca_display']].rename(columns={'Diferenca_display':'Diferenca'})
                display_df[['Edital','Real']] = display_df[['Edital','Real']].astype(str)

                def style_table(row):
                    styles = ['text-align: center;'] * 4
                    val = str(row['Diferenca'])
                    base = 'text-align: center; font-weight: bold;'
                    if '-' in val: styles[3] = base + 'color: #ff4b4b;' 
                    elif '+' in val: styles[3] = base + 'color: #29b6f6;' 
                    else: styles[3] = base + 'color: #00c853;' 
                    return styles
                
                st.dataframe(display_df.style.apply(style_table, axis=1), use_container_width=True, hide_index=True)

        st.markdown("---")
        st.subheader("🏫 Detalhe por Escola")

        # --- FILTROS ---
        c_diag1, c_diag2 = st.columns(2)
        with c_diag1: filtro_escola = st.selectbox("🔍 Filtrar por Escola:", ["Todas"] + sorted(list(df_resumo['Escola'].unique())))
        with c_diag2: termo_busca = st.text_input("👤 Buscar Colaborador (Nome ou ID):", "")

        col_cargos = list(df_resumo['Cargo'].unique())
        filtro_comb = {}
        cols = st.columns(5)
        for i, cargo in enumerate(col_cargos):
            with cols[i % 5]:
                if (sel := st.selectbox(cargo, ["Todos","FALTA","EXCEDENTE","OK"], key=f'f_{i}')) != "Todos": filtro_comb[cargo] = sel

        st.markdown("---")

        # === APLICAÇÃO DOS FILTROS ===
        mask = pd.Series([True] * len(df_resumo))
        if filtro_escola != "Todas": mask &= (df_resumo['Escola'] == filtro_escola)
        
        if filtro_comb:
            escolas_validas = []
            for escola in df_resumo['Escola'].unique():
                df_e = df_resumo[df_resumo['Escola'] == escola]
                valid = True
                for c, s in filtro_comb.items():
                    row = df_e[df_e['Cargo'] == c]
                    if row.empty or row['Status'].iloc[0] != s:
                        valid = False; break
                if valid: escolas_validas.append(escola)
            mask &= df_resumo['Escola'].isin(escolas_validas)
        
        if termo_busca:
            match = df_pessoas[df_pessoas['Funcionario'].astype(str).str.contains(termo_busca, case=False) | 
                               df_pessoas['ID'].astype(str).str.contains(termo_busca)]['Escola'].unique()
            mask &= df_resumo['Escola'].isin(match)

        df_final = df_resumo[mask]
        st.info(f"**Encontradas {df_final['Escola'].nunique()} escolas.**")

        # === LOOP DE ESCOLAS ===
        for escola in df_final['Escola'].unique():
            df_e = df_final[df_final['Escola'] == escola].copy()
            status_list = df_e['Status'].tolist()
            
            icon = "🏫"
            if "FALTA" in status_list: icon = "🔴"
            elif "EXCEDENTE" in status_list: icon = "🔵"
            elif "OK" in status_list and len(set(status_list)) == 1: icon = "✅"

            with st.expander(f"{icon} {escola}", expanded=False):
                st.markdown("#### 📊 Quadro de Vagas")
                d_show = df_e[['Cargo','Edital','Real','Diferenca_display','Status_display']].rename(columns={'Diferenca_display':'Diferenca','Status_display':'Status'})
                d_show[['Edital','Real']] = d_show[['Edital','Real']].astype(str)

                def style_escola(row):
                    styles = ['text-align: center;'] * 5
                    val = str(row['Diferenca'])
                    base = 'text-align: center; font-weight: bold;'
                    if '-' in val: styles[3] = base + 'color: #ff4b4b;'
                    elif '+' in val: styles[3] = base + 'color: #29b6f6;'
                    else: styles[3] = base + 'color: #00c853;'
                    
                    stt = str(row['Status'])
                    if '🔴' in stt: styles[4] = base + 'color: #ff4b4b;'
                    elif '🔵' in stt: styles[4] = base + 'color: #29b6f6;'
                    else: styles[4] = base + 'color: #00c853;'
                    return styles

                st.dataframe(d_show.style.apply(style_escola, axis=1), use_container_width=True, hide_index=True)

                st.markdown("#### 📋 Colaboradores")
                p_show = df_pessoas[df_pessoas['Escola'] == escola]
                if termo_busca:
                    p_show = p_show[p_show['Funcionario'].astype(str).str.contains(termo_busca, case=False) | 
                                    p_show['ID'].astype(str).str.contains(termo_busca)]
                
                if not p_show.empty:
                    st.dataframe(p_show[['ID','Funcionario','Cargo']], use_container_width=True, hide_index=True)
                else:
                    st.warning("Nenhum colaborador encontrado.")

    except Exception as e:
        st.error(f"Erro de conexão ou dados: {e}")