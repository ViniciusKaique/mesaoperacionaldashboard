import streamlit as st 
import streamlit_authenticator as stauth
import pandas as pd
import plotly.express as px
from PIL import Image
from sqlalchemy import text

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Mesa Operacional", layout="wide", page_icon="📊")

# --- CSS PERSONALIZADO ---
st.markdown("""
<style>
    .block-container { padding-top: 1rem; }
    .stButton button { background-color: #ff4b4b; color: white; border-radius: 8px; }
    [data-testid="stMetricValue"] { font-size: 32px; font-weight: bold; }
    .dataframe { font-size: 14px !important; }
    
    th, td { text-align: center !important; }
    .stDataFrame div[data-testid="stDataFrame"] div[role="grid"] div[role="row"] div {
        justify-content: center !important;
        text-align: center !important;
    }

    /* Spinner Grande */
    div[data-testid="stSpinner"] > div {
        font-size: 28px !important; font-weight: bold !important; color: #ff4b4b !important; white-space: nowrap;
    }

    /* Botão Login */
    div.stButton > button { width: 100%; display: block; margin: 0 auto; }
</style>
""", unsafe_allow_html=True)

def carregar_logo():
    try: return Image.open("logo.png")
    except: return None

# --- AUTH CONFIG ---
try:
    auth_secrets = st.secrets["auth"]
    config = {
        'credentials': {'usernames': {auth_secrets["username"]: {'name': auth_secrets["name"], 'password': auth_secrets["password_hash"], 'email': auth_secrets["email"]}}},
        'cookie': {'name': auth_secrets["cookie_name"], 'key': auth_secrets["cookie_key"], 'expiry_days': auth_secrets["cookie_expiry_days"]}
    }
except Exception as e:
    st.error("Erro Crítico: Secrets não configurados."); st.stop()

authenticator = stauth.Authenticate(config['credentials'], config['cookie']['name'], config['cookie']['key'], config['cookie']['expiry_days'])

# --- LOGIN ---
if not st.session_state.get("authentication_status"):
    st.write(""); st.write(""); st.write(""); st.write(""); st.write("")
    col_esq, col_centro, col_dir = st.columns([3, 2, 3])
    with col_centro:
        try: authenticator.login(location='main')
        except: authenticator.login()
    if st.session_state.get("authentication_status") is False:
        with col_centro: st.error('Usuário ou senha incorretos')

# --- FUNÇÃO: EDITAR COLABORADOR (JÁ EXISTIA) ---
@st.dialog("✏️ Editar Colaborador")
def editar_colaborador(colab_data, df_unidades_all, df_cargos_all, conn):
    st.write(f"Editando: **{colab_data['Funcionario']}**")
    with st.form("form_edicao"):
        lista_escolas = df_unidades_all['NomeUnidade'].tolist()
        try: idx_escola = lista_escolas.index(colab_data['Escola'])
        except: idx_escola = 0
        nova_escola_nome = st.selectbox("🏫 Escola:", lista_escolas, index=idx_escola)

        lista_cargos = df_cargos_all['NomeCargo'].tolist()
        try: idx_cargo = lista_cargos.index(colab_data['Cargo'])
        except: idx_cargo = 0
        novo_cargo_nome = st.selectbox("💼 Cargo:", lista_cargos, index=idx_cargo)

        novo_status = st.checkbox("✅ Ativo?", value=True)
        submitted = st.form_submit_button("💾 Salvar Alterações")
        
        if submitted:
            novo_unidade_id = int(df_unidades_all[df_unidades_all['NomeUnidade'] == nova_escola_nome]['UnidadeID'].iloc[0])
            novo_cargo_id = int(df_cargos_all[df_cargos_all['NomeCargo'] == novo_cargo_nome]['CargoID'].iloc[0])
            colab_id = int(colab_data['ID'])
            
            try:
                with conn.session as session:
                    session.execute(text("UPDATE \"Colaboradores\" SET \"UnidadeID\" = :uid, \"CargoID\" = :cid, \"Ativo\" = :ativo WHERE \"ColaboradorID\" = :id"), 
                                    {"uid": novo_unidade_id, "cid": novo_cargo_id, "ativo": novo_status, "id": colab_id})
                    session.commit()
                st.toast("Atualizado!", icon="🎉"); st.rerun()
            except Exception as e: st.error(f"Erro: {e}")

