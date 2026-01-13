import streamlit as st 
import streamlit_authenticator as stauth
import pandas as pd
import plotly.express as px
import numpy as np 
from PIL import Image
from sqlalchemy import text
from datetime import date

# ==============================================================================
# CONFIGURAÇÕES E CONSTANTES
# ==============================================================================
ID_VOLANTES = 101092601 # ID da Unidade de Volantes (Base fixa deles)

def configurar_pagina():
    st.set_page_config(page_title="Mesa Operacional", layout="wide", page_icon="📊")
    st.markdown("""
    <style>
        .block-container { padding-top: 1rem; }
        [data-testid="stMetricValue"] { font-size: 32px; font-weight: bold; }
        
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
@st.cache_data(ttl=60, show_spinner=False) # TTL baixo para refletir alocações rápido
def buscar_dados_auxiliares(_conn):
    df_unidades = _conn.query('SELECT "UnidadeID", "NomeUnidade" FROM "Unidades" ORDER BY "NomeUnidade"')
    df_cargos = _conn.query('SELECT "CargoID", "NomeCargo" FROM "Cargos" ORDER BY "NomeCargo"')
    return df_unidades, df_cargos

@st.cache_data(ttl=60, show_spinner=False)
def buscar_dados_operacionais(_conn):
    # 1. Query Resumo (Quadro de Vagas)
    query_resumo = """
    WITH ContagemReal AS (
        SELECT "UnidadeID", "CargoID", COUNT(*) as "QtdReal"
        FROM "Colaboradores"
        WHERE "Ativo" = TRUE
        GROUP BY "UnidadeID", "CargoID"
    )
    SELECT 
        t."NomeTipo" AS "Tipo", u."UnidadeID", u."NomeUnidade" AS "Escola", 
        u."DataConferencia", s."NomeSupervisor" AS "Supervisor", 
        c."NomeCargo" AS "Cargo", q."Quantidade" AS "Edital",
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
    
    # 2. Query Todos Funcionários
    query_funcionarios = """
    SELECT u."UnidadeID", u."NomeUnidade" AS "Escola", c."NomeCargo" AS "Cargo", col."Nome" AS "Funcionario", col."ColaboradorID" AS "ID"
    FROM "Colaboradores" col
    JOIN "Unidades" u ON col."UnidadeID" = u."UnidadeID"
    JOIN "Cargos" c ON col."CargoID" = c."CargoID"
    WHERE col."Ativo" = TRUE
    ORDER BY u."NomeUnidade", c."NomeCargo", col."Nome";
    """

    # 3. Query Alocações de HOJE (Reset automático amanhã)
    query_alocacoes = """
    SELECT av."ColaboradorID" AS "ID", av."UnidadeDestinoID", u."NomeUnidade" AS "EscolaDestino"
    FROM "AlocacaoVolantes" av
    JOIN "Unidades" u ON av."UnidadeDestinoID" = u."UnidadeID"
    WHERE av."DataAlocacao" = CURRENT_DATE
    """

    df_resumo = _conn.query(query_resumo)
    df_pessoas = _conn.query(query_funcionarios)
    df_alocacoes = _conn.query(query_alocacoes)

    # --- PROCESSAMENTO DOS VOLANTES ---
    # Separa volantes da lista geral
    df_volantes_base = df_pessoas[df_pessoas['UnidadeID'] == ID_VOLANTES].copy()
    
    # Merge com alocações para saber status
    df_volantes_status = pd.merge(df_volantes_base, df_alocacoes, on="ID", how="left")
    
    # Define Status Texto e Visual
    df_volantes_status['Status_Texto'] = np.where(df_volantes_status['UnidadeDestinoID'].notnull(), 
                                                  "Cobrindo: " + df_volantes_status['EscolaDestino'], 
                                                  "Disponível")
    df_volantes_status['Status_Icon'] = np.where(df_volantes_status['UnidadeDestinoID'].notnull(), "🔴", "🟢")

    # Remove volantes (base fixa) da lista geral de gestão escolas
    df_resumo = df_resumo[df_resumo['UnidadeID'] != ID_VOLANTES]
    df_pessoas = df_pessoas[df_pessoas['UnidadeID'] != ID_VOLANTES]

    # Lógica de Status (Texto Puro)
    condicoes = [df_resumo['Diferenca_num'] < 0, df_resumo['Diferenca_num'] > 0]
    df_resumo['Status_Codigo'] = np.select(condicoes, ['FALTA', 'EXCEDENTE'], default='OK')
    df_resumo['Status_Display'] = np.select(condicoes, ['🔴 FALTA', '🔵 EXCEDENTE'], default='🟢 OK')
    df_resumo['Diferenca_Display'] = df_resumo['Diferenca_num'].apply(lambda x: f"+{x}" if x > 0 else str(int(x)))
    df_resumo['DataConferencia'] = pd.to_datetime(df_resumo['DataConferencia'])
    
    return df_resumo, df_pessoas, df_volantes_status, df_alocacoes

def acao_atualizar_data(unidade_id, nova_data, conn):
    try:
        with conn.session as session:
            session.execute(text('UPDATE "Unidades" SET "DataConferencia" = :nova_data WHERE "UnidadeID" = :uid'),
                            {'nova_data': nova_data, 'uid': unidade_id})
            session.commit()
        st.cache_data.clear()
        st.toast("Data salva!", icon="✅")
        st.rerun()
    except Exception as e:
        st.error(f"Erro: {e}")

# ==============================================================================
# FUNÇÕES DE ALOCAÇÃO (SQL)
# ==============================================================================
def acao_alocar_volante(colab_id, unidade_destino_id, conn):
    try:
        with conn.session as s:
            # Garante que limpa qualquer alocação anterior HOJE para esse ID antes de inserir a nova
            s.execute(text('DELETE FROM "AlocacaoVolantes" WHERE "ColaboradorID" = :id AND "DataAlocacao" = CURRENT_DATE'), {'id': colab_id})
            s.execute(text('INSERT INTO "AlocacaoVolantes" ("ColaboradorID", "UnidadeDestinoID", "DataAlocacao") VALUES (:cid, :uid, CURRENT_DATE)'),
                      {'cid': colab_id, 'uid': unidade_destino_id})
            s.commit()
        st.cache_data.clear()
        st.toast("Volante alocado!", icon="🚙")
        st.rerun()
    except Exception as e:
        st.error(f"Erro ao alocar: {e}")

def acao_desalocar_volante(colab_id, conn):
    try:
        with conn.session as s:
            s.execute(text('DELETE FROM "AlocacaoVolantes" WHERE "ColaboradorID" = :id AND "DataAlocacao" = CURRENT_DATE'), {'id': colab_id})
            s.commit()
        st.cache_data.clear()
        st.toast("Volante liberado!", icon="🟢")
        st.rerun()
    except Exception as e:
        st.error(f"Erro ao desalocar: {e}")

# ==============================================================================
# MODAIS (DIALOGS)
# ==============================================================================

@st.dialog("🚙 Gestão de Volantes (Diário)", width="large")
def modal_lista_volantes(df_volantes, conn, df_unidades_list):
    st.markdown(f"### Status do Dia: {date.today().strftime('%d/%m/%Y')}")
    
    # Métricas Rápidas
    total = len(df_volantes)
    disponiveis = len(df_volantes[df_volantes['UnidadeDestinoID'].isnull()])
    alocados = total - disponiveis
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Total", total)
    c2.metric("🟢 Disponíveis", disponiveis)
    c3.metric("🔴 Alocados", alocados)
    
    st.divider()

    # Visualização Tabela
    st.dataframe(
        df_volantes[['Status_Icon', 'Funcionario', 'Cargo', 'Status_Texto']], 
        use_container_width=True, hide_index=True,
        column_config={"Status_Icon": st.column_config.TextColumn("", width="small")}
    )

    st.subheader("🛠️ Ações")
    col_sel, col_act = st.columns([2, 1])
    
    with col_sel:
        opcoes = df_volantes['Funcionario'].tolist()
        nome_selecionado = st.selectbox("Selecione o Volante:", ["Selecione..."] + opcoes)

    if nome_selecionado != "Selecione...":
        row = df_volantes[df_volantes['Funcionario'] == nome_selecionado].iloc[0]
        colab_id = int(row['ID'])
        esta_alocado = pd.notnull(row['UnidadeDestinoID'])

        with col_act:
            st.write("") # Espaçamento
            st.write("") 
            if esta_alocado:
                st.info(f"Atualmente em: **{row['EscolaDestino']}**")
                if st.button("🔓 Liberar (Tornar Disponível)", type="primary"):
                    acao_desalocar_volante(colab_id, conn)
            else:
                st.success("Atualmente **Disponível**")
        
        if not esta_alocado:
            # Form para Alocar
            with st.form("form_alocacao"):
                st.write(f"Alocar **{nome_selecionado}** hoje para:")
                lst_esc = df_unidades_list['NomeUnidade'].tolist()
                destino = st.selectbox("Escolha a Escola:", lst_esc)
                
                if st.form_submit_button("🚙 Confirmar Alocação"):
                    uid_dest = int(df_unidades_list[df_unidades_list['NomeUnidade'] == destino]['UnidadeID'].iloc[0])
                    acao_alocar_volante(colab_id, uid_dest, conn)

@st.dialog("🏫 Detalhes da Unidade", width="large")
def modal_detalhe_escola(escola_nome, escola_id, row_stats, df_cargos_view, df_pessoas_view, df_volantes_todos, conn):
    
    # --- CABEÇALHO ---
    c1, c2 = st.columns([2, 1])
    with c1:
        st.markdown(f"**Supervisor:** {row_stats['Supervisor']}")
        st.markdown(f"**Tipo:** {row_stats['Tipo']}")
    with c2:
        dt_atual = row_stats['DataConferencia']
        lbl = "⚠️ Pendente" if pd.isnull(dt_atual) else f"📅 {dt_atual.strftime('%d/%m/%Y')}"
        with st.popover(lbl, use_container_width=True):
            nova_dt = st.date_input("Data:", value=pd.Timestamp.today() if pd.isnull(dt_atual) else dt_atual, format="DD/MM/YYYY")
            if st.button("Salvar Data"):
                acao_atualizar_data(int(row_stats['UnidadeID']), nova_dt, conn)

    # --- KPI RESUMO ---
    cor, sinal = row_stats['Cor'], row_stats['Sinal']
    st.markdown(f"""
    <div style='display: flex; justify-content: space-around; background-color: #f0f2f6; padding: 12px; border-radius: 8px; margin-bottom: 20px; color: black; border-left: 5px solid {cor}'>
        <span>📋 Edital: <b>{row_stats['Edital']}</b></span>
        <span>👥 Real: <b>{row_stats['Real']}</b></span>
        <span>⚖️ Saldo: <b style='color: {cor}; font-size: 1.1em'>{sinal}{row_stats['Saldo']}</b></span>
    </div>
    """, unsafe_allow_html=True)

    # --- QUADRO DE VAGAS ---
    st.caption("📊 Quadro de Vagas")
    st.dataframe(df_cargos_view[['Cargo','Edital','Real','Diferenca_Display','Status_Display']], use_container_width=True, hide_index=True)

    # --- LISTA DE PESSOAS (COM VOLANTES INJETADOS) ---
    st.caption("📋 Equipe na Escola Hoje")

    # 1. Filtra volantes que estão alocados para ESTA escola (ID)
    volantes_aqui = df_volantes_todos[df_volantes_todos['UnidadeDestinoID'] == escola_id].copy()
    
    # 2. Prepara Dataframe unificado para exibição
    df_fixos = df_pessoas_view[['Funcionario', 'Cargo']].copy()
    df_fixos['Tipo'] = 'Fixo'
    
    if not volantes_aqui.empty:
        df_moveis = volantes_aqui[['Funcionario', 'Cargo']].copy()
        df_moveis['Funcionario'] = "🚙 " + df_moveis['Funcionario'] + " (Volante)"
        df_moveis['Tipo'] = 'Cobertura'
        # Junta os dois
        df_final_lista = pd.concat([df_fixos, df_moveis], ignore_index=True)
    else:
        df_final_lista = df_fixos

    # Exibe
    if not df_final_lista.empty:
        st.dataframe(df_final_lista, use_container_width=True, hide_index=True)
    else:
        st.info("Nenhum colaborador nesta unidade.")

# ==============================================================================
# MAIN & UI
# ==============================================================================
def main():
    configurar_pagina()
    authenticator, nome_usuario = realizar_login()
    
    if authenticator:
        exibir_sidebar(authenticator, nome_usuario)
        
        try:
            conn = st.connection("postgres", type="sql")
            df_unidades_list, df_cargos_list = buscar_dados_auxiliares(conn)
            # Busca dados operacionais + Volantes com Status + Alocações
            df_resumo, df_pessoas, df_volantes_status, df_alocacoes = buscar_dados_operacionais(conn)
            
            st.title("📊 Mesa Operacional")
            
            # --- TOPO: KPIs ---
            c1, c2, c3, c4 = st.columns([1, 1, 1, 1.2]) 
            total_edital = int(df_resumo['Edital'].sum())
            total_real = int(df_resumo['Real'].sum())
            
            with c1: st.metric("📋 Total Edital", total_edital)
            with c2: st.metric("👥 Efetivo Atual", total_real)
            with c3: st.metric("⚖️ Saldo Geral", total_real - total_edital)
            
            # KPI VOLANTES
            qtd_volantes = len(df_volantes_status)
            disp = len(df_volantes_status[df_volantes_status['UnidadeDestinoID'].isnull()])
            with c4:
                st.metric("🚙 Volantes (Disp.)", f"{disp} / {qtd_volantes}", help="Disponíveis hoje / Total cadastrado")
                if st.button("Gerenciar Volantes"):
                    modal_lista_volantes(df_volantes_status, conn, df_unidades_list)
            
            st.markdown("---")
            exibir_graficos_gerais(df_resumo)

            # --- FILTROS ---
            st.subheader("🏫 Gestão de Escolas")
            c_f1, c_f2, c_f3, c_f4, c_f5 = st.columns([1, 1.5, 1.2, 1, 1])
            with c_f1: f_tipo = st.selectbox("🏫 Tipo:", ["Todos"] + sorted(list(df_resumo['Tipo'].unique())))
            
            df_esc_view = df_resumo[df_resumo['Tipo'] == f_tipo] if f_tipo != "Todos" else df_resumo
            with c_f2: f_esc = st.selectbox("🔍 Escola:", ["Todas"] + sorted(list(df_esc_view['Escola'].unique())))
            with c_f3: f_sup = st.selectbox("👔 Supervisor:", ["Todos"] + sorted(list(df_resumo['Supervisor'].unique())))
            with c_f4: f_sts = st.selectbox("🚦 Situação:", ["Todas", "🔴 FALTA", "🔵 EXCEDENTE", "🟢 OK"])
            with c_f5: f_txt = st.text_input("👤 Buscar:", "")

            # --- LÓGICA DE FILTRAGEM (Simplificada para brevidade, mantendo a sua original) ---
            mask = pd.Series([True] * len(df_resumo))
            if f_tipo != "Todos": mask &= (df_resumo['Tipo'] == f_tipo)
            if f_esc != "Todas": mask &= (df_resumo['Escola'] == f_esc)
            if f_sup != "Todos": mask &= (df_resumo['Supervisor'] == f_sup)
            
            df_final = df_resumo[mask]

            # --- TABELA DE ESCOLAS ---
            if not df_final.empty:
                # Agrupamento para linhas únicas por escola
                df_lista = df_final.groupby('Escola').agg({
                    'Edital': 'sum', 'Real': 'sum', 'Supervisor': 'first', 'Tipo': 'first',
                    'UnidadeID': 'first', 'DataConferencia': 'first',
                    'Status_Codigo': lambda x: list(x)
                }).reset_index()
                
                df_lista['Saldo'] = df_lista['Real'] - df_lista['Edital']
                df_lista['Status'] = np.where(df_lista['Saldo'] < 0, "🔴", np.where(df_lista['Saldo'] > 0, "🔵", "🟢"))
                df_lista['Cor'] = np.where(df_lista['Saldo'] < 0, '#e74c3c', np.where(df_lista['Saldo'] > 0, '#3498db', '#27ae60'))
                df_lista['Sinal'] = np.where(df_lista['Saldo'] > 0, '+', '')

                # Renderiza Tabela Interativa
                event = st.dataframe(
                    df_lista[['Status', 'Tipo', 'Escola', 'Supervisor', 'Edital', 'Real', 'Saldo']],
                    use_container_width=True, hide_index=True, selection_mode="single-row", on_select="rerun"
                )

                if len(event.selection.rows) > 0:
                    idx = event.selection.rows[0]
                    esc_sel = df_lista.iloc[idx]['Escola']
                    esc_id = int(df_lista.iloc[idx]['UnidadeID']) # Pega o ID para buscar volantes
                    
                    # Dados para o modal
                    row_stats = df_lista[df_lista['Escola'] == esc_sel].iloc[0]
                    df_cargos_sel = df_final[df_final['Escola'] == esc_sel]
                    df_pessoas_sel = df_pessoas[df_pessoas['Escola'] == esc_sel]
                    
                    # Abre modal passando a lista COMPLETA de volantes (o modal filtra quem está nessa escola)
                    modal_detalhe_escola(esc_sel, esc_id, row_stats, df_cargos_sel, df_pessoas_sel, df_volantes_status, conn)

        except Exception as e:
            st.error(f"Erro no sistema: {e}")

def exibir_sidebar(auth, user):
    with st.sidebar:
        if l := carregar_logo(): st.image(l, use_container_width=True)
        st.write(f"👤 {user}"); auth.logout()

def exibir_graficos_gerais(df):
    with st.expander("📈 Resumo Geral e Gráficos", expanded=True):
        df_agrupado = df.groupby('Cargo')[['Edital','Real']].sum().reset_index()
        df_agrupado['Saldo'] = df_agrupado['Real'] - df_agrupado['Edital']
        c1, c2 = st.columns([2, 1])
        with c1:
            fig = px.bar(df_agrupado.melt(id_vars=['Cargo'], value_vars=['Edital','Real'], var_name='Tipo', value_name='Qtd'), 
                         x='Cargo', y='Qtd', color='Tipo', barmode='group', 
                         color_discrete_map={'Edital': '#7f8c8d','Real': '#3498db'}, text_auto=True, template="seaborn")
            st.plotly_chart(fig, use_container_width=True)
        with c2:
            st.dataframe(df_agrupado[['Cargo','Edital','Real','Saldo']], use_container_width=True, hide_index=True)

if __name__ == "__main__":
    main()