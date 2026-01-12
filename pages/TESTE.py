import streamlit as st 
import streamlit_authenticator as stauth
import pandas as pd
import plotly.express as px
import numpy as np 
from PIL import Image
from sqlalchemy import text

# ==============================================================================
# CONFIGURAÇÕES INICIAIS
# ==============================================================================
def configurar_pagina():
    st.set_page_config(page_title="Mesa Operacional", layout="wide", page_icon="📊")
    st.markdown("""
    <style>
        .block-container { padding-top: 1rem; }
        [data-testid="stMetricValue"] { font-size: 32px; font-weight: bold; }
        /* Centralizar textos nas células da tabela */
        .stDataFrame div[data-testid="stDataFrame"] div[role="grid"] div[role="row"] div {
            justify-content: center !important;
            text-align: center !important;
        }
        div.stButton > button { width: 100%; display: block; margin: 0 auto; }
    </style>
    """, unsafe_allow_html=True)

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
            st.write(""); st.write(""); st.write("");
            col_esq, col_centro, col_dir = st.columns([3, 2, 3])
            with col_centro:
                authenticator.login()
            if st.session_state.get("authentication_status") is False:
                with col_centro: st.error('Usuário ou senha incorretos')
            return None, None
            
        return authenticator, st.session_state.get("name")
    except Exception as e:
        st.error(f"Erro Crítico de Autenticação: {e}")
        st.stop()

# ==============================================================================
# QUERIES E DADOS
# ==============================================================================
@st.cache_data(ttl=600, show_spinner=False)
def buscar_dados_auxiliares(_conn):
    df_unidades = _conn.query('SELECT "UnidadeID", "NomeUnidade" FROM "Unidades" ORDER BY "NomeUnidade"')
    df_cargos = _conn.query('SELECT "CargoID", "NomeCargo" FROM "Cargos" ORDER BY "NomeCargo"')
    return df_unidades, df_cargos

