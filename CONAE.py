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
ID_VOLANTES = 101092601 # ID da Unidade de Volantes

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
@st.cache_data(ttl=600, show_spinner=False)
def buscar_dados_auxiliares(_conn):
    df_unidades = _conn.query('SELECT "UnidadeID", "NomeUnidade" FROM "Unidades" ORDER BY "NomeUnidade"')
    df_cargos = _conn.query('SELECT "CargoID", "NomeCargo" FROM "Cargos" ORDER BY "NomeCargo"')
    return df_unidades, df_cargos

@st.cache_data(ttl=60, show_spinner=False) 
def buscar_dados_operacionais(_conn):
    # --- QUERY ORIGINAL DO QUADRO ---
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
    
    # --- QUERY FUNCIONÁRIOS ---
    query_funcionarios = """
    SELECT u."UnidadeID", u."NomeUnidade" AS "Escola", c."NomeCargo" AS "Cargo", col."Nome" AS "Funcionario", col."ColaboradorID" AS "ID"
    FROM "Colaboradores" col
    JOIN "Unidades" u ON col."UnidadeID" = u."UnidadeID"
    JOIN "Cargos" c ON col."CargoID" = c."CargoID"
    WHERE col."Ativo" = TRUE
    ORDER BY u."NomeUnidade", c."NomeCargo", col."Nome";
    """

    # --- QUERY ALOCAÇÕES ---
    query_alocacoes = """
    SELECT av."ColaboradorID" AS "ID", av."UnidadeDestinoID", u."NomeUnidade" AS "EscolaDestino"
    FROM "AlocacaoVolantes" av
    JOIN "Unidades" u ON av."UnidadeDestinoID" = u."UnidadeID"
    WHERE av."DataAlocacao" = CURRENT_DATE
    """

    df_resumo = _conn.query(query_resumo)
    df_pessoas = _conn.query(query_funcionarios)
    
    try:
        df_alocacoes = _conn.query(query_alocacoes)
    except:
        df_alocacoes = pd.DataFrame(columns=["ID", "UnidadeDestinoID", "EscolaDestino"])

    # --- PROCESSAMENTO ---
    df_volantes_base = df_pessoas[df_pessoas['UnidadeID'] == ID_VOLANTES].copy()
    
    if not df_volantes_base.empty:
        df_volantes_status = pd.merge(df_volantes_base, df_alocacoes, on="ID", how="left")
        df_volantes_status['Status_Texto'] = np.where(df_volantes_status['UnidadeDestinoID'].notnull(), 
                                                      "Cobrindo: " + df_volantes_status['EscolaDestino'].fillna(''), 
                                                      "Disponível")
        df_volantes_status['Status_Icon'] = np.where(df_volantes_status['UnidadeDestinoID'].notnull(), "🔴", "🟢")
    else:
        df_volantes_status = pd.DataFrame()

    df_resumo = df_resumo[df_resumo['UnidadeID'] != ID_VOLANTES]
    df_pessoas = df_pessoas[df_pessoas['UnidadeID'] != ID_VOLANTES]

    condicoes = [df_resumo['Diferenca_num'] < 0, df_resumo['Diferenca_num'] > 0]
    df_resumo['Status_Codigo'] = np.select(condicoes, ['FALTA', 'EXCEDENTE'], default='OK')
    df_resumo['Status_Display'] = np.select(condicoes, ['🔴 FALTA', '🔵 EXCEDENTE'], default='🟢 OK')
    
    df_resumo['Diferenca_Display'] = df_resumo['Diferenca_num'].apply(lambda x: f"+{x}" if x > 0 else str(int(x)))
    df_resumo['DataConferencia'] = pd.to_datetime(df_resumo['DataConferencia'])
    
    return df_resumo, df_pessoas, df_volantes_status

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
# NOVAS FUNÇÕES: REGISTRO HISTÓRICO
# ==============================================================================
def registrar_historico_uso(conn):
    """Calcula e salva o % de uso dos volantes na data de hoje."""
    try:
        # 1. Conta Total de Volantes (Pessoas na unidade Volantes)
        q_total = text('SELECT COUNT(*) FROM "Colaboradores" WHERE "UnidadeID" = :uid AND "Ativo" = TRUE')
        # 2. Conta Alocados Hoje
        q_aloc = text('SELECT COUNT(*) FROM "AlocacaoVolantes" WHERE "DataAlocacao" = CURRENT_DATE')
        
        with conn.session as s:
            total = s.execute(q_total, {'uid': ID_VOLANTES}).scalar()
            alocados = s.execute(q_aloc).scalar()
            
            if total > 0:
                pct = round((alocados / total) * 100, 2)
            else:
                pct = 0.0
            
            # Upsert (Insere ou Atualiza se já existir hoje)
            s.execute(text("""
                INSERT INTO "HistoricoVolantes" ("DataRegistro", "TotalVolantes", "QtdAlocados", "PercentualUso")
                VALUES (CURRENT_DATE, :t, :a, :p)
                ON CONFLICT ("DataRegistro") 
                DO UPDATE SET "TotalVolantes" = :t, "QtdAlocados" = :a, "PercentualUso" = :p
            """), {'t': total, 'a': alocados, 'p': pct})
            s.commit()
            
    except Exception as e:
        print(f"Erro ao registrar histórico: {e}")

