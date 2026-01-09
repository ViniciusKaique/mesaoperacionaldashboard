import streamlit as st
import pandas as pd
import plotly.express as px
from sqlalchemy import text
import numpy as np
from PIL import Image
import streamlit_authenticator as stauth

# ==============================================================================
# CONFIGURAÇÃO E ESTILOS
# ==============================================================================
st.set_page_config(page_title="Gestão Araraquara", layout="wide", page_icon="🏥")

st.markdown("""
<style>
    .block-container { padding-top: 1rem; }
    [data-testid="stMetricValue"] { font-size: 26px; font-weight: bold; }
    .stDataFrame { font-size: 14px; }
    
    th, td { text-align: center !important; }
    .stDataFrame div[data-testid="stDataFrame"] div[role="grid"] div[role="row"] div {
        justify-content: center !important;
        text-align: center !important;
    }
    
    div.stButton > button { width: 100%; display: block; margin: 0 auto; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# FUNÇÕES DE UI E AUTENTICAÇÃO
# ==============================================================================

def carregar_logo():
    try: return Image.open("logo.png")
    except: return None

def realizar_login():
    try:
        auth_secrets = st.secrets["auth"]
        config = {
            'credentials': {'usernames': {auth_secrets["username"]: {'name': auth_secrets["name"], 'password': auth_secrets["password_hash"], 'email': auth_secrets["email"]}}},
            'cookie': {'name': auth_secrets["cookie_name"], 'key': auth_secrets["cookie_key"], 'expiry_days': auth_secrets["cookie_expiry_days"]}
        }
        authenticator = stauth.Authenticate(
            config['credentials'], 
            config['cookie']['name'], 
            config['cookie']['key'], 
            config['cookie']['expiry_days']
        )
        
        if not st.session_state.get("authentication_status"):
            st.write(""); st.write(""); st.write(""); st.write(""); st.write("")
            col_esq, col_centro, col_dir = st.columns([3, 2, 3])
            with col_centro:
                authenticator.login()
            if st.session_state.get("authentication_status") is False:
                with col_centro: st.error('Usuário ou senha incorretos')
            return None, None
            
        return authenticator, st.session_state.get("name")
    except Exception as e:
        st.error(f"Erro de Autenticação: {e}")
        st.stop()

def exibir_sidebar(authenticator, nome_usuario):
    with st.sidebar:
        if logo := carregar_logo(): 
            st.image(logo, use_container_width=True)
            st.divider()
        
        st.write(f"👤 **{nome_usuario}**")
        authenticator.logout('Logout', location='sidebar')
        st.divider()
        st.info("Painel Araraquara")

def exibir_metricas_setor(df_chart):
    if df_chart.empty:
        return

    total_edital = int(df_chart[df_chart['Tipo_Dado'] == 'Edital']['Qtd'].sum())
    total_real = int(df_chart[df_chart['Tipo_Dado'] == 'Real']['Qtd'].sum())
    saldo = total_real - total_edital
    
    c1, c2, c3 = st.columns(3)
    
    with c1: 
        st.markdown("**<div style='font-size:18px'>📋 Total Edital</div>**", unsafe_allow_html=True)
        st.metric("", total_edital)
    with c2: 
        st.markdown("**<div style='font-size:18px'>👥 Efetivo Atual</div>**", unsafe_allow_html=True)
        st.metric("", total_real)
    with c3: 
        st.markdown("**<div style='font-size:18px'>⚖️ Saldo</div>**", unsafe_allow_html=True)
        st.metric("", saldo)
    
    st.markdown("<br>", unsafe_allow_html=True)

# ==============================================================================
# 1. BUSCA DE DADOS
# ==============================================================================

@st.cache_data(ttl=300)
def buscar_dados_completos(_conn):
    query_real = """
    SELECT "ColaboradorID", "Nome", "Contrato", "Cargo", "RecebeInsalubridade", "Escala"
    FROM "AraraquaraColaboradores"
    WHERE "Contrato" IN ('SAUDE', 'EDUCACAO')
    """
    query_edital_edu = 'SELECT "Edital" as "Qtd", "Insalubridade" FROM "EditalEducação"'
    query_edital_saude = 'SELECT "Tipo", "Edital" as "Qtd", "Insalubridade" FROM "EditalSaúde"'
    
    try:
        df_real = _conn.query(query_real)
        df_real['Escala'] = df_real['Escala'].fillna('-').str.upper().str.strip()
        df_real['Contrato'] = df_real['Contrato'].str.upper().str.strip()
        
        try:
            df_meta_edu = _conn.query(query_edital_edu)
            df_meta_saude = _conn.query(query_edital_saude)
            df_meta_saude['Tipo'] = df_meta_saude['Tipo'].str.upper().str.strip()
        except Exception as e:
            st.error(f"Erro tabelas Edital: {e}")
            df_meta_edu = pd.DataFrame(); df_meta_saude = pd.DataFrame()

        return df_real, df_meta_edu, df_meta_saude
    except Exception as e:
        st.error(f"Erro conexão: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

# ==============================================================================
# 2. PROCESSAMENTO
# ==============================================================================

def processar_educacao(df_real, df_meta):
    meta_agg = df_meta.groupby('Insalubridade')['Qtd'].sum().reset_index()
    meta_agg['Categoria'] = meta_agg['Insalubridade'].apply(lambda x: f"Insalubridade {int(x)}%")
    meta_agg['Tipo_Dado'] = 'Edital'
    meta_agg['Cor'] = '#808080'

    real_filter = df_real[df_real['Contrato'] == 'EDUCACAO'].copy()
    real_agg = real_filter.groupby('RecebeInsalubridade').size().reset_index(name='Qtd')
    real_agg['Categoria'] = real_agg['RecebeInsalubridade'].apply(lambda x: f"Insalubridade {int(x)}%")
    real_agg['Tipo_Dado'] = 'Real'
    real_agg['Cor'] = '#00bfff'

    return pd.concat([meta_agg[['Categoria', 'Tipo_Dado', 'Qtd', 'Cor']], real_agg[['Categoria', 'Tipo_Dado', 'Qtd', 'Cor']]])

def processar_saude(df_real, df_meta):
    real_filter = df_real[df_real['Contrato'] == 'SAUDE'].copy()
    def normalizar_escala_saude(row):
        esc = row['Escala']
        if 'NOTURNO' in esc: return 'NOTURNO 12 HORAS'
        elif '12X36' in esc and 'DIURNO' in esc: return 'DIURNO 12 HORAS'
        elif any(x in esc for x in ['5X2', '6X1', '8H', 'DIARISTA']): return 'DIURNO 8 HORAS'
        return 'OUTROS'
    real_filter['Tipo_Normalizado'] = real_filter.apply(normalizar_escala_saude, axis=1)
    
    real_agg = real_filter.groupby(['Tipo_Normalizado', 'RecebeInsalubridade']).size().reset_index(name='Qtd')
    real_agg['Chave'] = real_agg.apply(lambda x: f"{x['Tipo_Normalizado']} ({int(x['RecebeInsalubridade'])}%)", axis=1)
    real_agg['Tipo_Dado'] = 'Real'
    real_agg['Cor'] = '#00bfff'

    meta_agg = df_meta.groupby(['Tipo', 'Insalubridade'])['Qtd'].sum().reset_index()
    meta_agg['Chave'] = meta_agg.apply(lambda x: f"{x['Tipo']} ({int(x['Insalubridade'])}%)", axis=1)
    meta_agg['Tipo_Dado'] = 'Edital'
    meta_agg['Cor'] = '#808080'

    return pd.concat([meta_agg[['Chave', 'Tipo_Dado', 'Qtd', 'Cor']], real_agg[['Chave', 'Tipo_Dado', 'Qtd', 'Cor']]]).rename(columns={'Chave': 'Categoria'})

def gerar_tabela_comparativa(df_chart):
    if df_chart.empty: return pd.DataFrame()
    df_pivot = df_chart.pivot_table(index='Categoria', columns='Tipo_Dado', values='Qtd', aggfunc='sum').fillna(0)
    if 'Edital' not in df_pivot.columns: df_pivot['Edital'] = 0
    if 'Real' not in df_pivot.columns: df_pivot['Real'] = 0
    df_pivot = df_pivot.reset_index()
    df_pivot['Edital'] = df_pivot['Edital'].astype(int); df_pivot['Real'] = df_pivot['Real'].astype(int)
    df_pivot['Diferença'] = df_pivot['Real'] - df_pivot['Edital']
    df_pivot['Diff_Display'] = df_pivot['Diferença'].apply(lambda x: f"+{x}" if x > 0 else str(x))
    return df_pivot[['Categoria', 'Edital', 'Real', 'Diff_Display']]

def estilo_tabela_araraquara(row):
    styles = ['text-align: center;'] * 4
    val = str(row['Diff_Display'])
    if '-' in val: styles[3] += 'color: #ff4b4b; font-weight: bold;'
    elif '+' in val: styles[3] += 'color: #29b6f6; font-weight: bold;'
    else: styles[3] += 'color: #00c853; font-weight: bold;'
    return styles

# ==============================================================================
# MAIN APP
# ==============================================================================

def main():
    authenticator, nome_usuario = realizar_login()
    
    if authenticator:
        exibir_sidebar(authenticator, nome_usuario)

        # CABEÇALHO LIMPO E ALINHADO À ESQUERDA
        st.title("📊 Gestão Araraquara")
        # Removido: st.markdown(f"**Usuário:** ...")
        st.markdown("---")

        conn = st.connection("postgres", type="sql")
        df_real, df_meta_edu, df_meta_saude = buscar_dados_completos(conn)

        if df_real.empty: st.info("Nenhum colaborador encontrado."); st.stop()

        df_chart_edu = processar_educacao(df_real, df_meta_edu) if not df_meta_edu.empty else pd.DataFrame()
        df_chart_saude = processar_saude(df_real, df_meta_saude) if not df_meta_saude.empty else pd.DataFrame()

        # --- EDUCAÇÃO ---
        st.markdown("### 📚 Educação")
        exibir_metricas_setor(df_chart_edu)
        
        if not df_chart_edu.empty:
            df_chart_edu = df_chart_edu.sort_values('Categoria')
            df_table_edu = gerar_tabela_comparativa(df_chart_edu)
            
            c_plot, c_table = st.columns([1.5, 1])
            with c_plot:
                fig_edu = px.bar(df_chart_edu, x='Categoria', y='Qtd', color='Tipo_Dado', barmode='group', text_auto=True,
                    color_discrete_map={'Edital': '#808080', 'Real': '#00bfff'}, category_orders={"Tipo_Dado": ["Edital", "Real"]})
                fig_edu.update_layout(showlegend=True, xaxis_title=None, yaxis_title="Quantidade", legend_title_text="")
                st.plotly_chart(fig_edu, use_container_width=True)
            with c_table:
                st.write(""); st.dataframe(df_table_edu.style.apply(estilo_tabela_araraquara, axis=1), use_container_width=True, hide_index=True)
        else: st.warning("Sem dados de Educação.")
        
        st.markdown("---")

        # --- SAÚDE ---
        st.markdown("### 🏥 Saúde")
        exibir_metricas_setor(df_chart_saude)

        if not df_chart_saude.empty:
            df_chart_saude = df_chart_saude.sort_values('Categoria')
            df_table_saude = gerar_tabela_comparativa(df_chart_saude)
            
            c_plot, c_table = st.columns([1.5, 1])
            with c_plot:
                fig_saude = px.bar(df_chart_saude, x='Categoria', y='Qtd', color='Tipo_Dado', barmode='group', text_auto=True,
                    color_discrete_map={'Edital': '#808080', 'Real': '#00bfff'}, category_orders={"Tipo_Dado": ["Edital", "Real"]})
                fig_saude.update_layout(showlegend=True, xaxis_title=None, yaxis_title="Quantidade", legend_title_text="")
                st.plotly_chart(fig_saude, use_container_width=True)
            with c_table:
                st.write(""); st.dataframe(df_table_saude.style.apply(estilo_tabela_araraquara, axis=1), use_container_width=True, hide_index=True)
        else: st.warning("Sem dados de Saúde.")
        
        st.markdown("---")

        # --- DETALHE ---
        st.subheader("📋 Detalhe Nominal (Real)")
        with st.expander("🔎 Filtros", expanded=False):
            c1, c2, c3 = st.columns(3)
            f_contrato = c1.multiselect("Contrato:", df_real['Contrato'].unique())
            f_insal = c2.selectbox("Insalubridade:", ["Todas", "0%", "20%", "40%"])
            f_busca = c3.text_input("Buscar Nome/ID:")

        df_table = df_real.copy()
        if f_contrato: df_table = df_table[df_table['Contrato'].isin(f_contrato)]
        if f_insal != "Todas": val_insal = int(f_insal.replace('%','')); df_table = df_table[df_table['RecebeInsalubridade'] == val_insal]
        if f_busca: df_table = df_table[df_table['Nome'].str.contains(f_busca, case=False) | df_table['ColaboradorID'].astype(str).str.contains(f_busca)]

        st.dataframe(df_table[['ColaboradorID', 'Nome', 'Contrato', 'Cargo', 'Escala', 'RecebeInsalubridade']], use_container_width=True, hide_index=True, height=500,
            column_config={"ColaboradorID": st.column_config.NumberColumn("ID", format="%d"), "RecebeInsalubridade": st.column_config.ProgressColumn("Insalubridade %", format="%d%%", min_value=0, max_value=40)})

if __name__ == "__main__":
    main()