# --- FUNÇÃO NOVA: ADICIONAR COLABORADOR ---
@st.dialog("➕ Adicionar Novo Colaborador")
def adicionar_colaborador(unidade_atual_id, unidade_atual_nome, df_cargos_all, conn):
    st.write(f"Adicionando colaborador em: **{unidade_atual_nome}**")
    
    with st.form("form_add"):
        nome_novo = st.text_input("Nome Completo:")
        
        lista_cargos = df_cargos_all['NomeCargo'].tolist()
        cargo_novo_nome = st.selectbox("Cargo:", lista_cargos)
        
        submit_add = st.form_submit_button("💾 Cadastrar")
        
        if submit_add:
            if not nome_novo:
                st.warning("O nome é obrigatório.")
            else:
                cargo_novo_id = int(df_cargos_all[df_cargos_all['NomeCargo'] == cargo_novo_nome]['CargoID'].iloc[0])
                
                try:
                    with conn.session as session:
                        # Query de Insert
                        sql = text("""
                            INSERT INTO "Colaboradores" ("Nome", "UnidadeID", "CargoID", "Ativo") 
                            VALUES (:nome, :uid, :cid, TRUE)
                        """)
                        session.execute(sql, {"nome": nome_novo, "uid": unidade_atual_id, "cid": cargo_novo_id})
                        session.commit()
                    st.toast("Colaborador cadastrado com sucesso!", icon="✅")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao cadastrar: {e}")