# ==============================================================================
# AÇÕES VOLANTES
# ==============================================================================
def acao_alocar_volante(colab_id, unidade_destino_id, conn):
    try:
        with conn.session as s:
            s.execute(text('DELETE FROM "AlocacaoVolantes" WHERE "ColaboradorID" = :id AND "DataAlocacao" = CURRENT_DATE'), {'id': colab_id})
            s.execute(text('INSERT INTO "AlocacaoVolantes" ("ColaboradorID", "UnidadeDestinoID", "DataAlocacao") VALUES (:cid, :uid, CURRENT_DATE)'),
                      {'cid': colab_id, 'uid': unidade_destino_id})
            s.commit()
        
        # Atualiza histórico
        registrar_historico_uso(conn)

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
        
        # Atualiza histórico
        registrar_historico_uso(conn)
        
        st.cache_data.clear()
        st.toast("Volante liberado!", icon="🟢")
        st.rerun()
    except Exception as e:
        st.error(f"Erro ao desalocar: {e}")

# ==============================================================================
# MODAIS
# ==============================================================================
@st.dialog("🚙 Gestão de Volantes (Diário)", width="large")
def modal_lista_volantes(df_volantes, conn, df_unidades_list, df_cargos_list):
    
    # Abas para separar Operação do Histórico
    tab_op, tab_hist = st.tabs(["🛠️ Operação Hoje", "📈 Histórico de Uso"])

    with tab_op:
        st.markdown(f"### Status do Dia: {date.today().strftime('%d/%m/%Y')}")
        
        if not df_volantes.empty:
            total = len(df_volantes)
            disponiveis = len(df_volantes[df_volantes['UnidadeDestinoID'].isnull()])
            alocados = total - disponiveis
            
            c1, c2, c3 = st.columns(3)
            c1.metric("Total", total)
            c2.metric("🟢 Disponíveis", disponiveis)
            c3.metric("🔴 Alocados", alocados)
            st.divider()

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
                    st.write(""); st.write("") 
                    if esta_alocado:
                        st.info(f"Em: **{row['EscolaDestino']}**")
                        # BOTÃO SEM COR (REMOVIDO type="primary")
                        if st.button("🔓 Liberar"):
                            acao_desalocar_volante(colab_id, conn)
                    else:
                        st.success("**Disponível**")
            
                if not esta_alocado:
                    with st.form("form_alocacao"):
                        st.write(f"Alocar **{nome_selecionado}** hoje para:")
                        lst_esc = df_unidades_list['NomeUnidade'].tolist()
                        destino = st.selectbox("Escolha a Escola:", lst_esc)
                        
                        if st.form_submit_button("🚙 Confirmar Alocação"):
                            uid_dest = int(df_unidades_list[df_unidades_list['NomeUnidade'] == destino]['UnidadeID'].iloc[0])
                            acao_alocar_volante(colab_id, uid_dest, conn)
        else:
            st.info("Nenhum volante cadastrado.")

    # Aba do Gráfico
    with tab_hist:
        try:
            df_hist = conn.query('SELECT * FROM "HistoricoVolantes" ORDER BY "DataRegistro" ASC')
            if not df_hist.empty:
                st.subheader("Evolução do Uso (%)")
                fig = px.line(df_hist, x="DataRegistro", y="PercentualUso", markers=True, 
                              title="Taxa de Ocupação da Equipe de Volantes")
                fig.update_yaxes(range=[0, 110]) # Fixa eixo y de 0 a 100+
                fig.add_hline(y=70, line_dash="dot", annotation_text="Meta (70%)", annotation_position="bottom right")
                st.plotly_chart(fig, use_container_width=True)
                
                st.caption("Dados Brutos:")
                st.dataframe(df_hist.sort_values("DataRegistro", ascending=False), use_container_width=True)
            else:
                st.info("Ainda não há histórico registrado. As informações aparecerão aqui conforme o uso diário.")
        except:
            st.warning("Tabela de histórico ainda não criada ou vazia.")

