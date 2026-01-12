import streamlit as st 
import streamlit_authenticator as stauth
import pandas as pd
import plotly.express as px
import numpy as np 
import time
from PIL import Image
from sqlalchemy import text

# ==============================================================================
# 1. CONFIGURAÇÃO GERAL E ESTILOS
# ==============================================================================
st.set_page_config(page_title="Mesa Operacional", layout="wide", page_icon="🏫")

st.markdown("""
<style>
    .block-container { padding-top: 1rem; }
    [data-testid="stMetricValue"] { font-size: 32px; font-weight: bold; }
    
    /* Centralizar textos nas tabelas */
    .stDataFrame div[data-testid="stDataFrame"] div[role="grid"] div[role="row"] div {
        justify-content: center !important;
        text-align: center !important;
    }
    
    /* Coluna Status compacta */
    [data-testid="stDataFrame"] div[role="grid"] div[role="row"] div:nth-child(2) {
        max-width: 50px !important;
        min-width: 40px !important;
    }
    
    div.stButton > button { width: 100%; display: block; margin: 0 auto; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 2. FUNÇÕES DE SUPORTE (LOGIN / DB)
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
        t."NomeTipo" AS "Tipo", u."UnidadeID", u."NomeUnidade" AS "Escola", u."DataConferencia",
        s."NomeSupervisor" AS "Supervisor", c."NomeCargo" AS "Cargo", 
        q."Quantidade" AS "Edital", COALESCE(cr."QtdReal", 0) AS "Real",
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
    SELECT u."NomeUnidade" AS "Escola", c."NomeCargo" AS "Cargo", col."Nome" AS "Funcionario", col."ColaboradorID" AS "ID", col."Ativo"
    FROM "Colaboradores" col
    JOIN "Unidades" u ON col."UnidadeID" = u."UnidadeID"
    JOIN "Cargos" c ON col."CargoID" = c."CargoID"
    WHERE col."Ativo" = TRUE
    ORDER BY col."Nome";
    """
    df_resumo = _conn.query(query_resumo)
    df_pessoas = _conn.query(query_funcionarios)

    condicoes = [df_resumo['Diferenca_num'] < 0, df_resumo['Diferenca_num'] > 0]
    df_resumo['Status_Codigo'] = np.select(condicoes, ['FALTA', 'EXCEDENTE'], default='OK')
    df_resumo['Status_Display'] = np.select(condicoes, ['🔴 FALTA', '🔵 EXCEDENTE'], default='🟢 OK')
    df_resumo['Diferenca_Display'] = df_resumo['Diferenca_num'].apply(lambda x: f"+{x}" if x > 0 else str(int(x)))
    df_resumo['DataConferencia'] = pd.to_datetime(df_resumo['DataConferencia'])
    return df_resumo, df_pessoas

def acao_atualizar_data(unidade_id, nova_data, conn):
    try:
        with conn.session as session:
            session.execute(text('UPDATE "Unidades" SET "DataConferencia" = :d WHERE "UnidadeID" = :u'), {'d': nova_data, 'u': unidade_id})
            session.commit()
        st.cache_data.clear()
        st.toast("Data atualizada!", icon="✅")
        st.rerun()
    except Exception as e: st.error(f"Erro: {e}")

# ==============================================================================
# 3. COMPONENTE: MODAL DE DETALHES COM EDIÇÃO EM MASSA (DATA_EDITOR)
# ==============================================================================
@st.dialog("🏫 Detalhes da Unidade", width="large")
def modal_detalhe_escola(escola_nome, row_stats, df_cargos_view, df_pessoas_view, conn, df_unidades_list, df_cargos_list):
    
    # Atualiza a URL para permitir deep linking (Feature 4)
    st.query_params["escola"] = escola_nome

    # 1. Cabeçalho
    c1, c2 = st.columns([2, 1])
    with c1:
        st.markdown(f"**Supervisor:** {row_stats['Supervisor']} | **Tipo:** {row_stats['Tipo']}")
    with c2:
        dt_atual = row_stats['DataConferencia']
        lbl = "⚠️ Pendente" if pd.isnull(dt_atual) else f"📅 {dt_atual.strftime('%d/%m/%Y')}"
        with st.popover(lbl, use_container_width=True):
            nova_dt = st.date_input("Data:", value=pd.Timestamp.today() if pd.isnull(dt_atual) else dt_atual, format="DD/MM/YYYY")
            if st.button("Salvar Data"): acao_atualizar_data(int(row_stats['UnidadeID']), nova_dt, conn)

    # 2. Métricas
    cor, sinal = row_stats['Cor'], row_stats['Sinal']
    st.markdown(f"""
    <div style='display: flex; justify-content: space-around; background-color: #f0f2f6; padding: 12px; border-radius: 8px; margin-bottom: 20px; color: black; border-left: 5px solid {cor}'>
        <span>📋 Edital: <b>{row_stats['Edital']}</b></span>
        <span>👥 Real: <b>{row_stats['Real']}</b></span>
        <span>⚖️ Saldo: <b style='color: {cor}; font-size: 1.1em'>{sinal}{row_stats['Saldo']}</b></span>
    </div>""", unsafe_allow_html=True)

    # 3. Quadro de Vagas
    st.caption("📊 Quadro de Vagas")
    df_show = df_cargos_view[['Cargo','Edital','Real','Diferenca_Display','Status_Display']].rename(columns={'Diferenca_Display':'Diferenca', 'Status_Display':'Status'})
    st.dataframe(df_show, use_container_width=True, hide_index=True)

    # 4. Edição em Massa (Feature 1: st.data_editor)
    st.divider()
    st.caption("✏️ **Gerenciamento de Colaboradores** (Edite diretamente na tabela)")
    
    if not df_pessoas_view.empty:
        # Prepara dataframe para edição
        df_editavel = df_pessoas_view[['ID', 'Funcionario', 'Cargo', 'Escola']].copy()
        df_editavel['Ativo'] = True # Default para visualização
        
        # Configurações do Editor
        list_escolas = sorted(df_unidades_list['NomeUnidade'].unique().tolist())
        list_cargos = sorted(df_cargos_list['NomeCargo'].unique().tolist())

        edited_df = st.data_editor(
            df_editavel,
            column_config={
                "ID": st.column_config.NumberColumn("ID", disabled=True, width="small"),
                "Funcionario": st.column_config.TextColumn("Nome", disabled=True),
                "Escola": st.column_config.SelectboxColumn("Unidade", options=list_escolas, width="medium", required=True),
                "Cargo": st.column_config.SelectboxColumn("Cargo", options=list_cargos, width="medium", required=True),
                "Ativo": st.column_config.CheckboxColumn("Ativo?", default=True)
            },
            hide_index=True,
            use_container_width=True,
            key=f"editor_{row_stats['UnidadeID']}"
        )

        if st.button("💾 Salvar Alterações", use_container_width=True, type="primary"):
            # Lógica de Comparação e Update
            alteracoes = 0
            with conn.session as session:
                for index, row in edited_df.iterrows():
                    original = df_editavel.loc[index]
                    
                    # Verifica se houve mudança
                    mudou_escola = row['Escola'] != original['Escola']
                    mudou_cargo = row['Cargo'] != original['Cargo']
                    mudou_ativo = row['Ativo'] != True # Se desmarcou, é false
                    
                    if mudou_escola or mudou_cargo or mudou_ativo:
                        uid_new = int(df_unidades_list[df_unidades_list['NomeUnidade'] == row['Escola']]['UnidadeID'].iloc[0])
                        cid_new = int(df_cargos_list[df_cargos_list['NomeCargo'] == row['Cargo']]['CargoID'].iloc[0])
                        
                        session.execute(
                            text('UPDATE "Colaboradores" SET "UnidadeID"=:u, "CargoID"=:c, "Ativo"=:a WHERE "ColaboradorID"=:i'),
                            {'u': uid_new, 'c': cid_new, 'a': row['Ativo'], 'i': int(row['ID'])}
                        )
                        alteracoes += 1
                session.commit()
            
            if alteracoes > 0:
                st.cache_data.clear()
                st.toast(f"{alteracoes} registros atualizados!", icon="🎉")
                time.sleep(1)
                st.rerun()
            else:
                st.info("Nenhuma alteração detectada.")
    else:
        st.info("Nenhum colaborador alocado.")

# ==============================================================================
# 4. DASHBOARD LOGIC (WRAPPED FOR NAVIGATION)
# ==============================================================================
def exibir_painel_conae():
    conn = st.connection("postgres", type="sql")
    df_unidades, df_cargos = buscar_dados_auxiliares(conn)
    df_resumo, df_pessoas = buscar_dados_operacionais(conn)

    # --- MÉTRICAS GERAIS (ESTÁTICAS) ---
    c1, c2, c3 = st.columns(3)
    c1.metric("📋 Total Edital", int(df_resumo['Edital'].sum()))
    c2.metric("👥 Efetivo Atual", int(df_resumo['Real'].sum()))
    saldo_total = int(df_resumo['Real'].sum()) - int(df_resumo['Edital'].sum())
    c3.metric("⚖️ Saldo Geral", saldo_total, delta_color="normal")
    st.markdown("---")

    # --- ÁREA REATIVA (FEATURE 2: ST.FRAGMENT) ---
    @st.fragment
    def renderizar_filtros_e_tabela():
        st.subheader("🏫 Gestão de Escolas")
        
        # Filtros
        c1, c2, c3, c4, c5 = st.columns([1, 1.5, 1.2, 1, 1])
        with c1: f_tipo = st.selectbox("🏫 Tipo:", ["Todos"] + sorted(list(df_resumo['Tipo'].unique())))
        
        df_esc_view = df_resumo[df_resumo['Tipo'] == f_tipo] if f_tipo != "Todos" else df_resumo
        with c2: f_esc = st.selectbox("🔍 Escola:", ["Todas"] + sorted(list(df_esc_view['Escola'].unique())))
        with c3: f_sup = st.selectbox("👔 Supervisor:", ["Todos"] + sorted(list(df_resumo['Supervisor'].unique())))
        with c4: f_sts = st.selectbox("🚦 Situação:", ["Todas", "🔴 FALTA", "🔵 EXCEDENTE", "🟡 AJUSTE", "🟢 OK"])
        with c5: f_txt = st.text_input("👤 Buscar:", "")

        # Feature 3: ST.TOGGLE
        filtro_comb = {}
        if st.toggle("🔎 Filtros Avançados (Por Cargo)"):
            with st.container(border=True):
                cols = st.columns(5)
                for i, cargo in enumerate(sorted(df_resumo['Cargo'].unique())):
                    with cols[i % 5]:
                        if (sel := st.selectbox(cargo, ["Todos","FALTA","EXCEDENTE","OK"], key=f'fc_{i}')) != "Todos":
                            filtro_comb[cargo] = sel

        # Lógica de Filtragem
        mask = pd.Series([True] * len(df_resumo))
        if f_tipo != "Todos": mask &= (df_resumo['Tipo'] == f_tipo)
        if f_esc != "Todas": mask &= (df_resumo['Escola'] == f_esc)
        if f_sup != "Todos": mask &= (df_resumo['Supervisor'] == f_sup)
        
        if f_sts != "Todas":
            agg = df_resumo.groupby('Escola').agg({'Edital': 'sum', 'Real': 'sum', 'Status_Codigo': list}).reset_index()
            agg['Saldo'] = agg['Real'] - agg['Edital']
            conds = [agg['Saldo'] < 0, agg['Saldo'] > 0, (agg['Saldo'] == 0) & (agg['Status_Codigo'].apply(lambda x: 'OK' not in x or any(s != 'OK' for s in x)))]
            agg['Sts_Calc'] = np.select(conds, ["🔴 FALTA", "🔵 EXCEDENTE", "🟡 AJUSTE"], default="🟢 OK")
            
            alvos = []
            if f_sts == "🔴 FALTA": alvos = ["🔴 FALTA", "🟡 AJUSTE"]
            elif f_sts == "🔵 EXCEDENTE": alvos = ["🔵 EXCEDENTE"]
            elif f_sts == "🟡 AJUSTE": alvos = ["🟡 AJUSTE"]
            elif f_sts == "🟢 OK": alvos = ["🟢 OK"]
            mask &= df_resumo['Escola'].isin(agg[agg['Sts_Calc'].isin(alvos)]['Escola'])

        if filtro_comb:
            for c, s in filtro_comb.items():
                mask &= df_resumo['Escola'].isin(df_resumo[(df_resumo['Cargo'] == c) & (df_resumo['Status_Codigo'] == s)]['Escola'])

        if f_txt:
            mask &= df_resumo['Escola'].isin(df_pessoas[df_pessoas['Funcionario'].str.contains(f_txt, case=False, na=False) | df_pessoas['ID'].astype(str).str.contains(f_txt, na=False)]['Escola'].unique())

        # Renderiza Tabela
        df_final = df_resumo[mask]
        if not df_final.empty:
            cols_num = ['Edital', 'Real']
            df_view = df_final.copy()
            df_view[cols_num] = df_view[cols_num].apply(pd.to_numeric, errors='coerce').fillna(0).astype(int)
            
            df_lista = df_view.groupby('Escola').agg({
                'Edital': 'sum', 'Real': 'sum', 'Supervisor': 'first', 'Tipo': 'first',
                'UnidadeID': 'first', 'DataConferencia': 'first', 'Status_Codigo': lambda x: list(x)
            }).reset_index()
            
            df_lista['Saldo'] = df_lista['Real'] - df_lista['Edital']
            def get_icone(row):
                s = row['Saldo']
                if s < 0: return "🔴" 
                if s > 0: return "🔵" 
                if 'FALTA' in row['Status_Codigo']: return "🟡" 
                return "🟢" 
            df_lista['Status'] = df_lista.apply(get_icone, axis=1)
            
            # Cores
            df_lista['Cor'] = np.where(df_lista['Saldo'] < 0, '#e74c3c', np.where(df_lista['Saldo'] > 0, '#3498db', '#27ae60'))
            df_lista['Sinal'] = np.where(df_lista['Saldo'] > 0, '+', '')
            
            # Ordenação
            df_lista['rank'] = df_lista['Status'].map({"🔴": 0, "🟡": 1, "🔵": 2, "🟢": 3})
            df_lista = df_lista.sort_values(['rank', 'Escola'])

            st.caption(f"**{len(df_lista)} Unidades Encontradas.**")
            
            def style_saldo(val):
                if val < 0: return 'color: #e74c3c; font-weight: bold;'
                if val > 0: return 'color: #3498db; font-weight: bold;'
                return 'color: #27ae60; font-weight: bold;'

            event = st.dataframe(
                df_lista[['Status', 'Tipo', 'Escola', 'Supervisor', 'Edital', 'Real', 'Saldo']].style.map(style_saldo, subset=['Saldo']),
                use_container_width=True, hide_index=True, selection_mode="single-row", on_select="rerun",
                column_config={"Status": st.column_config.TextColumn("Status", width="small"), "Saldo": st.column_config.NumberColumn("Saldo", format="%+d")}
            )

            # Feature 4: ST.QUERY_PARAMS (Deep Linking)
            # Verifica se clicou na tabela OU se veio parâmetro na URL
            param_escola = st.query_params.get("escola")
            escola_abrir = None

            if len(event.selection.rows) > 0:
                idx = event.selection.rows[0]
                escola_abrir = df_lista.iloc[idx]['Escola']
            elif param_escola and param_escola in df_lista['Escola'].values:
                escola_abrir = param_escola

            if escola_abrir:
                row_stats = df_lista[df_lista['Escola'] == escola_abrir].iloc[0]
                df_cargos_sel = df_final[df_final['Escola'] == escola_abrir]
                df_pessoas_sel = df_pessoas[df_pessoas['Escola'] == escola_abrir]
                modal_detalhe_escola(escola_abrir, row_stats, df_cargos_sel, df_pessoas_sel, conn, df_unidades, df_cargos)
        
        else:
            st.warning("Nenhum resultado.")

    # Executa o fragmento
    renderizar_filtros_e_tabela()

# ==============================================================================
# 5. ENTRY POINT COM ST.NAVIGATION (Feature 5)
# ==============================================================================
def main():
    authenticator, nome_usuario = realizar_login()
    
    if authenticator:
        # Menu Lateral Customizado com st.navigation
        with st.sidebar:
            if l := carregar_logo(): st.image(l, use_container_width=True)
            st.divider()
            st.write(f"👤 **{nome_usuario}**")
            authenticator.logout(location='sidebar')
            st.divider()
        
        # Definição das Páginas (Organização Profissional)
        pg = st.navigation({
            "Operacional": [
                st.Page(exibir_painel_conae, title="Mesa Operacional", icon="🏫"),
                st.Page("pages/MESA_OPERACIONAL.py", title="Monitoramento Faltas", icon="📉"),
                st.Page("pages/PORTALGESTOR_TURBO.py", title="Aprovação Turbo", icon="🚀"),
                st.Page("pages/BUSCA_CONTATOS.py", title="Busca Contatos", icon="📞"),
            ],
            "Gestão": [
                st.Page("pages/FATURAMENTO_CONAE.py", title="Faturamento", icon="💰"),
            ],
            "Clientes": [
                st.Page("pages/ARARAQUARA.py", title="Araraquara", icon="🏥"),
                st.Page("pages/SME.py", title="SME Ocorrências", icon="🔔"),
            ]
        })
        pg.run()

if __name__ == "__main__":
    main()