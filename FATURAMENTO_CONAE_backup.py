import streamlit as st
import pandas as pd
import altair as alt

# ==============================================================================
# CONFIGURAÇÃO DA PÁGINA
# ==============================================================================
st.set_page_config(page_title="Monitoramento de Contratos", layout="wide", page_icon="📈")

# ==============================================================================
# VERIFICAÇÃO DE SEGURANÇA (LOGIN)
# ==============================================================================
if not st.session_state.get("authentication_status"):
    st.warning("🔒 Acesso restrito. Por favor, faça login na página inicial.")
    st.stop()

# ==============================================================================
# INICIALIZAÇÃO DO ESTADO (SESSION STATE)
# ==============================================================================
if 'monit_df_dashboard' not in st.session_state:
    st.session_state['monit_df_dashboard'] = None

if 'monit_df_comp1' not in st.session_state:
    st.session_state['monit_df_comp1'] = None

if 'monit_df_comp2' not in st.session_state:
    st.session_state['monit_df_comp2'] = None

# ==============================================================================
# FUNÇÕES AUXILIARES
# ==============================================================================
@st.cache_data
def load_data(file):
    if file is None:
        return None
    
    try:
        df = pd.read_csv(file, sep=';')
    except:
        df = pd.read_csv(file, sep=',')
    
    numeric_cols = [
        'totalContrato', 'descontoContrato', 'liquidoContrato',
        'totalUnidade', 'glosaImrUnidade', 'glosaRhUnidade', 
        'liquidoUnidade', 'percentualImrUnidade', 'pontuacaoUnidade'
    ]
    
    for col in numeric_cols:
        if col in df.columns:
            df[col] = df[col].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            
    if 'glosaImrUnidade' in df.columns and 'glosaRhUnidade' in df.columns:
        df['Total Glosas'] = df['glosaImrUnidade'] + df['glosaRhUnidade']
    
    # Tratamento da coluna nomeFiscal para garantir consistência
    if 'nomeFiscal' in df.columns:
        df['nomeFiscal'] = df['nomeFiscal'].fillna('').astype(str).str.strip()

    return df

# ==============================================================================
# INTERFACE PRINCIPAL
# ==============================================================================

if "name" in st.session_state:
    st.sidebar.write(f"👤 **{st.session_state['name']}**")
    st.sidebar.divider()

st.sidebar.title("Menu Monitoramento")
page_mode = st.sidebar.radio("Selecione a Visão:", ["Dashboard Geral", "Comparador (Mês a Mês)"])

