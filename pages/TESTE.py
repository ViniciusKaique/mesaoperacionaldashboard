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
        .dataframe { font-size: 14px !important; }
        
        th, td { text-align: center !important; }
        .stDataFrame div[data-testid="stDataFrame"] div[role="grid"] div[role="row"] div {
            justify-content: center !important;
            text-align: center !important;
        }

        div[data-testid="stSpinner"] > div {
            font-size: 28px !important;
            font-weight: bold !important; color: #ff4b4b !important; white-space: nowrap;
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
            st.write(""); st.write(""); st.write(""); st.write(""); st.write("")
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

    condicoes = [df_resumo['Diferenca_num'] < 0, df_resumo['Diferenca_num'] > 0]
    df_resumo['Status_Display'] = np.select(condicoes, ['🔴 FALTA', '🔵 EXCEDENTE'], default='🟢 OK')
    df_resumo['Status_Codigo'] = np.select(condicoes, ['FALTA', 'EXCEDENTE'], default='OK')
    df_resumo['Diferenca_Display'] = df_resumo['Diferenca_num'].apply(lambda x: f"+{x}" if x > 0 else str(int(x)))
    df_resumo['DataConferencia'] = pd.to_datetime(df_resumo['DataConferencia'])
    
    return df_resumo, df_pessoas

# ==============================================================================
# LÓGICA DE ATUALIZAÇÃO (DB)
# ==============================================================================
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
        st.error(f"Erro ao salvar data: {e}")

# ==============================================================================
# MODAL DE DETALHE (Substitui o Expander)
# ==============================================================================
@st.dialog("🏫 Detalhes da Unidade", width="large")
def detalhar_escola(nome_escola, stats_row, df_cargos_view, df_pessoas_view, conn, df_unidades_bd, df_cargos_bd):
    
    # 1. Cabeçalho e Data
    c_sup, c_btn = st.columns([3, 1.5])
    with c_sup: 
        st.markdown(f"**👨‍💼 Supervisor:** {stats_row['Supervisor']}")
    with c_btn:
        data_atual = stats_row['DataConferencia']
        unidade_id = int(stats_row['UnidadeID'])
        label_botao = "⚠️ Pendente" if pd.isnull(data_atual) else f"📅 Conferido: {data_atual.strftime('%d/%m/%Y')}"
        
        with st.popover(label_botao, use_container_width=True):
            st.markdown("Alterar data de conferência")
            nova_data_input = st.date_input("Nova Data:", value=pd.Timestamp.today() if pd.isnull(data_atual) else data_atual, format="DD/MM/YYYY", key=f"dt_mod_{unidade_id}")
            if st.button("💾 Salvar Data", key=f"save_mod_{unidade_id}"):
                acao_atualizar_data(unidade_id, nova_data_input, conn)

    # 2. Métricas Visuais (HTML)
    st.markdown(f"""
    <div style='display: flex; justify-content: space-around; background-color: #262730; padding: 8px; border-radius: 5px; margin: 5px 0 15px 0; border: 1px solid #404040;'>
        <span>📋 Edital: <b>{stats_row['Edital']}</b></span>
        <span>👥 Real: <b>{stats_row['Real']}</b></span>
        <span>⚖️ Saldo: <b style='color: {stats_row['Cor']}'>{stats_row['Sinal']}{stats_row['Saldo']}</b></span>
    </div>
    """, unsafe_allow_html=True)

    # 3. Tabela de Cargos
    st.markdown("#### 📊 Quadro de Vagas")
    df_tabela_final = df_cargos_view[['Cargo','Edital','Real','Diferenca','Status']]
    
    def estilo_linha_escola(row):
        styles = ['text-align: center;'] * 5
        val = str(row['Diferenca'])
        if '-' in val: styles[3] += 'color: #ff4b4b; font-weight: bold;'
        elif '+' in val: styles[3] += 'color: #29b6f6; font-weight: bold;'
        else: styles[3] += 'color: #00c853; font-weight: bold;'
        
        stt = str(row['Status'])
        if '🔴' in stt: styles[4] += 'color: #ff4b4b; font-weight: bold;'
        elif '🔵' in stt: styles[4] += 'color: #29b6f6; font-weight: bold;'
        else: styles[4] += 'color: #00c853; font-weight: bold;'
        return styles
    
    st.dataframe(df_tabela_final.style.apply(estilo_linha_escola, axis=1), use_container_width=True, hide_index=True)

    # 4. Lista de Colaboradores e Edição
    st.markdown("#### 📋 Colaboradores (Selecione para Editar)")
    
    if not df_pessoas_view.empty:
        # Tabela selecionável dentro do modal
        event_colab = st.dataframe(
            df_pessoas_view[['ID','Funcionario','Cargo']], 
            use_container_width=True, 
            hide_index=True, 
            on_select="rerun", 
            selection_mode="single-row", 
            key=f"grid_modal_{unidade_id}"
        )
        
        if len(event_colab.selection.rows) > 0:
            idx_sel = event_colab.selection.rows[0]
            dados_colab = df_pessoas_view.iloc[idx_sel]
            
            # Formulário de edição (substitui o antigo dialog aninhado)
            with st.expander(f"✏️ Editar: {dados_colab['Funcionario']}", expanded=True):
                with st.form(key=f"form_edit_{dados_colab['ID']}"):
                    lista_escolas = df_unidades_bd['NomeUnidade'].tolist()
                    try: idx_escola = lista_escolas.index(stats_row.name) # Nome da escola atual
                    except: idx_escola = 0
                    nova_escola = st.selectbox("🏫 Mover para Escola:", lista_escolas, index=idx_escola)

                    lista_cargos_bd = df_cargos_bd['NomeCargo'].tolist()
                    try: idx_cargo = lista_cargos_bd.index(dados_colab['Cargo'])
                    except: idx_cargo = 0
                    novo_cargo = st.selectbox("💼 Alterar Cargo:", lista_cargos_bd, index=idx_cargo)

                    novo_status = st.checkbox("✅ Manter Ativo?", value=True)
                    
                    if st.form_submit_button("💾 Confirmar Alteração"):
                        novo_uid = int(df_unidades_bd[df_unidades_bd['NomeUnidade'] == nova_escola]['UnidadeID'].iloc[0])
                        novo_cid = int(df_cargos_bd[df_cargos_bd['NomeCargo'] == novo_cargo]['CargoID'].iloc[0])
                        colab_id = int(dados_colab['ID'])
                        
                        try:
                            with conn.session as session:
                                session.execute(text("UPDATE \"Colaboradores\" SET \"UnidadeID\" = :uid, \"CargoID\" = :cid, \"Ativo\" = :ativo WHERE \"ColaboradorID\" = :id"), 
                                                {"uid": novo_uid, "cid": novo_cid, "ativo": novo_status, "id": colab_id})
                                session.commit()
                            st.cache_data.clear() 
                            st.toast("Colaborador atualizado!", icon="🎉")
                            st.rerun()
                        except Exception as e: st.error(f"Erro: {e}")
    else:
        st.info("Nenhum colaborador alocado nesta unidade.")

# ==============================================================================
# UI COMPONENTS
# ==============================================================================
def exibir_sidebar(authenticator, nome_usuario):
    with st.sidebar:
        if logo := carregar_logo(): st.image(logo, use_container_width=True)
        st.divider()
        st.write(f"👤 **{nome_usuario}**"); authenticator.logout(location='sidebar'); st.divider()
        st.info("Painel Gerencial + Detalhe")

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
    with st.expander("📈 Ver Gráficos e Resumo Geral", expanded=True):
        df_agrupado = df.groupby('Cargo')[['Edital','Real']].sum().reset_index()
        df_agrupado['Diff_Display'] = (df_agrupado['Real'] - df_agrupado['Edital']).apply(lambda x: f"+{x}" if x > 0 else str(x))
        
        c_g1, c_g2 = st.columns([2,1])
        with c_g1: 
            fig = px.bar(df_agrupado.melt(id_vars=['Cargo'], value_vars=['Edital','Real'], var_name='Tipo', value_name='Quantidade'), 
                         x='Cargo', y='Quantidade', color='Tipo', barmode='group', 
                         color_discrete_map={'Edital': '#808080','Real': '#00bfff'}, text_auto=True, template="seaborn")
            st.plotly_chart(fig, use_container_width=True)
        
        with c_g2: 
            def estilo_tabela(row):
                styles = ['text-align: center;'] * 4
                val = str(row['Diferenca'])
                if '-' in val: styles[3] += 'color: #ff4b4b; font-weight: bold;'
                elif '+' in val: styles[3] += 'color: #29b6f6; font-weight: bold;'
                else: styles[3] += 'color: #00c853; font-weight: bold;'
                return styles
            
            df_display = df_agrupado[['Cargo','Edital','Real','Diff_Display']].rename(columns={'Diff_Display':'Diferenca'})
            st.dataframe(df_display.style.apply(estilo_tabela, axis=1), use_container_width=True, hide_index=True)

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
            
            df_unidades, df_cargos = buscar_dados_auxiliares(conn)
            df_resumo, df_pessoas = buscar_dados_operacionais(conn)
            
            st.title("📊 Mesa Operacional")
            exibir_metricas_topo(df_resumo)
            exibir_graficos_gerais(df_resumo)

            st.markdown("---"); st.subheader("🏫 Lista de Escolas")

            # --- FILTROS ---
            c_f1, c_f2, c_f3, c_f4 = st.columns([1.2, 1.2, 1, 1])
            with c_f1: filtro_escola = st.selectbox("🔍 Escola:", ["Todas"] + sorted(list(df_resumo['Escola'].unique())))
            with c_f2: filtro_supervisor = st.selectbox("👔 Supervisor:", ["Todos"] + sorted(list(df_resumo['Supervisor'].unique())))
            with c_f3: filtro_situacao = st.selectbox("🚦 Situação:", ["Todas", "🔴 FALTA", "🔵 EXCEDENTE", "🟡 AJUSTE", "🟢 OK"])
            with c_f4: termo_busca = st.text_input("👤 Buscar Colaborador:", "")

            # Filtros de Cargos (Linha extra)
            lista_cargos_filtro = list(df_resumo['Cargo'].unique())
            filtro_comb = {}
            if st.checkbox("Exibir Filtros por Cargo"):
                cols = st.columns(5)
                for i, cargo in enumerate(lista_cargos_filtro):
                    with cols[i % 5]:
                        if (sel := st.selectbox(cargo, ["Todos","FALTA","EXCEDENTE","OK"], key=f'f_{i}')) != "Todos": 
                            filtro_comb[cargo] = sel

            # --- APLICAÇÃO DOS FILTROS ---
            mask = pd.Series([True] * len(df_resumo))
            if filtro_escola != "Todas": mask &= (df_resumo['Escola'] == filtro_escola)
            if filtro_supervisor != "Todos": mask &= (df_resumo['Supervisor'] == filtro_supervisor)
            
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
                    escolas_validas = df_resumo[(df_resumo['Cargo'] == c) & (df_resumo['Status_Codigo'] == s)]['Escola']
                    mask &= df_resumo['Escola'].isin(escolas_validas)

            if termo_busca:
                match = df_pessoas[df_pessoas['Funcionario'].str.contains(termo_busca, case=False, na=False) | df_pessoas['ID'].astype(str).str.contains(termo_busca, na=False)]['Escola'].unique()
                mask &= df_resumo['Escola'].isin(match)

            df_final = df_resumo[mask]
            
            # --- PREPARAÇÃO DA TABELA LISTA ---
            if not df_final.empty:
                df_view = df_final.copy()
                df_view = df_view.rename(columns={'Diferenca_Display': 'Diferenca', 'Status_Display': 'Status'})
                
                cols_num = ['Edital', 'Real']
                df_view[cols_num] = df_view[cols_num].apply(pd.to_numeric, errors='coerce').fillna(0).astype(int)
                df_view = df_view.sort_values('Escola')

                # Tabela Resumo (Stats) para a Lista Principal
                df_stats = df_view.groupby('Escola').agg({
                    'Edital': 'sum', 'Real': 'sum',
                    'Status_Codigo': lambda x: any(s != 'OK' for s in x),
                    'UnidadeID': 'first', 'Supervisor': 'first', 'DataConferencia': 'first'
                })

                df_stats['Saldo'] = df_stats['Real'] - df_stats['Edital']
                condicoes_icone = [
                    df_stats['Saldo'] > 0, df_stats['Saldo'] < 0,
                    (df_stats['Saldo'] == 0) & (df_stats['Status_Codigo'])
                ]
                df_stats['Icone'] = np.select(condicoes_icone, ["🔵", "🔴", "🟡"], default="✅")
                df_stats['Cor'] = np.where(df_stats['Saldo'] < 0, 'red', np.where(df_stats['Saldo'] > 0, 'blue', 'green'))
                df_stats['Sinal'] = np.where(df_stats['Saldo'] > 0, '+', '')

                # -------------------------------------------------------------
                # RENDERIZAÇÃO DA TABELA DE SELEÇÃO
                # -------------------------------------------------------------
                st.info(f"**Encontradas {len(df_stats)} escolas.** Clique na linha para ver detalhes.")
                
                # Prepara dataframe para exibição (reset index para ter Escola como coluna)
                df_lista_show = df_stats.reset_index()[['Icone', 'Escola', 'Supervisor', 'Edital', 'Real', 'Saldo']]
                
                event = st.dataframe(
                    df_lista_show,
                    use_container_width=True,
                    hide_index=True,
                    selection_mode="single-row",
                    on_select="rerun",
                    column_config={
                        "Icone": st.column_config.TextColumn("St", width="small"),
                        "Escola": st.column_config.TextColumn("Unidade Escolar", width="large"),
                        "Saldo": st.column_config.NumberColumn("Saldo", format="%d")
                    }
                )

                # -------------------------------------------------------------
                # AÇÃO DE CLIQUE -> ABRIR MODAL
                # -------------------------------------------------------------
                if len(event.selection.rows) > 0:
                    idx_selecionado = event.selection.rows[0]
                    nome_escola_sel = df_lista_show.iloc[idx_selecionado]['Escola']
                    
                    # Recupera dados detalhados para o modal
                    stats_row = df_stats.loc[nome_escola_sel]
                    df_cargos_sel = df_view[df_view['Escola'] == nome_escola_sel]
                    
                    df_pessoas_sel = df_pessoas[df_pessoas['Escola'] == nome_escola_sel]
                    if termo_busca: # Reaplica filtro de busca de pessoas se houver
                        df_pessoas_sel = df_pessoas_sel[df_pessoas_sel['Funcionario'].str.contains(termo_busca, case=False, na=False) | df_pessoas_sel['ID'].astype(str).str.contains(termo_busca, na=False)]

                    # Abre o Dialog
                    detalhar_escola(nome_escola_sel, stats_row, df_cargos_sel, df_pessoas_sel, conn, df_unidades, df_cargos)

            else:
                st.warning("Nenhuma escola encontrada com os filtros atuais.")

        except Exception as e:
            st.error(f"Erro no sistema: {e}")

if __name__ == "__main__":
    main()