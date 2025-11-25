import streamlit as st 
import streamlit_authenticator as stauth
import pandas as pd
import plotly.express as px
import psycopg2 
import socket # <--- NOVA IMPORTAÇÃO NECESSÁRIA
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
    
    /* Força bruta para cabeçalhos e células */
    th, td { text-align: center !important; }
    .stDataFrame div[data-testid="stDataFrame"] div[role="grid"] div[role="row"] div {
        justify-content: center !important;
        text-align: center !important;
    }
</style>
""", unsafe_allow_html=True)

def carregar_logo():
    try:
        return Image.open("logo.png")
    except:
        return None

# --- AUTH CONFIG (VIA SECRETS) ---
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

# --- FUNÇÃO DE CONEXÃO AO POSTGRES (CORRIGIDA PARA IPv4) ---
@st.cache_resource
def init_connection():
    db_config = st.secrets["postgres"]
    
    # TRUQUE PARA CORRIGIR O ERRO "Cannot assign requested address" (IPv6)
    # Nós resolvemos o DNS manualmente para pegar o IP numérico (IPv4)
    try:
        ip_v4 = socket.gethostbyname(db_config["host"])
    except socket.gaierror:
        # Se falhar, tenta usar o host original
        ip_v4 = db_config["host"]

    return psycopg2.connect(
        host=db_config["host"],       # Mantém o domínio para validar o certificado SSL
        hostaddr=ip_v4,               # Força a conexão no IP v4 encontrado
        port=db_config["port"],
        user=db_config["user"],
        password=db_config["password"],
        dbname=db_config["dbname"],
        sslmode=db_config.get("sslmode", "require") 
    )

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

    try:
        conn = init_connection()

        # --- QUERIES ---
        query_resumo = """
        SELECT 
            t."NomeTipo" AS "Tipo",
            u."NomeUnidade" AS "Escola",
            s."NomeSupervisor" AS "Supervisor", 
            c."NomeCargo" AS "Cargo",
            q."Quantidade" AS "Edital",
            (SELECT COUNT(*) FROM "Colaboradores" col WHERE col."UnidadeID" = u."UnidadeID" AND col."CargoID" = c."CargoID" AND col."Ativo" = TRUE) AS "Real",
            ((SELECT COUNT(*) FROM "Colaboradores" col WHERE col."UnidadeID" = u."UnidadeID" AND col."CargoID" = c."CargoID" AND col."Ativo" = TRUE) - q."Quantidade") AS "Diferenca",
            CASE 
                WHEN ((SELECT COUNT(*) FROM "Colaboradores" col WHERE col."UnidadeID" = u."UnidadeID" AND col."CargoID" = c."CargoID" AND col."Ativo" = TRUE) - q."Quantidade") < 0 THEN 'FALTA'
                WHEN ((SELECT COUNT(*) FROM "Colaboradores" col WHERE col."UnidadeID" = u."UnidadeID" AND col."CargoID" = c."CargoID" AND col."Ativo" = TRUE) - q."Quantidade") > 0 THEN 'EXCEDENTE'
                ELSE 'OK'
            END AS "Status"
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

        df_resumo = pd.read_sql(query_resumo, conn)
        df_pessoas = pd.read_sql(query_funcionarios, conn)

        # --- PRÉ-PROCESSAMENTO ---
        if 'Diferenca' in df_resumo.columns:
            df_resumo['Diferenca_num'] = pd.to_numeric(df_resumo['Diferenca'], errors='coerce').fillna(0).astype(int)
        else:
            df_resumo['Diferenca_num'] = 0

        df_resumo['Diferenca_display'] = df_resumo['Diferenca_num'].apply(lambda x: f"+{x}" if x > 0 else str(int(x)))

        def status_with_emoji(s):
            if s == 'FALTA': return '🔴 FALTA'
            elif s == 'EXCEDENTE': return '🔵 EXCEDENTE'
            elif s == 'OK': return '🟢 OK'
            return s
        
        df_resumo['Status_display'] = df_resumo['Status'].apply(status_with_emoji)

        # === DASHBOARD GERAL ===
        st.title("📊 Mesa Operacional")
        
        total_edital = df_resumo['Edital'].sum() if 'Edital' in df_resumo.columns else 0
        total_real = df_resumo['Real'].sum() if 'Real' in df_resumo.columns else 0
        saldo_geral = int(total_real - total_edital)

        col_m1, col_m2, col_m3 = st.columns(3)
        with col_m1:
            st.markdown("**<div style='font-size: 18px; font-weight: 600;'>📋 Total Edital</div>**", unsafe_allow_html=True)
            st.metric("", total_edital)
        with col_m2:
            st.markdown("**<div style='font-size: 18px; font-weight: 600;'>👥 Efetivo Atual</div>**", unsafe_allow_html=True)
            st.metric("", total_real)
        with col_m3:
            st.markdown("**<div style='font-size: 18px; font-weight: 600;'>⚖️ Saldo Geral</div>**", unsafe_allow_html=True)
            st.metric("", saldo_geral, delta_color="normal")

        st.markdown("---")

        # === GRÁFICOS E RESUMO ===
        with st.expander("📈 Ver Gráficos e Resumo Geral", expanded=True):
            df_por_cargo = df_resumo.groupby('Cargo')[['Edital','Real']].sum().reset_index()
            df_por_cargo['Edital'] = df_por_cargo['Edital'].astype(int)
            df_por_cargo['Real'] = df_por_cargo['Real'].astype(int)
            
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

                def style_geral(row):
                    styles = ['text-align: center;'] * len(display_df_geral.columns)
                    idx_diff = display_df_geral.columns.get_loc('Diferenca')
                    val_str = str(row['Diferenca'])
                    base = 'text-align: center; font-weight: bold;'
                    if '-' in val_str: styles[idx_diff] = base + 'color: #ff4b4b;'
                    elif '+' in val_str: styles[idx_diff] = base + 'color: #29b6f6;'
                    else: styles[idx_diff] = base + 'color: #00c853;'
                    return styles
                
                styler_resumo = display_df_geral.style.apply(style_geral, axis=1)
                styler_resumo = styler_resumo.set_properties(**{'text-align': 'center'})
                styler_resumo = styler_resumo.set_table_styles([dict(selector='th', props=[('text-align', 'center')])])

                st.dataframe(styler_resumo, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.subheader("🏫 Detalhe por Escola")

        # --- FILTROS ---
        st.markdown("##### 🛠️ Filtro de Diagnóstico")
        col_diag1, col_diag2 = st.columns([1,1])
        with col_diag1:
            lista_escolas = ["Todas"] + sorted(list(df_resumo['Escola'].unique()))
            filtro_escola = st.selectbox("🔍 Filtrar por Escola:", lista_escolas, key='filtro_escola_principal')
        with col_diag2:
            termo_busca = st.text_input("👤 Buscar Colaborador (Nome ou ID):", "")

        col_cargos = list(df_resumo['Cargo'].unique())
        st.markdown("---")
        st.markdown("##### 🔍 Condições Múltiplas")
        filtro_combinacao = {}
        cols_filter = st.columns(5)
        for i, cargo in enumerate(col_cargos):
            with cols_filter[i % 5]:
                opcoes = ["Todos"] + ["FALTA","EXCEDENTE","OK"]
                selecao = st.selectbox(label=cargo, options=opcoes, key=f'cargo_filtro_{i}')
                if selecao != "Todos": filtro_combinacao[cargo] = selecao

        st.markdown("---")

        # === LÓGICA DE FILTRAGEM ===
        df_filtrado = df_resumo.copy()
        if filtro_escola != "Todas":
            df_filtrado = df_filtrado[df_filtrado['Escola'] == filtro_escola]

        escolas_para_mostrar = []
        todas_escolas_candidatas = df_filtrado['Escola'].unique()
        
        for escola in todas_escolas_candidatas:
            df_da_escola = df_resumo[df_resumo['Escola'] == escola]
            atende = True
            for cargo, status_desejado in filtro_combinacao.items():
                status_real_row = df_da_escola[df_da_escola['Cargo'] == cargo]['Status']
                if status_real_row.empty:
                    atende = False; break
                status_real = status_real_row.iloc[0]
                if status_real != status_desejado:
                    atende = False; break
            if atende: escolas_para_mostrar.append(escola)

        if termo_busca:
            mask_colab = df_pessoas['Funcionario'].astype(str).str.contains(termo_busca, case=False, na=False) | \
                         df_pessoas['ID'].astype(str).str.contains(termo_busca, case=False, na=False)
            escolas_com_match = df_pessoas[mask_colab]['Escola'].unique()
            escolas_para_mostrar = [e for e in escolas_para_mostrar if e in escolas_com_match]

        st.info(f"**Encontradas {len(escolas_para_mostrar)} escolas com os critérios selecionados.**")

        # === LOOP DE ESCOLAS ===
        for escola in escolas_para_mostrar:
            df_escola_resumo = df_resumo[df_resumo['Escola'] == escola].copy()
            df_escola_resumo['Diferenca_num'] = pd.to_numeric(df_escola_resumo.get('Diferenca_num', 0), errors='coerce').fillna(0).astype(int)
            df_escola_resumo['Diferenca_display'] = df_escola_resumo['Diferenca_num'].apply(lambda x: f"+{x}" if x > 0 else str(int(x)))

            try: tipo_escola = df_escola_resumo['Tipo'].iloc[0]
            except: tipo_escola = "UNIDADE"

            status_para_icone = df_escola_resumo['Status'].tolist()
            icon = "🏫"
            if "FALTA" in status_para_icone: icon = "🔴"
            elif "EXCEDENTE" in status_para_icone: icon = "🔵"
            elif "OK" in status_para_icone and len(set(status_para_icone)) == 1: icon = "✅"

            with st.expander(f"{icon} {tipo_escola} {escola}", expanded=False):
                st.markdown("#### 📊 Quadro de Vagas")
                display_df = df_escola_resumo[['Cargo','Edital','Real','Diferenca_display','Status_display']].rename(columns={'Diferenca_display':'Diferenca','Status_display':'Status'})
                display_df['Edital'] = display_df['Edital'].astype(str)
                display_df['Real'] = display_df['Real'].astype(str)

                def style_row(row):
                    styles = ['text-align: center;'] * len(display_df.columns)
                    idx_diff = display_df.columns.get_loc('Diferenca')
                    idx_status = display_df.columns.get_loc('Status')
                    try: num = int(str(row['Diferenca']).replace('+', ''))
                    except: num = 0
                    
                    diff_base = 'text-align: center; font-weight: bold;'
                    if num < 0: styles[idx_diff] = diff_base + ' color: #ff4b4b;'
                    elif num > 0: styles[idx_diff] = diff_base + ' color: #29b6f6;'
                    else: styles[idx_diff] = diff_base + ' color: #00c853;'

                    status_base = 'text-align: center;'
                    stt = str(row['Status'])
                    if '🔴' in stt: styles[idx_status] = status_base + ' color: #ff4b4b; font-weight:bold;'
                    elif '🔵' in stt: styles[idx_status] = status_base + ' color: #29b6f6; font-weight:bold;'
                    elif '🟢' in stt: styles[idx_status] = status_base + ' color: #00c853; font-weight:bold;'
                    else: styles[idx_status] = status_base
                    return styles

                styler = display_df.style.apply(style_row, axis=1)
                styler = styler.set_properties(**{'text-align': 'center'})
                styler = styler.set_table_styles([{'selector': 'th', 'props': [('text-align', 'center')]}])
                st.dataframe(styler, use_container_width=True, hide_index=True)

                st.markdown("#### 📋 Lista de Colaboradores")
                df_escola_pessoas = df_pessoas[df_pessoas['Escola'] == escola]
                if termo_busca:
                     mask_pessoa = df_escola_pessoas['Funcionario'].astype(str).str.contains(termo_busca, case=False, na=False) | \
                                   df_escola_pessoas['ID'].astype(str).str.contains(termo_busca, case=False, na=False)
                     df_escola_pessoas = df_escola_pessoas[mask_pessoa]

                if not df_escola_pessoas.empty:
                    st.dataframe(df_escola_pessoas[['ID','Funcionario','Cargo']], use_container_width=True, hide_index=True)
                else:
                    st.warning("Nenhum colaborador encontrado com este termo nesta unidade.")

    except Exception as e:
        st.error(f"Erro de conexão ou dados: {e}")