# ------------------------------------------------------------------------------
# VISÃO 1: DASHBOARD GERAL
# ------------------------------------------------------------------------------
if page_mode == "Dashboard Geral":
    st.title("📊 Dashboard: Monitoramento Mensal")
    
    uploaded_file = st.sidebar.file_uploader("Carregar Arquivo do Mês", type=['csv'])
    
    if uploaded_file is not None:
        st.session_state['monit_df_dashboard'] = load_data(uploaded_file)
    
    df = st.session_state['monit_df_dashboard']

    if df is not None:
        if uploaded_file is None:
            st.sidebar.success("📂 Dados da sessão anterior.")

        st.sidebar.header("Filtros")
        
        # Filtros
        df_filtered = df.copy()

        if 'ano' in df_filtered.columns:
            anos = sorted(df_filtered['ano'].unique())
            sel_ano = st.sidebar.selectbox("Ano", anos)
            df_filtered = df_filtered[df_filtered['ano'] == sel_ano]
        
        if 'mes' in df_filtered.columns:
            meses = sorted(df_filtered['mes'].unique())
            sel_mes = st.sidebar.multiselect("Mês", meses, default=meses)
            if sel_mes: df_filtered = df_filtered[df_filtered['mes'].isin(sel_mes)]
            
        if 'nomeLote' in df_filtered.columns:
            lotes = sorted(df_filtered['nomeLote'].unique())
            sel_lote = st.sidebar.multiselect("Lote", lotes, default=lotes)
            if sel_lote: df_filtered = df_filtered[df_filtered['nomeLote'].isin(sel_lote)]

        # --- NOVA MÉTRICA: AGUARDANDO FISCAL ---
        total_unidades = len(df_filtered)
        # Considera aguardando fiscal se for " - " (que virou "-" com o strip) ou vazio
        aguardando_fiscal = df_filtered[df_filtered['nomeFiscal'].isin(['-', '', 'nan'])].shape[0]
        
        st.markdown("### Indicadores Gerais")
        
        # Linha superior de métricas
        col1, col2, col3, col4, col5 = st.columns(5)
        
        col1.metric("Valor Total Medido", f"R$ {df_filtered['totalUnidade'].sum():,.2f}")
        col2.metric("Total Glosa IMR", f"R$ {df_filtered['glosaImrUnidade'].sum():,.2f}", delta_color="inverse")
        col3.metric("Total Glosa RH", f"R$ {df_filtered['glosaRhUnidade'].sum():,.2f}", delta_color="inverse")
        col4.metric("Pontuação Média", f"{df_filtered['pontuacaoUnidade'].mean():.2f}")
        
        # Nova métrica destacada
        col5.metric(
            "Aguardando Fiscal", 
            f"{aguardando_fiscal} / {total_unidades}",
            help="Unidades onde o nomeFiscal consta como ' - '"
        )
        
        st.divider()
        
        # Se houver pendências de fiscal, mostrar botão para ver detalhes
        if aguardando_fiscal > 0:
            with st.expander(f"⚠️ Ver Lista de {aguardando_fiscal} Unidades Aguardando Fiscal"):
                df_aguardando = df_filtered[df_filtered['nomeFiscal'].isin(['-', '', 'nan'])]
                st.dataframe(
                    df_aguardando[['nomeUnidadeEscolar', 'nomeLote', 'totalUnidade']], 
                    use_container_width=True,
                    hide_index=True
                )

        # Gráficos
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Top 10 - Glosa IMR")
            if df_filtered['glosaImrUnidade'].sum() > 0:
                top_imr = df_filtered[df_filtered['glosaImrUnidade'] > 0].groupby('nomeUnidadeEscolar')['glosaImrUnidade'].sum().reset_index().nlargest(10, 'glosaImrUnidade')
                st.altair_chart(alt.Chart(top_imr).mark_bar().encode(
                    x=alt.X('glosaImrUnidade', title='R$'), y=alt.Y('nomeUnidadeEscolar', sort='-x'), color=alt.value('#f57c00')
                ).interactive(), use_container_width=True)
            else:
                st.info("Sem glosa IMR neste período.")
                
        with c2:
            st.subheader("Top 10 - Glosa RH")
            if df_filtered['glosaRhUnidade'].sum() > 0:
                top_rh = df_filtered[df_filtered['glosaRhUnidade'] > 0].groupby('nomeUnidadeEscolar')['glosaRhUnidade'].sum().reset_index().nlargest(10, 'glosaRhUnidade')
                st.altair_chart(alt.Chart(top_rh).mark_bar().encode(
                    x=alt.X('glosaRhUnidade', title='R$'), y=alt.Y('nomeUnidadeEscolar', sort='-x'), color=alt.value('#d32f2f')
                ).interactive(), use_container_width=True)
            else:
                st.info("Sem glosa RH neste período.")

    else:
        st.info("👈 Por favor, faça o upload do arquivo CSV no menu lateral para visualizar o dashboard.")

