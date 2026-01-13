import streamlit as st 
import streamlit_authenticator as stauth
import pandas as pd
import plotly.express as px
import numpy as np 
from PIL import Image
from sqlalchemy import text
from datetime import datetime

# ==============================================================================
# CONFIGURAÇÕES E CONSTANTES
# ==============================================================================
ID_VOLANTES = 101092601 # ID da Unidade de origem dos Volantes

def configurar_pagina():
    st.set_page_config(page_title="Mesa Operacional", layout="wide", page_icon="📊")
    st.markdown("""
    <style>
        .block-container { padding-top: 1rem; }
        [data-testid="stMetricValue"] { font-size: 32px; font-weight: bold; }
        
        /* Centralizar textos nas tabelas */
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
    # --- 1. Query Resumo (QUADRO DE VAGAS OFICIAL) ---
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
    
    # --- 2. Query Funcionários (OFICIAL FIXO) ---
    query_funcionarios = """
    SELECT u."UnidadeID", u."NomeUnidade" AS "Escola", c."NomeCargo" AS "Cargo", col."Nome" AS "Funcionario", col."ColaboradorID" AS "ID"
    FROM "Colaboradores" col
    JOIN "Unidades" u ON col."UnidadeID" = u."UnidadeID"
    JOIN "Cargos" c ON col."CargoID" = c."CargoID"
    WHERE col."Ativo" = TRUE
    ORDER BY u."NomeUnidade", c."NomeCargo", col."Nome";
    """

    # --- 3. Query Alocação de Volantes (TABELA ESPECIFICA) ---
    # Assume que a tabela AlocacaoVolantes tem: AlocacaoID, ColaboradorID, UnidadeID, Ativo
    query_alocacoes = """
    SELECT 
        av."AlocacaoID",
        av."UnidadeID",
        u."NomeUnidade" as "EscolaDestino",
        av."ColaboradorID",
        col."Nome" as "Volante",
        c."NomeCargo" as "Cargo"
    FROM "AlocacaoVolantes" av
    JOIN "Colaboradores" col ON av."ColaboradorID" = col."ColaboradorID"
    JOIN "Cargos" c ON col."CargoID" = c."CargoID"
    JOIN "Unidades" u ON av."UnidadeID" = u."UnidadeID"
    WHERE av."Ativo" = TRUE
    """

    df_resumo = _conn.query(query_resumo)
    df_pessoas = _conn.query(query_funcionarios)
    
    # Tenta buscar alocações, se a tabela não existir, cria DF vazio para não quebrar
    try:
        df_alocacoes = _conn.query(query_alocacoes)
    except:
        df_alocacoes = pd.DataFrame(columns=["AlocacaoID", "UnidadeID", "EscolaDestino", "ColaboradorID", "Volante", "Cargo"])

    # --- PROCESSAMENTO ---
    
    # 1. Isolar quem é volante na tabela de pessoas (quem tem cargo/unidade de volante)
    df_todos_volantes = df_pessoas[df_pessoas['UnidadeID'] == ID_VOLANTES].copy()
    
    # 2. Limpar DataFrame principal (Tirar volantes da visão de escolas, se estivessem lá)
    df_resumo = df_resumo[df_resumo['UnidadeID'] != ID_VOLANTES]
    df_pessoas = df_pessoas[df_pessoas['UnidadeID'] != ID_VOLANTES]

    # Lógica de Status (Texto Puro)
    condicoes = [df_resumo['Diferenca_num'] < 0, df_resumo['Diferenca_num'] > 0]
    df_resumo['Status_Codigo'] = np.select(condicoes, ['FALTA', 'EXCEDENTE'], default='OK')
    
    # Emojis VISUAIS (Bolinhas)
    df_resumo['Status_Display'] = np.select(condicoes, ['🔴 FALTA', '🔵 EXCEDENTE'], default='🟢 OK')
    
    df_resumo['Diferenca_Display'] = df_resumo['Diferenca_num'].apply(lambda x: f"+{x}" if x > 0 else str(int(x)))
    df_resumo['DataConferencia'] = pd.to_datetime(df_resumo['DataConferencia'])
    
    return df_resumo, df_pessoas, df_todos_volantes, df_alocacoes

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
# MODAIS (DIALOGS)
# ==============================================================================

@st.dialog("🏫 Detalhes da Unidade", width="large")
def modal_detalhe_escola(escola_nome, row_stats, df_cargos_view, df_pessoas_view, conn, df_unidades_list, df_cargos_list, df_todos_volantes, df_alocacoes):
    
    unidade_id_atual = int(row_stats['UnidadeID'])

    # 1. Info e Data
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
                acao_atualizar_data(unidade_id_atual, nova_dt, conn)

    # 2. Resumo Visual
    cor_resumo = row_stats['Cor']
    sinal_resumo = row_stats['Sinal']
    st.markdown(f"""
    <div style='display: flex; justify-content: space-around; background-color: #f0f2f6; padding: 12px; border-radius: 8px; margin-bottom: 20px; color: black; border-left: 5px solid {cor_resumo}'>
        <span>📋 Edital: <b>{row_stats['Edital']}</b></span>
        <span>👥 Real: <b>{row_stats['Real']}</b></span>
        <span>⚖️ Saldo: <b style='color: {cor_resumo}; font-size: 1.1em'>{sinal_resumo}{row_stats['Saldo']}</b></span>
    </div>
    """, unsafe_allow_html=True)

    # 3. Tabela de Cargos
    st.caption("📊 Quadro de Vagas (Funcionários Fixos)")
    df_view = df_cargos_view[['Cargo','Edital','Real','Diferenca_Display','Status_Display']].rename(columns={'Diferenca_Display':'Diferenca', 'Status_Display':'Status'})
    st.dataframe(df_view, use_container_width=True, hide_index=True)

    # 4. Edição de Funcionários Fixos
    st.caption("📋 Colaboradores Fixos (Selecione para Editar)")
    if not df_pessoas_view.empty:
        event = st.dataframe(
            df_pessoas_view[['ID','Funcionario','Cargo']],
            use_container_width=True, hide_index=True,
            selection_mode="single-row", on_select="rerun"
        )
        
        if len(event.selection.rows) > 0:
            idx = event.selection.rows[0]
            colab = df_pessoas_view.iloc[idx]
            
            with st.expander(f"✏️ Editar Fixo: {colab['Funcionario']}", expanded=True):
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
                    
                    if st.form_submit_button("💾 Salvar Alteração"):
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
        st.info("Nenhum colaborador fixo nesta unidade.")

    # ==========================================================
    # 5. GESTÃO DE VOLANTES (USANDO TABELA ALOCACAOVOLANTES)
    # ==========================================================
    st.divider()
    st.markdown("#### 🚙 Volantes em Apoio")
    
    # 5.1 Mostrar Volantes Atualmente Alocados AQUI
    volantes_aqui = df_alocacoes[df_alocacoes['UnidadeID'] == unidade_id_atual]
    
    if not volantes_aqui.empty:
        st.info(f"Há {len(volantes_aqui)} volante(s) cobrindo esta unidade.")
        
        # Exibe com botão de remover
        for index, row in volantes_aqui.iterrows():
            c_v1, c_v2, c_v3 = st.columns([3, 2, 1])
            with c_v1: st.write(f"**{row['Volante']}**")
            with c_v2: st.caption(f"{row['Cargo']}")
            with c_v3:
                if st.button("❌", key=f"del_aloc_{row['AlocacaoID']}", help="Remover alocação"):
                    try:
                        with conn.session as s:
                            # Opção A: Delete fisico
                            # s.execute(text('DELETE FROM "AlocacaoVolantes" WHERE "AlocacaoID" = :aid'), {'aid': row['AlocacaoID']})
                            # Opção B: Soft Delete (Update Ativo = False) -> Mais seguro
                            s.execute(text('UPDATE "AlocacaoVolantes" SET "Ativo" = FALSE WHERE "AlocacaoID" = :aid'), {'aid': row['AlocacaoID']})
                            s.commit()
                        st.cache_data.clear()
                        st.toast("Volante liberado!", icon="👋")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro: {e}")
    else:
        st.caption("Nenhum volante alocado nesta escola no momento.")

    # 5.2 Formulário para Alocar Novo Volante
    with st.expander("➕ Adicionar Volante (Alocação Temporária)"):
        # Filtra volantes que NÃO estão alocados em lugar nenhum (para não duplicar)
        # Pega IDs de todos que estão na tabela AlocacaoVolantes como Ativos
        ids_alocados = df_alocacoes['ColaboradorID'].unique().tolist()
        
        # Filtra o DF de todos os volantes
        volantes_disponiveis = df_todos_volantes[~df_todos_volantes['ID'].isin(ids_alocados)]
        
        if not volantes_disponiveis.empty:
            with st.form("form_alocar_volante"):
                lista_nomes = volantes_disponiveis['Funcionario'].tolist()
                nome_sel = st.selectbox("Selecione o Volante Disponível:", lista_nomes)
                
                if st.form_submit_button("📍 Alocar Nesta Escola"):
                    try:
                        id_volante = int(volantes_disponiveis[volantes_disponiveis['Funcionario'] == nome_sel]['ID'].iloc[0])
                        
                        # INSERE NA TABELA DE ALOCAÇÃO (Mantendo o cadastro dele na unidade de origem)
                        with conn.session as s:
                            s.execute(text("""
                                INSERT INTO "AlocacaoVolantes" ("UnidadeID", "ColaboradorID", "DataInicio", "Ativo")
                                VALUES (:uid, :cid, :dt, TRUE)
                            """), {'uid': unidade_id_atual, 'cid': id_volante, 'dt': datetime.now()})
                            s.commit()
                        
                        st.cache_data.clear()
                        st.toast(f"{nome_sel} alocado com sucesso!", icon="✅")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro ao alocar: {e}")
        else:
            st.warning("Não há volantes livres no momento.")


# ==============================================================================
# COMPONENTES VISUAIS
# ==============================================================================
def exibir_sidebar(authenticator, nome_usuario):
    with st.sidebar:
        if logo := carregar_logo(): st.image(logo, use_container_width=True)
        st.divider()
        st.write(f"👤 **{nome_usuario}**"); authenticator.logout(location='sidebar')

def exibir_metricas_topo(df, df_todos, df_alocados):
    c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
    
    total_edital = int(df['Edital'].sum())
    total_real = int(df['Real'].sum())
    saldo = total_real - total_edital
    
    with c1: st.metric("📋 Total Edital", total_edital)
    with c2: st.metric("👥 Efetivo Atual", total_real)
    with c3: st.metric("⚖️ Saldo Geral", saldo, delta_color="normal")
    
    # KPI Volantes
    total_v = len(df_todos)
    ocupados_v = len(df_alocados)
    livres_v = total_v - ocupados_v
    
    with c4:
        st.metric("🚙 Volantes (Livres)", f"{livres_v}/{total_v}", help="Volantes não alocados / Total de volantes")
            
    st.markdown("---")

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
            
            # Busca os dados, incluindo a tabela de alocação separada
            df_resumo, df_pessoas, df_todos_volantes, df_alocacoes = buscar_dados_operacionais(conn)
            
            st.title("📊 Mesa Operacional")
            
            # Passando dados para topo
            exibir_metricas_topo(df_resumo, df_todos_volantes, df_alocacoes)
            
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

            # --- FILTROS AVANÇADOS ---
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

                if len(event.selection.rows) > 0:
                    idx = event.selection.rows[0]
                    esc_sel = df_lista.iloc[idx]['Escola']
                    
                    row_stats = df_lista[df_lista['Escola'] == esc_sel].iloc[0]
                    df_cargos_sel = df_view[df_view['Escola'] == esc_sel]
                    df_pessoas_sel = df_pessoas[df_pessoas['Escola'] == esc_sel]
                    
                    if f_txt:
                        df_pessoas_sel = df_pessoas_sel[df_pessoas_sel['Funcionario'].str.contains(f_txt, case=False, na=False) | 
                                                                                df_pessoas_sel['ID'].astype(str).str.contains(f_txt, na=False)]

                    # Passamos os Dataframes de Volantes e Alocações
                    modal_detalhe_escola(esc_sel, row_stats, df_cargos_sel, df_pessoas_sel, conn, df_unidades_list, df_cargos_list, df_todos_volantes, df_alocacoes)
            
            else:
                st.warning("Nenhum resultado para os filtros aplicados.")

        except Exception as e:
            st.error(f"Erro no sistema: {e}")

if __name__ == "__main__":
    main()