@st.dialog("🏫 Detalhes da Unidade", width="large")
def modal_detalhe_escola(escola_nome, row_stats, df_cargos_view, df_pessoas_view, conn, df_unidades_list, df_cargos_list):
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

    cor_resumo = row_stats['Cor']
    sinal_resumo = row_stats['Sinal']
    st.markdown(f"""
    <div style='display: flex; justify-content: space-around; background-color: #f0f2f6; padding: 12px; border-radius: 8px; margin-bottom: 20px; color: black; border-left: 5px solid {cor_resumo}'>
        <span>📋 Edital: <b>{row_stats['Edital']}</b></span>
        <span>👥 Real: <b>{row_stats['Real']}</b></span>
        <span>⚖️ Saldo: <b style='color: {cor_resumo}; font-size: 1.1em'>{sinal_resumo}{row_stats['Saldo']}</b></span>
    </div>
    """, unsafe_allow_html=True)

    st.caption("📊 Quadro de Vagas")
    df_view = df_cargos_view[['Cargo','Edital','Real','Diferenca_Display','Status_Display']].rename(columns={'Diferenca_Display':'Diferenca', 'Status_Display':'Status'})
    st.dataframe(df_view, use_container_width=True, hide_index=True)

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
                    
                    n_esc = st.selectbox("Mover para Escola:", lst_esc, index=i_esc)
                    n_car = st.selectbox("Alterar Cargo:", lst_car, index=i_car)
                    n_atv = st.checkbox("Manter Ativo?", value=True)
                    
                    if st.form_submit_button("💾 Confirmar Alteração"):
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
# COMPONENTES VISUAIS (CORRIGIDO PARA EVITAR ERRO DE DIALOG DUPLO)
# ==============================================================================
def exibir_sidebar(authenticator, nome_usuario):
    with st.sidebar:
        if logo := carregar_logo(): st.image(logo, use_container_width=True)
        st.divider()
        st.write(f"👤 **{nome_usuario}**"); authenticator.logout(location='sidebar')

def exibir_metricas_topo(df, conn, df_volantes, df_unidades_list, df_cargos_list):
    c1, c2, c3, c4 = st.columns([1, 1, 1, 1.2]) 
    
    total_edital = int(df['Edital'].sum())
    total_real = int(df['Real'].sum())
    saldo = total_real - total_edital
    
    with c1: st.metric("📋 Total Edital", total_edital)
    with c2: st.metric("👥 Efetivo Atual", total_real)
    with c3: st.metric("⚖️ Saldo Geral", saldo, delta_color="normal")
    
    # --- LÓGICA DE CONTROLE DO MODAL ---
    modal_aberto_aqui = False # Flag de controle

    with c4:
        if not df_volantes.empty:
            total_v = len(df_volantes)
            disp_v = len(df_volantes[df_volantes['UnidadeDestinoID'].isnull()])
            st.metric("🚙 Volantes (Disp.)", f"{disp_v} / {total_v}")
        else:
            st.metric("🚙 Volantes", "0")
            
        if st.button("Gerenciar Volantes"):
            # Garante que registra o uso atual ao abrir
            registrar_historico_uso(conn)
            
            modal_lista_volantes(df_volantes, conn, df_unidades_list, df_cargos_list)
            modal_aberto_aqui = True # Marca que abriu
            
    st.markdown("---")
    return modal_aberto_aqui # Retorna o status

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
            def cor_saldo(val):
                if val < 0: return 'color: #e74c3c; font-weight: bold;'
                if val > 0: return 'color: #3498db; font-weight: bold;'
                return 'color: #27ae60; font-weight: bold;'
            
            st.dataframe(
                df_agrupado[['Cargo','Edital','Real','Saldo']].style.map(cor_saldo, subset=['Saldo']), 
                use_container_width=True, hide_index=True,
                column_config={"Saldo": st.column_config.NumberColumn("Saldo", format="%+d")}
            )