# --- SISTEMA PRINCIPAL ---
if st.session_state.get("authentication_status"):
    name = st.session_state.get("name")
    with st.sidebar:
        if logo := carregar_logo(): st.image(logo, use_container_width=True); st.divider()
        st.write(f"👤 **{name}**"); authenticator.logout(location='sidebar'); st.divider(); st.info("Painel Gerencial + Detalhe")

    try:
        conn = st.connection("postgres", type="sql")

        # Dados Auxiliares
        df_unidades_all = conn.query('SELECT "UnidadeID", "NomeUnidade" FROM "Unidades" ORDER BY "NomeUnidade"', ttl=600)
        df_cargos_all = conn.query('SELECT "CargoID", "NomeCargo" FROM "Cargos" ORDER BY "NomeCargo"', ttl=600)

        # Queries Principais
        query_resumo = """
        SELECT 
            t."NomeTipo" AS "Tipo", u."UnidadeID", u."NomeUnidade" AS "Escola", u."DataConferencia",
            s."NomeSupervisor" AS "Supervisor", c."NomeCargo" AS "Cargo", q."Quantidade" AS "Edital",
            (SELECT COUNT(*) FROM "Colaboradores" col WHERE col."UnidadeID" = u."UnidadeID" AND col."CargoID" = c."CargoID" AND col."Ativo" = TRUE) AS "Real"
        FROM "QuadroEdital" q
        JOIN "Unidades" u ON q."UnidadeID" = u."UnidadeID"
        JOIN "Cargos" c ON q."CargoID" = c."CargoID"
        JOIN "TiposUnidades" t ON u."TipoID" = t."TipoID"
        JOIN "Supervisores" s ON u."SupervisorID" = s."SupervisorID"
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

        df_resumo = conn.query(query_resumo, ttl=0, show_spinner=False)
        df_pessoas = conn.query(query_funcionarios, ttl=0, show_spinner=False)

        # Processamento
        df_resumo['Diferenca_num'] = df_resumo['Real'] - df_resumo['Edital']
        df_resumo['Diferenca_display'] = df_resumo['Diferenca_num'].apply(lambda x: f"+{x}" if x > 0 else str(int(x)))
        df_resumo['DataConferencia'] = pd.to_datetime(df_resumo['DataConferencia'])

        def define_status(row):
            diff = row['Diferenca_num']; 
            if diff < 0: return '🔴 FALTA'
            elif diff > 0: return '🔵 EXCEDENTE'
            return '🟢 OK'
        df_resumo['Status_display'] = df_resumo.apply(define_status, axis=1)
        df_resumo['Status'] = df_resumo['Status_display'].apply(lambda x: x.split(' ')[1])

        # === DASHBOARD ===
        st.title("📊 Mesa Operacional")
        c1, c2, c3 = st.columns(3)
        with c1: st.markdown("**<div style='font-size:18px'>📋 Total Edital</div>**", unsafe_allow_html=True); st.metric("", int(df_resumo['Edital'].sum()))
        with c2: st.markdown("**<div style='font-size:18px'>👥 Efetivo Atual</div>**", unsafe_allow_html=True); st.metric("", int(df_resumo['Real'].sum()))
        with c3: st.markdown("**<div style='font-size:18px'>⚖️ Saldo Geral</div>**", unsafe_allow_html=True); st.metric("", int(df_resumo['Real'].sum() - df_resumo['Edital'].sum()))

        st.markdown("---")
        with st.expander("📈 Ver Gráficos e Resumo Geral", expanded=True):
            df_por_cargo = df_resumo.groupby('Cargo')[['Edital','Real']].sum().reset_index()
            df_por_cargo['Diferenca_display'] = (df_por_cargo['Real'] - df_por_cargo['Edital']).apply(lambda x: f"+{x}" if x > 0 else str(x))
            col_g1, col_g2 = st.columns([2,1])
            with col_g1: st.plotly_chart(px.bar(df_por_cargo.melt(id_vars=['Cargo'], value_vars=['Edital','Real'], var_name='Tipo', value_name='Quantidade'), x='Cargo', y='Quantidade', color='Tipo', barmode='group', color_discrete_map={'Edital': '#808080','Real': '#00bfff'}, text_auto=True, template="seaborn"), use_container_width=True)
            with col_g2: 
                def style_table(row):
                    styles = ['text-align: center;'] * 4
                    val = str(row['Diferenca'])
                    if '-' in val: styles[3] += 'color: #ff4b4b;'
                    elif '+' in val: styles[3] += 'color: #29b6f6;'
                    else: styles[3] += 'color: #00c853;'
                    return styles
                st.dataframe(df_por_cargo[['Cargo','Edital','Real','Diferenca_display']].rename(columns={'Diferenca_display':'Diferenca'}).style.apply(style_table, axis=1), use_container_width=True, hide_index=True)

        st.markdown("---"); st.subheader("🏫 Detalhe por Escola")
        c_f1, c_f2, c_f3 = st.columns([1.2, 1.2, 1])
        with c_f1: filtro_escola = st.selectbox("🔍 Escola:", ["Todas"] + sorted(list(df_resumo['Escola'].unique())))
        with c_f2: filtro_supervisor = st.selectbox("👔 Supervisor:", ["Todos"] + sorted(list(df_resumo['Supervisor'].unique())))
        with c_f3: termo_busca = st.text_input("👤 Buscar Colaborador:", "")

        col_cargos = list(df_resumo['Cargo'].unique()); filtro_comb = {}
        cols = st.columns(5)
        for i, cargo in enumerate(col_cargos):
            with cols[i % 5]:
                if (sel := st.selectbox(cargo, ["Todos","FALTA","EXCEDENTE","OK"], key=f'f_{i}')) != "Todos": filtro_comb[cargo] = sel

        # Filtros
        mask = pd.Series([True] * len(df_resumo))
        if filtro_escola != "Todas": mask &= (df_resumo['Escola'] == filtro_escola)
        if filtro_supervisor != "Todos": mask &= (df_resumo['Supervisor'] == filtro_supervisor)
        if filtro_comb:
            escolas_validas = []
            for escola in df_resumo['Escola'].unique():
                df_e = df_resumo[df_resumo['Escola'] == escola]
                valid = True
                for c, s in filtro_comb.items():
                    row = df_e[df_e['Cargo'] == c]
                    if row.empty or row['Status'].iloc[0] != s: valid = False; break
                if valid: escolas_validas.append(escola)
            mask &= df_resumo['Escola'].isin(escolas_validas)
        if termo_busca:
            match = df_pessoas[df_pessoas['Funcionario'].str.contains(termo_busca, case=False) | df_pessoas['ID'].astype(str).str.contains(termo_busca)]['Escola'].unique()
            mask &= df_resumo['Escola'].isin(match)

        df_final = df_resumo[mask]
        st.info(f"**Encontradas {df_final['Escola'].nunique()} escolas.**")

        # === LOOP ESCOLAS ===
        for escola in df_final['Escola'].unique():
            df_e = df_final[df_final['Escola'] == escola].copy()
            status_list = df_e['Status'].tolist()
            nome_supervisor = df_e['Supervisor'].iloc[0]
            unidade_id = int(df_e['UnidadeID'].iloc[0])
            data_atual = df_e['DataConferencia'].iloc[0]
            icon = "🔴" if "FALTA" in status_list else "🔵" if "EXCEDENTE" in status_list else "✅"

            with st.expander(f"{icon} {escola}", expanded=False):
                c_sup, c_btn = st.columns([3, 1.5])
                with c_sup: st.markdown(f"**👨‍💼 Supervisor:** {nome_supervisor}")
                with c_btn:
                    label_botao = "⚠️ Pendente" if pd.isnull(data_atual) else f"📅 Conferido: {data_atual.strftime('%d/%m/%Y')}"
                    with st.popover(label_botao, use_container_width=True):
                        st.markdown("Alterar data")
                        nova_data = st.date_input("Nova Data:", value=pd.Timestamp.today() if pd.isnull(data_atual) else data_atual, format="DD/MM/YYYY", key=f"dt_{unidade_id}")
                        if st.button("💾 Salvar", key=f"save_{unidade_id}"):
                            with conn.session as session:
                                session.execute(text(f"UPDATE \"Unidades\" SET \"DataConferencia\" = '{nova_data}' WHERE \"UnidadeID\" = {unidade_id};"))
                                session.commit()
                            st.toast("Data salva!", icon="✅"); st.rerun()

                st.divider()
                st.markdown("#### 📊 Quadro de Vagas")
                d_show = df_e[['Cargo','Edital','Real','Diferenca_display','Status_display']].rename(columns={'Diferenca_display':'Diferenca','Status_display':'Status'})
                d_show[['Edital','Real']] = d_show[['Edital','Real']].astype(str)
                
                def style_escola(row):
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
                st.dataframe(d_show.style.apply(style_escola, axis=1), use_container_width=True, hide_index=True)

                # === ÁREA DE COLABORADORES COM BOTÃO DE ADICIONAR ===
                col_tit, col_bt_add = st.columns([4, 1.2])
                with col_tit: 
                    st.markdown("#### 📋 Colaboradores (Selecione para Editar)")
                with col_bt_add:
                    # BOTÃO PARA ADICIONAR NOVO COLABORADOR NESTA ESCOLA
                    if st.button("➕ Adicionar", key=f"add_btn_{unidade_id}"):
                        adicionar_colaborador(unidade_id, escola, df_cargos_all, conn)

                p_show = df_pessoas[df_pessoas['Escola'] == escola]
                if termo_busca: p_show = p_show[p_show['Funcionario'].str.contains(termo_busca, case=False) | p_show['ID'].astype(str).str.contains(termo_busca)]
                
                if not p_show.empty:
                    event = st.dataframe(p_show[['ID','Funcionario','Cargo']], use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row", key=f"grid_{unidade_id}")
                    if len(event.selection.rows) > 0:
                        idx_selecionado = event.selection.rows[0]
                        dados_colaborador = p_show.iloc[idx_selecionado]
                        editar_colaborador(dados_colaborador, df_unidades_all, df_cargos_all, conn)
                else:
                    st.warning("Nenhum colaborador encontrado.")

    except Exception as e:
        st.error(f"Erro no sistema: {e}")