# ------------------------------------------------------------------------------
# VISÃO 2: COMPARADOR
# ------------------------------------------------------------------------------
elif page_mode == "Comparador (Mês a Mês)":
    st.title("⚖️ Comparativo: Faturamento e Glosas")
    
    c1, c2 = st.columns(2)
    
    # Upload Base 1
    with c1:
        st.subheader("Mês Anterior (Base 1)")
        up1 = st.file_uploader("Upload Base 1", type=['csv'], key="u1")
        if up1 is not None: st.session_state['monit_df_comp1'] = load_data(up1)
        
        df1 = st.session_state['monit_df_comp1']
        if df1 is not None:
            mes_txt = f"Mês {df1['mes'].iloc[0]}" if 'mes' in df1.columns else "Carregado"
            st.success(f"✅ {mes_txt}")
        
    # Upload Base 2
    with c2:
        st.subheader("Mês Atual (Base 2)")
        up2 = st.file_uploader("Upload Base 2", type=['csv'], key="u2")
        if up2 is not None: st.session_state['monit_df_comp2'] = load_data(up2)
        
        df2 = st.session_state['monit_df_comp2']
        if df2 is not None:
            mes_txt = f"Mês {df2['mes'].iloc[0]}" if 'mes' in df2.columns else "Carregado"
            st.success(f"✅ {mes_txt}")

    if df1 is not None and df2 is not None:
        st.divider()
        
        fat1, fat2 = df1['totalUnidade'].sum(), df2['totalUnidade'].sum()
        rh1, rh2 = df1['glosaRhUnidade'].sum(), df2['glosaRhUnidade'].sum()
        
        # KPIs Comparativos
        st.subheader("1. Visão Geral")
        k1, k2, k3 = st.columns(3)
        delta_fat = fat2 - fat1
        delta_fat_perc = (delta_fat / fat1 * 100) if fat1 > 0 else 0
        
        k1.metric("Faturamento Base 1", f"R$ {fat1:,.2f}")
        k2.metric("Faturamento Base 2", f"R$ {fat2:,.2f}")
        k3.metric("Variação", f"R$ {delta_fat:,.2f}", f"{delta_fat_perc:.2f}%")
        
        st.divider()
        
        # Glosas
        st.subheader("2. Glosa RH")
        perc_rh1 = (rh1 / fat1 * 100) if fat1 > 0 else 0
        perc_rh2 = (rh2 / fat2 * 100) if fat2 > 0 else 0
        
        c_rh1, c_rh2 = st.columns(2)
        c_rh1.metric("Glosa RH (Valor)", f"R$ {rh2:,.2f}", f"{rh2-rh1:,.2f}", delta_color="inverse")
        c_rh2.metric("Glosa RH (%)", f"{perc_rh2:.2f}%", f"{perc_rh2-perc_rh1:.2f} p.p", delta_color="inverse")
        
        # Gráfico
        chart_df = pd.DataFrame({
            'Base': ['Base 1', 'Base 2'],
            'Glosa RH (%)': [perc_rh1, perc_rh2]
        })
        st.altair_chart(alt.Chart(chart_df).mark_bar().encode(
            x='Base', y='Glosa RH (%)', color=alt.value('#d32f2f'), tooltip=['Base', alt.Tooltip('Glosa RH (%)', format='.2f')]
        ).properties(height=200), use_container_width=True)

        st.divider()

        # Detalhamento
        st.subheader("🏫 Detalhamento por Escola")
        q = st.text_input("Buscar Escola:", placeholder="Nome...")
        
        cols_key = ['nomeUnidadeEscolar', 'totalUnidade', 'glosaRhUnidade']
        g1 = df1[cols_key].groupby('nomeUnidadeEscolar').sum().reset_index()
        g2 = df2[cols_key].groupby('nomeUnidadeEscolar').sum().reset_index()
        merged = pd.merge(g1, g2, on='nomeUnidadeEscolar', how='outer', suffixes=('_1', '_2')).fillna(0)
        
        merged['Dif Fat'] = merged['totalUnidade_2'] - merged['totalUnidade_1']
        merged['Dif RH'] = merged['glosaRhUnidade_2'] - merged['glosaRhUnidade_1']
        
        if q: merged = merged[merged['nomeUnidadeEscolar'].str.contains(q, case=False)]
        
        st.dataframe(
            merged[['nomeUnidadeEscolar', 'totalUnidade_1', 'totalUnidade_2', 'Dif Fat', 'glosaRhUnidade_1', 'glosaRhUnidade_2', 'Dif RH']],
            use_container_width=True,
            column_config={
                "nomeUnidadeEscolar": "Escola",
                "totalUnidade_1": st.column_config.NumberColumn("Fat Base 1", format="R$ %.2f"),
                "totalUnidade_2": st.column_config.NumberColumn("Fat Base 2", format="R$ %.2f"),
                "Dif Fat": st.column_config.NumberColumn("Δ Fat", format="R$ %.2f"),
                "glosaRhUnidade_1": st.column_config.NumberColumn("RH Base 1", format="R$ %.2f"),
                "glosaRhUnidade_2": st.column_config.NumberColumn("RH Base 2", format="R$ %.2f"),
                "Dif RH": st.column_config.NumberColumn("Δ RH", format="R$ %.2f"),
            },
            hide_index=True
        )