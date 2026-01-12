import streamlit as st 
import streamlit_authenticator as stauth
import pandas as pd
import plotly.express as px
import numpy as np 
from PIL import Image
from sqlalchemy import text

# ==============================================================================
# CONFIGURAÇÕES
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
# BANCO DE DADOS
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
    df_resumo['Status_Codigo'] = np.select(condicoes, ['FALTA', 'EXCEDENTE'], default='OK')
    df_resumo['Status_Display'] = np.select(condicoes, ['🔴 FALTA', '🔵 EXCEDENTE'], default='🟢 OK')
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
# MODAL DE DETALHES
# ==============================================================================
@st.dialog("🏫 Detalhes da Unidade", width="large")
def modal_detalhe_escola(escola_nome, row_stats, df_cargos, df_pessoas, conn, df_unidades_list, df_cargos_list):
    
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
    df_view = df_cargos[['Cargo','Edital','Real','Diferenca_Display','Status_Display']].rename(columns={'Diferenca_Display':'Diferenca', 'Status_Display':'Status'})
    st.dataframe(df_view, use_container_width=True, hide_index=True)

    # 4. Lista de Pessoas com Edição
    st.caption("📋 Colaboradores (Selecione para Editar)")
    if not df_pessoas.empty:
        event = st.dataframe(
            df_pessoas[['ID','Funcionario','Cargo']],
            use_container_width=True, hide_index=True,
            selection_mode="single-row", on_select="rerun"
        )
        
        if len(event.selection.rows) > 0:
            idx = event.selection.rows[0]
            colab = df_pessoas.iloc[idx]
            
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
# INTERFACE PRINCIPAL
# ==============================================================================
def main():
    configurar_pagina()
    authenticator, nome_usuario = realizar_login()
    
    if authenticator:
        with st.sidebar:
            if l := carregar_logo(): st.image(l, use_container_width=True)
            st.divider()
            st.write(f"👤 **{nome_usuario}**"); authenticator.logout(location='sidebar')
        
        conn = st.connection("postgres", type="sql")
        df_unidades_list, df_cargos_list = buscar_dados_auxiliares(conn)
        df_resumo, df_pessoas = buscar_dados_operacionais(conn)
        
        st.title("📊 Mesa Operacional")
        
        # --- FILTROS ---
        c1, c2, c3, c4 = st.columns([1.5, 1.5, 1, 1.5])
        with c1: f_esc = st.selectbox("Escola", ["Todas"] + sorted(df_resumo['Escola'].unique().tolist()))
        with c2: f_sup = st.selectbox("Supervisor", ["Todos"] + sorted(df_resumo['Supervisor'].unique().tolist()))
        with c3: f_sts = st.selectbox("Situação", ["Todas", "🔴 FALTA", "🔵 EXCEDENTE", "🟢 OK"])
        with c4: f_txt = st.text_input("Buscar Pessoa", "")

        # --- PROCESSAMENTO DOS DADOS PARA A LISTA ---
        # 1. Filtra
        mask = pd.Series([True] * len(df_resumo))
        if f_esc != "Todas": mask &= (df_resumo['Escola'] == f_esc)
        if f_sup != "Todos": mask &= (df_resumo['Supervisor'] == f_sup)
        
        df_filtrado = df_resumo[mask].copy()
        cols_calc = ['Edital', 'Real']
        df_filtrado[cols_calc] = df_filtrado[cols_calc].apply(pd.to_numeric, errors='coerce').fillna(0).astype(int)
        
        # 2. Agrupa por Escola
        # Adicionado 'Tipo' na agregação
        df_lista = df_filtrado.groupby('Escola').agg({
            'Edital': 'sum', 'Real': 'sum',
            'Supervisor': 'first',
            'Tipo': 'first',  # <--- Adicionado Tipo
            'UnidadeID': 'first', 'DataConferencia': 'first',
            'Status_Codigo': lambda x: list(x)
        }).reset_index()
        
        # 3. Calcula Saldos e Status
        df_lista['Saldo'] = df_lista['Real'] - df_lista['Edital']
        
        def definir_icone(row):
            saldo = row['Saldo']
            if saldo < 0: return "🔴"
            if saldo > 0: return "🔵"
            if 'FALTA' in row['Status_Codigo']: return "🟡" 
            return "✅"

        df_lista['Icone'] = df_lista.apply(definir_icone, axis=1)
        
        # 4. Filtro Final de Status
        if f_sts != "Todas":
            mapa_filtro = {"🔴 FALTA": ["🔴", "🟡"], "🔵 EXCEDENTE": ["🔵"], "🟢 OK": ["✅"]}
            icones_validos = mapa_filtro.get(f_sts, [])
            df_lista = df_lista[df_lista['Icone'].isin(icones_validos)]

        if f_txt:
            escolas_match = df_pessoas[df_pessoas['Funcionario'].str.contains(f_txt, case=False, na=False) | 
                                     df_pessoas['ID'].astype(str).str.contains(f_txt, na=False)]['Escola'].unique()
            df_lista = df_lista[df_lista['Escola'].isin(escolas_match)]

        # Ordenação
        df_lista['sort_key'] = df_lista['Icone'].map({"🔴": 0, "🟡": 1, "🔵": 2, "✅": 3})
        df_lista = df_lista.sort_values(['sort_key', 'Escola'])

        # --- EXIBIÇÃO DA LISTA ---
        st.divider()
        st.info(f"**{len(df_lista)} Unidades Encontradas.** Clique na linha para gerenciar.")
        
        if not df_lista.empty:
            # Seleciona e renomeia colunas para exibição
            # Icone -> Status
            df_show = df_lista[['Icone', 'Tipo', 'Escola', 'Supervisor', 'Edital', 'Real', 'Saldo']].rename(columns={'Icone': 'Status'})
            
            # Função de Estilo para o Saldo (Cores)
            def colorir_saldo(val):
                if val < 0: return 'color: #ff4b4b; font-weight: bold;' # Vermelho
                elif val > 0: return 'color: #29b6f6; font-weight: bold;' # Azul
                return 'color: #00c853; font-weight: bold;' # Verde

            # Aplica o estilo apenas na coluna Saldo
            styler = df_show.style.map(colorir_saldo, subset=['Saldo'])

            event = st.dataframe(
                styler,
                use_container_width=True,
                hide_index=True,
                selection_mode="single-row",
                on_select="rerun",
                column_config={
                    "Status": st.column_config.TextColumn("Status", width="small", help="🔴 Falta | 🔵 Excedente | 🟡 Ajuste Interno | ✅ Ok"),
                    "Tipo": st.column_config.TextColumn("Tipo", width="small"),
                    "Escola": st.column_config.TextColumn("Unidade Escolar", width="large"),
                    "Saldo": st.column_config.NumberColumn("Saldo", format="%+d") # Formata com sinal (+/-)
                }
            )

            # --- AÇÃO AO CLICAR ---
            if len(event.selection.rows) > 0:
                idx = event.selection.rows[0]
                # Pega o nome da escola da linha selecionada no dataframe exibido
                # (Importante: o índice do selection corresponde ao dataframe ordenado/filtrado exibido)
                escola_sel = df_show.iloc[idx]['Escola']
                
                # Busca dados originais na df_lista (usando a escola como chave para segurança)
                row_stats = df_lista[df_lista['Escola'] == escola_sel].iloc[0]
                
                # Filtra detalhes
                df_cargos_sel = df_resumo[df_resumo['Escola'] == escola_sel]
                df_pessoas_sel = df_pessoas[df_pessoas['Escola'] == escola_sel]
                
                if f_txt:
                    df_pessoas_sel = df_pessoas_sel[df_pessoas_sel['Funcionario'].str.contains(f_txt, case=False, na=False) | 
                                                  df_pessoas_sel['ID'].astype(str).str.contains(f_txt, na=False)]

                modal_detalhe_escola(escola_sel, row_stats, df_cargos_sel, df_pessoas_sel, conn, df_unidades_list, df_cargos_list)
        else:
            st.warning("Nenhuma escola encontrada.")

if __name__ == "__main__":
    main()