@st.cache_data(ttl=600, show_spinner=False)
def buscar_dados_operacionais(_conn):
    # Query Principal (Resumo por Escola/Cargo)
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
        q."Quantidade" AS "Edital",
        COALESCE(cr."QtdReal", 0) AS "Real",
        (COALESCE(cr."QtdReal", 0) - q."Quantidade") AS "Diferenca_num"
    FROM "QuadroEdital" q
    JOIN "Unidades" u ON q."UnidadeID" = u."UnidadeID"
    JOIN "Cargos" c ON q."CargoID" = c."CargoID"
    JOIN "TiposUnidades" t ON u."TipoID" = t."TipoID"
    JOIN "Supervisores" s ON u."SupervisorID" = s."SupervisorID"
    LEFT JOIN ContagemReal cr ON q."UnidadeID" = cr."UnidadeID" AND q."CargoID" = cr."CargoID"
    ORDER BY u."NomeUnidade", c."NomeCargo";
    """
    
    # Query de Funcionários (Detalhe)
    query_funcionarios = """
    SELECT u."NomeUnidade" AS "Escola", c."NomeCargo" AS "Cargo", col."Nome" AS "Funcionario", col."ColaboradorID" AS "ID"
    FROM "Colaboradores" col
    JOIN "Unidades" u ON col."UnidadeID" = u."UnidadeID"
    JOIN "Cargos" c ON col."CargoID" = c."CargoID"
    WHERE col."Ativo" = TRUE
    ORDER BY u."NomeUnidade", c."NomeCargo", col."Nome";
    """

    df_resumo = _conn.query(query_resumo)
    df_pessoas = _conn.query(query_funcionarios)

    # Pré-cálculos de Status
    condicoes = [df_resumo['Diferenca_num'] < 0, df_resumo['Diferenca_num'] > 0]
    df_resumo['Status_Display'] = np.select(condicoes, ['🔴 FALTA', '🔵 EXCEDENTE'], default='🟢 OK')
    df_resumo['Status_Codigo'] = np.select(condicoes, ['FALTA', 'EXCEDENTE'], default='OK')
    df_resumo['Diferenca_Display'] = df_resumo['Diferenca_num'].apply(lambda x: f"+{x}" if x > 0 else str(int(x)))
    df_resumo['DataConferencia'] = pd.to_datetime(df_resumo['DataConferencia'])
    
    return df_resumo, df_pessoas

def acao_atualizar_data(unidade_id, nova_data, conn):
    try:
        with conn.session as session:
            session.execute(
                text('UPDATE "Unidades" SET "DataConferencia" = :nova_data WHERE "UnidadeID" = :uid'),
                {'nova_data': nova_data, 'uid': unidade_id}
            )
            session.commit()
        st.cache_data.clear()
        st.toast("Data salva!", icon="✅")
        st.rerun()
    except Exception as e:
        st.error(f"Erro: {e}")

# ==============================================================================
# MODAL DE DETALHES DA ESCOLA
# ==============================================================================
@st.dialog("🏫 Detalhes da Unidade", width="large")
def modal_detalhe_escola(escola_nome, row_stats, df_cargos_view, df_pessoas_view, conn, df_unidades_list, df_cargos_list):
    
    # 1. Info e Data
    c1, c2 = st.columns([2, 1])
    with c1:
        st.markdown(f"**Supervisor:** {row_stats['Supervisor']}")
        st.markdown(f"**Tipo:** {row_stats['Tipo']}")
    with c2:
        dt_atual = row_stats['DataConferencia']
        lbl = "⚠️ Conferência Pendente" if pd.isnull(dt_atual) else f"📅 Conferido: {dt_atual.strftime('%d/%m/%Y')}"
        with st.popover(lbl, use_container_width=True):
            nova_dt = st.date_input("Data:", value=pd.Timestamp.today() if pd.isnull(dt_atual) else dt_atual, format="DD/MM/YYYY")
            if st.button("Salvar Data"):
                acao_atualizar_data(int(row_stats['UnidadeID']), nova_dt, conn)

    # 2. Resumo Visual
    # Definindo cores e sinais para o resumo visual
    saldo_val = row_stats['Saldo']
    cor_resumo = '#ff4b4b' if saldo_val < 0 else ('#29b6f6' if saldo_val > 0 else '#00c853')
    sinal_resumo = '+' if saldo_val > 0 else ''

    st.markdown(f"""
    <div style='display: flex; justify-content: space-around; background-color: #f0f2f6; padding: 10px; border-radius: 8px; margin-bottom: 15px; color: black;'>
        <span>📋 Edital: <b>{row_stats['Edital']}</b></span>
        <span>👥 Real: <b>{row_stats['Real']}</b></span>
        <span>⚖️ Saldo: <b style='color: {cor_resumo}'>{sinal_resumo}{saldo_val}</b></span>
    </div>
    """, unsafe_allow_html=True)

    # 3. Tabela de Cargos
    st.caption("📊 Quadro de Vagas")
    df_view = df_cargos_view[['Cargo','Edital','Real','Diferenca_Display','Status_Display']].rename(columns={'Diferenca_Display':'Diferenca', 'Status_Display':'Status'})
    st.dataframe(df_view, use_container_width=True, hide_index=True)

    # 4. Lista de Pessoas com Edição
    st.caption("📋 Colaboradores (Selecione para Editar)")
    if not df_pessoas_view.empty:
        event = st.dataframe(
            df_pessoas_view[['ID','Funcionario','Cargo']],
            use_container_width=True, hide_index=True,
            selection_mode="single-row", on_select="rerun"
        )
        
        if len(event.selection.rows) > 0:
            idx = event.selection.rows[0]
            colab = df_pessoas_view.iloc[idx]
            
            with st.expander(f"✏️ Editar: {colab['Funcionario']}", expanded=True):
                with st.form(f"edit_{colab['ID']}"):
                    lst_esc = df_unidades_list['NomeUnidade'].tolist()
                    lst_car = df_cargos_list['NomeCargo'].tolist()
                    
                    try: i_esc = lst_esc.index(escola_nome)
                    except: i_esc = 0
                    try: i_car = lst_car.index(colab['Cargo'])
                    except: i_car = 0
                    
                    n_esc = st.selectbox("Escola:", lst_esc, index=i_esc)
                    n_car = st.selectbox("Cargo:", lst_car, index=i_car)
                    n_atv = st.checkbox("Ativo?", value=True)
                    
                    if st.form_submit_button("💾 Salvar"):
                        try:
                            uid_new = int(df_unidades_list[df_unidades_list['NomeUnidade'] == n_esc]['UnidadeID'].iloc[0])
                            cid_new = int(df_cargos_list[df_cargos_list['NomeCargo'] == n_car]['CargoID'].iloc[0])
                            
                            with conn.session as s:
                                s.execute(text('UPDATE "Colaboradores" SET "UnidadeID"=:u, "CargoID"=:c, "Ativo"=:a WHERE "ColaboradorID"=:i'), 
                                          {'u': uid_new, 'c': cid_new, 'a': n_atv, 'i': int(colab['ID'])})
                                s.commit()
                            st.cache_data.clear()
                            st.toast("Sucesso!", icon="🎉")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Erro: {e}")
    else:
        st.info("Nenhum colaborador nesta unidade.")

# ==============================================================================
# COMPONENTES VISUAIS (GRÁFICOS E MÉTRICAS)
# ==============================================================================
def exibir_sidebar(authenticator, nome_usuario):
    with st.sidebar:
        if logo := carregar_logo(): st.image(logo, use_container_width=True)
        st.divider()
        st.write(f"👤 **{nome_usuario}**"); authenticator.logout(location='sidebar')

def exibir_metricas_topo(df):
    c1, c2, c3 = st.columns(3)
    total_edital = int(df['Edital'].sum())
    total_real = int(df['Real'].sum())
    saldo = total_real - total_edital
    
    with c1: st.markdown("**<div style='font-size:18px'>📋 Total Edital</div>**", unsafe_allow_html=True); st.metric("", total_edital)
    with c2: st.markdown("**<div style='font-size:18px'>👥 Efetivo Atual</div>**", unsafe_allow_html=True); st.metric("", total_real)
    with c3: st.markdown("**<div style='font-size:18px'>⚖️ Saldo Geral</div>**", unsafe_allow_html=True); st.metric("", saldo)
    st.markdown("---")

def exibir_graficos_gerais(df):
    """Exibe o gráfico de barras comparativo e a tabela resumo por cargo"""
    with st.expander("📈 Ver Gráficos e Resumo Geral", expanded=True):
        # Agrupa dados globais por cargo
        df_agrupado = df.groupby('Cargo')[['Edital','Real']].sum().reset_index()
        df_agrupado['Saldo'] = df_agrupado['Real'] - df_agrupado['Edital']
        df_agrupado['Diff_Display'] = df_agrupado['Saldo'].apply(lambda x: f"+{x}" if x > 0 else str(x))
        
        c_g1, c_g2 = st.columns([2,1])
        with c_g1: 
            # Gráfico de Barras Comparativo
            fig = px.bar(df_agrupado.melt(id_vars=['Cargo'], value_vars=['Edital','Real'], var_name='Tipo', value_name='Quantidade'), 
                         x='Cargo', y='Quantidade', color='Tipo', barmode='group', 
                         color_discrete_map={'Edital': '#808080','Real': '#00bfff'}, text_auto=True, template="seaborn")
            st.plotly_chart(fig, use_container_width=True)
        
        with c_g2: 
            # Tabela Resumo com cores no saldo
            df_display = df_agrupado[['Cargo','Edital','Real','Saldo']]
            
            def colorir_saldo(val):
                if val < 0: return 'color: #ff4b4b; font-weight: bold;'
                elif val > 0: return 'color: #29b6f6; font-weight: bold;'
                return 'color: #00c853; font-weight: bold;'

            st.dataframe(
                df_display.style.map(colorir_saldo, subset=['Saldo']), 
                use_container_width=True, 
                hide_index=True,
                column_config={"Saldo": st.column_config.NumberColumn("Saldo", format="%+d")}
            )

# ==============================================================================
# MAIN
# ==============================================================================
def main():
    configurar_pagina()
    authenticator, nome_usuario = realizar_login()
    
    if authenticator:
        exibir_sidebar(authenticator, nome_usuario)
        
        try:
            conn = st.connection("postgres", type="sql")
            
            df_unidades_list, df_cargos_list = buscar_dados_auxiliares(conn)
            df_resumo, df_pessoas = buscar_dados_operacionais(conn)
            
            st.title("📊 Mesa Operacional")
            exibir_metricas_topo(df_resumo)
            exibir_graficos_gerais(df_resumo) # Gráficos reintegrados

            st.markdown("---"); st.subheader("🏫 Lista de Escolas")

            # --- FILTROS (Com Filtro de Tipo reintegrado) ---
            c_f1, c_f2, c_f3, c_f4, c_f5 = st.columns([1.5, 1.2, 1.2, 1, 1])
            with c_f1: filtro_escola = st.selectbox("🔍 Escola:", ["Todas"] + sorted(list(df_resumo['Escola'].unique())))
            with c_f2: filtro_supervisor = st.selectbox("👔 Supervisor:", ["Todos"] + sorted(list(df_resumo['Supervisor'].unique())))
            with c_f3: filtro_tipo = st.selectbox("🏷️ Tipo:", ["Todos"] + sorted(list(df_resumo['Tipo'].unique()))) # Novo filtro
            with c_f4: filtro_situacao = st.selectbox("🚦 Situação:", ["Todas", "🔴 FALTA", "🔵 EXCEDENTE", "🟢 OK"])
            with c_f5: termo_busca = st.text_input("👤 Buscar Pessoa:", "")

            # --- FILTROS AVANÇADOS POR CARGO (Reintegrado) ---
            lista_cargos_filtro = sorted(list(df_resumo['Cargo'].unique()))
            filtro_comb = {}
            with st.expander("🔎 Filtros Avançados por Cargo"):
                cols = st.columns(5)
                for i, cargo in enumerate(lista_cargos_filtro):
                    with cols[i % 5]:
                        if (sel := st.selectbox(cargo, ["Todos","FALTA","EXCEDENTE","OK"], key=f'f_{i}')) != "Todos": 
                            filtro_comb[cargo] = sel

            # --- APLICAÇÃO DOS FILTROS ---
            mask = pd.Series([True] * len(df_resumo))
            
            if filtro_escola != "Todas": mask &= (df_resumo['Escola'] == filtro_escola)
            if filtro_supervisor != "Todos": mask &= (df_resumo['Supervisor'] == filtro_supervisor)
            if filtro_tipo != "Todos": mask &= (df_resumo['Tipo'] == filtro_tipo)
            
            if filtro_situacao != "Todas":
                agg = df_resumo.groupby('Escola').agg({'Edital': 'sum', 'Real': 'sum', 'Status_Codigo': list}).reset_index()
                agg['Saldo'] = agg['Real'] - agg['Edital']
                condicoes_agg = [
                    agg['Saldo'] > 0, agg['Saldo'] < 0,
                    (agg['Saldo'] == 0) & (agg['Status_Codigo'].apply(lambda x: any(s != 'OK' for s in x)))
                ]
                agg['Status_Calculado'] = np.select(condicoes_agg, ["🔵 EXCEDENTE", "🔴 FALTA", "🟡 AJUSTE"], default="🟢 OK")
                escolas_alvo = agg[agg['Status_Calculado'] == filtro_situacao]['Escola']
                mask &= df_resumo['Escola'].isin(escolas_alvo)

            if filtro_comb:
                for c, s in filtro_comb.items():
                    # Filtra escolas que tenham aquele cargo com aquele status
                    escolas_validas = df_resumo[(df_resumo['Cargo'] == c) & (df_resumo['Status_Codigo'] == s)]['Escola']
                    mask &= df_resumo['Escola'].isin(escolas_validas)

            if termo_busca:
                match = df_pessoas[df_pessoas['Funcionario'].str.contains(termo_busca, case=False, na=False) | 
                                 df_pessoas['ID'].astype(str).str.contains(termo_busca, na=False)]['Escola'].unique()
                mask &= df_resumo['Escola'].isin(match)

            df_final = df_resumo[mask]
            
            # --- PREPARAÇÃO DA LISTA DE ESCOLAS ---
            if not df_final.empty:
                df_view = df_final.copy()
                df_view = df_view.rename(columns={'Diferenca_Display': 'Diferenca', 'Status_Display': 'Status'})
                cols_num = ['Edital', 'Real']
                df_view[cols_num] = df_view[cols_num].apply(pd.to_numeric, errors='coerce').fillna(0).astype(int)
                
                # Agrupa por Escola para a lista principal
                df_lista = df_view.groupby('Escola').agg({
                    'Edital': 'sum', 'Real': 'sum',
                    'Supervisor': 'first', 'Tipo': 'first', # Tipo incluído
                    'UnidadeID': 'first', 'DataConferencia': 'first',
                    'Status_Codigo': lambda x: list(x)
                }).reset_index()
                
                # Lógica do Status (Emojis)
                df_lista['Saldo'] = df_lista['Real'] - df_lista['Edital']
                condicoes_icone = [
                    df_lista['Saldo'] > 0, df_lista['Saldo'] < 0,
                    (df_lista['Saldo'] == 0) & (df_lista['Status_Codigo'].apply(lambda x: any(s == 'FALTA' for s in x)))
                ]
                df_lista['Icone'] = np.select(condicoes_icone, ["🔵", "🔴", "🟡"], default="✅")
                df_lista['Cor'] = np.where(df_lista['Saldo'] < 0, '#ff4b4b', np.where(df_lista['Saldo'] > 0, '#29b6f6', '#00c853'))
                df_lista['Sinal'] = np.where(df_lista['Saldo'] > 0, '+', '')

                # Reaplica filtro de situação se necessário (para pegar o amarelo 'Ajuste' que pode ter escapado)
                if filtro_situacao != "Todas":
                    mapa = {"🔴 FALTA": ["🔴", "🟡"], "🔵 EXCEDENTE": ["🔵"], "🟢 OK": ["✅"]}
                    validos = mapa.get(filtro_situacao, [])
                    df_lista = df_lista[df_lista['Icone'].isin(validos)]

                # Ordenação
                df_lista['sort_key'] = df_lista['Icone'].map({"🔴": 0, "🟡": 1, "🔵": 2, "✅": 3})
                df_lista = df_lista.sort_values(['sort_key', 'Escola'])

                # --- RENDERIZAÇÃO DA TABELA ---
                st.divider()
                st.info(f"**{len(df_lista)} Unidades Encontradas.** Clique na linha para gerenciar.")
                
                # Seleciona colunas para exibição
                df_show = df_lista[['Icone', 'Tipo', 'Escola', 'Supervisor', 'Edital', 'Real', 'Saldo']].rename(columns={'Icone': 'Status'})
                
                # Estilo condicional para o Saldo
                def colorir_saldo(val):
                    if val < 0: return 'color: #ff4b4b; font-weight: bold;'
                    elif val > 0: return 'color: #29b6f6; font-weight: bold;'
                    return 'color: #00c853; font-weight: bold;'

                event = st.dataframe(
                    df_show.style.map(colorir_saldo, subset=['Saldo']),
                    use_container_width=True,
                    hide_index=True,
                    selection_mode="single-row",
                    on_select="rerun",
                    column_config={
                        "Status": st.column_config.TextColumn("St", width="small", help="🔴 Falta | 🔵 Excedente | 🟡 Ajuste Interno | ✅ Ok"),
                        "Tipo": st.column_config.TextColumn("Tipo", width="small"),
                        "Escola": st.column_config.TextColumn("Unidade Escolar", width="large"),
                        "Saldo": st.column_config.NumberColumn("Saldo", format="%+d")
                    }
                )

                # --- AÇÃO DE CLIQUE (ABRIR MODAL) ---
                if len(event.selection.rows) > 0:
                    idx = event.selection.rows[0]
                    # Garante que pegamos a escola correta mesmo com ordenação
                    escola_sel = df_show.iloc[idx]['Escola']
                    
                    # Recupera dados originais para passar ao modal
                    row_stats = df_lista[df_lista['Escola'] == escola_sel].iloc[0]
                    df_cargos_sel = df_view[df_view['Escola'] == escola_sel]
                    df_pessoas_sel = df_pessoas[df_pessoas['Escola'] == escola_sel]
                    
                    if termo_busca:
                        df_pessoas_sel = df_pessoas_sel[df_pessoas_sel['Funcionario'].str.contains(termo_busca, case=False, na=False) | 
                                                      df_pessoas_sel['ID'].astype(str).str.contains(termo_busca, na=False)]

                    modal_detalhe_escola(escola_sel, row_stats, df_cargos_sel, df_pessoas_sel, conn, df_unidades_list, df_cargos_list)
            else:
                st.warning("Nenhuma escola encontrada com os filtros atuais.")

        except Exception as e:
            st.error(f"Erro no sistema: {e}")

if __name__ == "__main__":
    main()