# ==============================================================================
# MAIN (CORRIGIDO PARA EVITAR ERRO DE DIALOG DUPLO)
# ==============================================================================
def main():
    configurar_pagina()
    authenticator, nome_usuario = realizar_login()
    
    if authenticator:
        exibir_sidebar(authenticator, nome_usuario)
        
        try:
            conn = st.connection("postgres", type="sql")
            df_unidades_list, df_cargos_list = buscar_dados_auxiliares(conn)
            df_resumo, df_pessoas, df_volantes = buscar_dados_operacionais(conn)
            
            st.title("📊 Mesa Operacional")
            
            # 1. Executa o topo e recebe se o modal de volantes foi aberto
            volantes_aberto = exibir_metricas_topo(df_resumo, conn, df_volantes, df_unidades_list, df_cargos_list)
            
            exibir_graficos_gerais(df_resumo)

            st.markdown("---")
            st.subheader("🏫 Gestão de Escolas")

            # --- FILTROS ---
            c1, c2, c3, c4, c5 = st.columns([1, 1.5, 1.2, 1, 1])
            with c1: f_tipo = st.selectbox("🏫 Tipo:", ["Todos"] + sorted(list(df_resumo['Tipo'].unique())))
            df_escolas_view = df_resumo[df_resumo['Tipo'] == f_tipo] if f_tipo != "Todos" else df_resumo
            with c2: f_esc = st.selectbox("🔍 Escola:", ["Todas"] + sorted(list(df_escolas_view['Escola'].unique())))
            with c3: f_sup = st.selectbox("👔 Supervisor:", ["Todos"] + sorted(list(df_resumo['Supervisor'].unique())))
            with c4: f_sts = st.selectbox("🚦 Situação:", ["Todas", "🔴 FALTA", "🔵 EXCEDENTE", "🟡 AJUSTE", "🟢 OK"])
            with c5: f_txt = st.text_input("👤 Buscar Pessoa:", "")

            with st.expander("🔎 Filtros Avançados por Cargo"):
                cols = st.columns(5)
                filtro_comb = {}
                for i, cargo in enumerate(sorted(df_resumo['Cargo'].unique())):
                    with cols[i % 5]:
                        if (sel := st.selectbox(cargo, ["Todos","FALTA","EXCEDENTE","OK"], key=f'fc_{i}')) != "Todos":
                            filtro_comb[cargo] = sel

            # --- APLICAÇÃO DOS FILTROS ---
            mask = pd.Series([True] * len(df_resumo))
            if f_tipo != "Todos": mask &= (df_resumo['Tipo'] == f_tipo)
            if f_esc != "Todas": mask &= (df_resumo['Escola'] == f_esc)
            if f_sup != "Todos": mask &= (df_resumo['Supervisor'] == f_sup)
            
            if f_sts != "Todas":
                agg = df_resumo.groupby('Escola').agg({'Edital': 'sum', 'Real': 'sum', 'Status_Codigo': list}).reset_index()
                agg['Saldo'] = agg['Real'] - agg['Edital']
                conds = [
                    agg['Saldo'] < 0,
                    agg['Saldo'] > 0,
                    (agg['Saldo'] == 0) & (agg['Status_Codigo'].apply(lambda x: 'OK' not in x or any(s != 'OK' for s in x)))
                ]
                agg['Sts_Calc'] = np.select(conds, ["🔴 FALTA", "🔵 EXCEDENTE", "🟡 AJUSTE"], default="🟢 OK")
                alvos = []
                if f_sts == "🔴 FALTA": alvos = ["🔴 FALTA"]
                elif f_sts == "🔵 EXCEDENTE": alvos = ["🔵 EXCEDENTE"]
                elif f_sts == "🟡 AJUSTE": alvos = ["🟡 AJUSTE"]
                elif f_sts == "🟢 OK": alvos = ["🟢 OK"]
                
                escolas_validas = agg[agg['Sts_Calc'].isin(alvos)]['Escola']
                mask &= df_resumo['Escola'].isin(escolas_validas)

            if filtro_comb:
                for c, s in filtro_comb.items():
                    escolas_v = df_resumo[(df_resumo['Cargo'] == c) & (df_resumo['Status_Codigo'] == s)]['Escola']
                    mask &= df_resumo['Escola'].isin(escolas_v)

            if f_txt:
                match = df_pessoas[df_pessoas['Funcionario'].str.contains(f_txt, case=False, na=False) | 
                                 df_pessoas['ID'].astype(str).str.contains(f_txt, na=False)]['Escola'].unique()
                mask &= df_resumo['Escola'].isin(match)

            df_final = df_resumo[mask]

            # --- TABELA FINAL ---
            if not df_final.empty:
                df_view = df_final.copy()
                cols_num = ['Edital', 'Real']
                df_view[cols_num] = df_view[cols_num].apply(pd.to_numeric, errors='coerce').fillna(0).astype(int)
                
                df_lista = df_view.groupby('Escola').agg({
                    'Edital': 'sum', 'Real': 'sum',
                    'Supervisor': 'first', 'Tipo': 'first',
                    'UnidadeID': 'first', 'DataConferencia': 'first',
                    'Status_Codigo': lambda x: list(x)
                }).reset_index()
                
                df_lista['Saldo'] = df_lista['Real'] - df_lista['Edital']
                
                def get_icone(row):
                    s = row['Saldo']
                    if s < 0: return "🔴" 
                    if s > 0: return "🔵" 
                    if 'FALTA' in row['Status_Codigo']: return "🟡" 
                    return "🟢" 

                df_lista['Status'] = df_lista.apply(get_icone, axis=1)
                df_lista['Cor'] = np.where(df_lista['Saldo'] < 0, '#e74c3c', np.where(df_lista['Saldo'] > 0, '#3498db', '#27ae60'))
                df_lista['Sinal'] = np.where(df_lista['Saldo'] > 0, '+', '')
                df_lista['rank'] = df_lista['Status'].map({"🔴": 0, "🟡": 1, "🔵": 2, "🟢": 3})
                df_lista = df_lista.sort_values(['rank', 'Escola'])

                st.info(f"**{len(df_lista)} Unidades Encontradas.**")
                
                def style_saldo(val):
                    if val < 0: return 'color: #e74c3c; font-weight: bold;'
                    if val > 0: return 'color: #3498db; font-weight: bold;'
                    return 'color: #27ae60; font-weight: bold;'

                event = st.dataframe(
                    df_lista[['Status', 'Tipo', 'Escola', 'Supervisor', 'Edital', 'Real', 'Saldo']].style.map(style_saldo, subset=['Saldo']),
                    use_container_width=True,
                    hide_index=True,
                    selection_mode="single-row",
                    on_select="rerun",
                    column_config={
                        "Status": st.column_config.TextColumn("Status", width="small", help="🔴 Falta | 🔵 Excedente | 🟡 Ajuste | 🟢 Ok"),
                        "Saldo": st.column_config.NumberColumn("Saldo", format="%+d")
                    }
                )

                # CORREÇÃO AQUI: Só abre o modal da escola se o de volantes NÃO estiver aberto
                if len(event.selection.rows) > 0 and not volantes_aberto:
                    idx = event.selection.rows[0]
                    esc_sel = df_lista.iloc[idx]['Escola']
                    
                    row_stats = df_lista[df_lista['Escola'] == esc_sel].iloc[0]
                    df_cargos_sel = df_view[df_view['Escola'] == esc_sel]
                    df_pessoas_sel = df_pessoas[df_pessoas['Escola'] == esc_sel]
                    
                    if f_txt:
                        df_pessoas_sel = df_pessoas_sel[df_pessoas_sel['Funcionario'].str.contains(f_txt, case=False, na=False) | 
                                                                                df_pessoas_sel['ID'].astype(str).str.contains(f_txt, na=False)]

                    modal_detalhe_escola(esc_sel, row_stats, df_cargos_sel, df_pessoas_sel, conn, df_unidades_list, df_cargos_list)
            else:
                st.warning("Nenhum resultado para os filtros aplicados.")

        except Exception as e:
            st.error(f"Erro no sistema: {e}")

if __name__ == "__main__":
    main()