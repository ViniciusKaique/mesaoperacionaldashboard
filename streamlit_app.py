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

    div[data-testid="stSpinner"] > div {
        font-size: 28px !important; font-weight: bold !important; color: #ff4b4b !important; white-space: nowrap;
    }

    div.stButton > button { width: 100%; display: block; margin: 0 auto; }

    /* BOTÃO MINIMALISTA */
    div[data-testid="stExpanderDetails"] .stButton button {
        background-color: transparent !important;   
        border: none !important;
        color: #29b6f6 !important;
        border-radius: 50% !important;              
        width: 32px !important; height: 32px !important; padding: 0 !important;
        font-size: 20px !important; line-height: 1 !important;
        display: flex; align-items: center; justify-content: center; float: right;
    }
    div[data-testid="stExpanderDetails"] .stButton button:hover {
        background-color: rgba(41, 182, 246, 0.15) !important;
        transform: scale(1.1);
    }
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

# --- OTIMIZAÇÃO 1: FUNÇÃO DE CARREGAMENTO COM CACHE ---
@st.cache_data(ttl=600, show_spinner=False)
def load_data():
    conn = st.connection("postgres", type="sql")
    
    # Listas Auxiliares (Cacheada)
    df_unidades = conn.query('SELECT "UnidadeID", "NomeUnidade" FROM "Unidades" ORDER BY "NomeUnidade"')
    df_cargos = conn.query('SELECT "CargoID", "NomeCargo" FROM "Cargos" ORDER BY "NomeCargo"')

    # Queries Principais
    q_resumo = """
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
    
    q_func = """
    SELECT u."NomeUnidade" AS "Escola", c."NomeCargo" AS "Cargo", col."Nome" AS "Funcionario", col."ColaboradorID" AS "ID"
    FROM "Colaboradores" col
    JOIN "Unidades" u ON col."UnidadeID" = u."UnidadeID"
    JOIN "Cargos" c ON col."CargoID" = c."CargoID"
    WHERE col."Ativo" = TRUE
    ORDER BY u."NomeUnidade", c."NomeCargo", col."Nome";
    """
    
    df_resumo = conn.query(q_resumo)
    df_pessoas = conn.query(q_func)
    
    return df_unidades, df_cargos, df_resumo, df_pessoas

# --- FUNÇÕES DE EDIÇÃO ---
@st.dialog("✏️ Editar Colaborador")
def editar_colaborador(colab_data, df_unidades_all, df_cargos_all):
    st.write(f"Editando: **{colab_data['Funcionario']}** (ID: {colab_data['ID']})")
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
        
        if st.form_submit_button("💾 Salvar Alterações"):
            conn = st.connection("postgres", type="sql")
            novo_unidade_id = int(df_unidades_all[df_unidades_all['NomeUnidade'] == nova_escola_nome]['UnidadeID'].iloc[0])
            novo_cargo_id = int(df_cargos_all[df_cargos_all['NomeCargo'] == novo_cargo_nome]['CargoID'].iloc[0])
            colab_id = int(colab_data['ID'])
            try:
                with conn.session as session:
                    session.execute(text("UPDATE \"Colaboradores\" SET \"UnidadeID\" = :uid, \"CargoID\" = :cid, \"Ativo\" = :ativo WHERE \"ColaboradorID\" = :id"), 
                                    {"uid": novo_unidade_id, "cid": novo_cargo_id, "ativo": novo_status, "id": colab_id})
                    session.commit()
                st.cache_data.clear() # Limpa cache para atualizar dados
                st.toast("Atualizado!", icon="🎉"); st.rerun()
            except Exception as e: st.error(f"Erro: {e}")

@st.dialog("➕ Novo Colaborador")
def adicionar_colaborador(unidade_atual_id, unidade_atual_nome, df_cargos_all):
    st.caption(f"Cadastrando na unidade: **{unidade_atual_nome}**")
    with st.form("form_add"):
        c1, c2 = st.columns([1, 2])
        with c1: novo_id = st.number_input("Matrícula (ID):", min_value=1, step=1, format="%d")
        with c2: nome_novo = st.text_input("Nome Completo:")
        cargo_novo_nome = st.selectbox("Cargo:", df_cargos_all['NomeCargo'].tolist())
        
        if st.form_submit_button("💾 Cadastrar"):
            if not nome_novo: st.warning("Nome é obrigatório."); st.stop()
            conn = st.connection("postgres", type="sql")
            
            # Verifica ID (Sem cache para garantir unicidade)
            res = conn.query(f'SELECT count(*) FROM "Colaboradores" WHERE "ColaboradorID" = {novo_id}', ttl=0)
            if res.iloc[0,0] > 0: st.error(f"Erro: ID {novo_id} já existe!")
            else:
                cargo_novo_id = int(df_cargos_all[df_cargos_all['NomeCargo'] == cargo_novo_nome]['CargoID'].iloc[0])
                try:
                    with conn.session as session:
                        sql = text("INSERT INTO \"Colaboradores\" (\"ColaboradorID\", \"Nome\", \"UnidadeID\", \"CargoID\", \"Ativo\") VALUES (:id, :nome, :uid, :cid, TRUE)")
                        session.execute(sql, {"id": novo_id, "nome": nome_novo, "uid": unidade_atual_id, "cid": cargo_novo_id})
                        session.commit()
                    st.cache_data.clear() # Limpa cache
                    st.toast("Cadastrado!", icon="✅"); st.rerun()
                except Exception as e: st.error(f"Erro: {e}")

# --- SISTEMA PRINCIPAL ---
if st.session_state.get("authentication_status"):
    name = st.session_state.get("name")
    with st.sidebar:
        if logo := carregar_logo(): st.image(logo, use_container_width=True); st.divider()
        st.write(f"👤 **{name}**"); authenticator.logout(location='sidebar'); st.divider(); st.info("Painel Gerencial + Detalhe")

    try:
        # Carrega dados do Cache (MUITO MAIS RÁPIDO)
        with st.spinner("🕵️‍♂️ Carregando dados..."):
            df_unidades_all, df_cargos_all, df_resumo, df_pessoas = load_data()

        # OTIMIZAÇÃO 2: Pré-cálculos vetorizados (Rápido)
        df_resumo['Diferenca_num'] = df_resumo['Real'] - df_resumo['Edital']
        df_resumo['Diferenca_display'] = df_resumo['Diferenca_num'].apply(lambda x: f"+{x}" if x > 0 else str(int(x)))
        df_resumo['DataConferencia'] = pd.to_datetime(df_resumo['DataConferencia'])

        # Lógica de Status Otimizada
        def get_status_label(diff):
            if diff < 0: return '🔴 FALTA'
            elif diff > 0: return '🔵 EXCEDENTE'
            return '🟢 OK'
        
        df_resumo['Status_display'] = df_resumo['Diferenca_num'].apply(get_status_label)
        # Extrai texto puro para filtro
        df_resumo['Status'] = df_resumo['Status_display'].str.split(' ').str[1]

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
                    if '-' in val: styles[3] += 'color: #ff4b4b; font-weight: bold;'
                    elif '+' in val: styles[3] += 'color: #29b6f6; font-weight: bold;'
                    else: styles[3] += 'color: #00c853; font-weight: bold;'
                    return styles
                st.dataframe(df_por_cargo[['Cargo','Edital','Real','Diferenca_display']].rename(columns={'Diferenca_display':'Diferenca'}).style.apply(style_table, axis=1), use_container_width=True, hide_index=True)

        st.markdown("---"); st.subheader("🏫 Detalhe por Escola")
        c_f1, c_f2, c_f3, c_f4 = st.columns([1.2, 1.2, 1, 1])
        with c_f1: filtro_escola = st.selectbox("🔍 Escola:", ["Todas"] + sorted(list(df_resumo['Escola'].unique())))
        with c_f2: filtro_supervisor = st.selectbox("👔 Supervisor:", ["Todos"] + sorted(list(df_resumo['Supervisor'].unique())))
        with c_f3: filtro_situacao = st.selectbox("🚦 Situação:", ["Todas", "🔴 FALTA", "🔵 EXCEDENTE", "🟡 AJUSTE", "🟢 OK"])
        with c_f4: termo_busca = st.text_input("👤 Buscar Colaborador:", "")

        col_cargos = list(df_resumo['Cargo'].unique()); filtro_comb = {}
        cols = st.columns(5)
        for i, cargo in enumerate(col_cargos):
            with cols[i % 5]:
                if (sel := st.selectbox(cargo, ["Todos","FALTA","EXCEDENTE","OK"], key=f'f_{i}')) != "Todos": filtro_comb[cargo] = sel

        # Filtros (Em Memória - Rápido)
        mask = pd.Series([True] * len(df_resumo))
        if filtro_escola != "Todas": mask &= (df_resumo['Escola'] == filtro_escola)
        if filtro_supervisor != "Todos": mask &= (df_resumo['Supervisor'] == filtro_supervisor)
        
        # Lógica Ajuste Otimizada
        if filtro_situacao != "Todas":
            # Agrupa por escola para calcular status
            grp = df_resumo.groupby('Escola').agg({
                'Edital': 'sum', 
                'Real': 'sum', 
                'Status': lambda x: list(x)
            })
            grp['Saldo'] = grp['Real'] - grp['Edital']
            
            def get_school_status(row):
                if row['Saldo'] == 0 and any(s != 'OK' for s in row['Status']): return "🟡 AJUSTE"
                if "FALTA" in row['Status']: return "🔴 FALTA"
                if "EXCEDENTE" in row['Status']: return "🔵 EXCEDENTE"
                return "🟢 OK"
            
            grp['FinalStatus'] = grp.apply(get_school_status, axis=1)
            valid_schools = grp[grp['FinalStatus'] == filtro_situacao].index
            mask &= df_resumo['Escola'].isin(valid_schools)

        if filtro_comb:
            # Filtro complexo de cargos (Otimizado)
            valid_schools = df_resumo.groupby('Escola').apply(lambda x: all(x[x['Cargo'] == c]['Status'].iloc[0] == s for c, s in filtro_comb.items() if not x[x['Cargo'] == c].empty))
            mask &= df_resumo['Escola'].isin(valid_schools[valid_schools].index)
            
        if termo_busca:
            match = df_pessoas[df_pessoas['Funcionario'].str.contains(termo_busca, case=False, na=False) | df_pessoas['ID'].astype(str).str.contains(termo_busca, na=False)]['Escola'].unique()
            mask &= df_resumo['Escola'].isin(match)

        df_final = df_resumo[mask]
        st.info(f"**Encontradas {df_final['Escola'].nunique()} escolas.**")

        # === LOOP ESCOLAS ===
        conn_update = st.connection("postgres", type="sql") # Conexão para updates fora do cache
        
        for escola in df_final['Escola'].unique():
            df_e = df_final[df_final['Escola'] == escola].copy()
            status_list = df_e['Status'].tolist()
            nome_supervisor = df_e['Supervisor'].iloc[0]
            unidade_id = int(df_e['UnidadeID'].iloc[0])
            data_atual = df_e['DataConferencia'].iloc[0]
            
            # Cálculos Rápidos
            total_e = df_e['Edital'].sum(); total_r = df_e['Real'].sum(); saldo = total_r - total_e
            icon = "✅"
            if saldo == 0 and any(s != 'OK' for s in status_list): icon = "🟡"
            elif "FALTA" in status_list: icon = "🔴"
            elif "EXCEDENTE" in status_list: icon = "🔵"
            
            cor = "red" if saldo < 0 else "blue" if saldo > 0 else "green"
            sinal = "+" if saldo > 0 else ""

            with st.expander(f"{icon} {escola}", expanded=False):
                c_sup, c_btn = st.columns([3, 1.5])
                with c_sup: st.markdown(f"**👨‍💼 Supervisor:** {nome_supervisor}")
                with c_btn:
                    label_botao = "⚠️ Pendente" if pd.isnull(data_atual) else f"📅 Conferido: {data_atual.strftime('%d/%m/%Y')}"
                    with st.popover(label_botao, use_container_width=True):
                        st.markdown("Alterar data")
                        nova_data = st.date_input("Nova Data:", value=pd.Timestamp.today() if pd.isnull(data_atual) else data_atual, format="DD/MM/YYYY", key=f"dt_{unidade_id}")
                        if st.button("💾 Salvar", key=f"save_{unidade_id}"):
                            with conn_update.session as session:
                                session.execute(text(f"UPDATE \"Unidades\" SET \"DataConferencia\" = '{nova_data}' WHERE \"UnidadeID\" = {unidade_id};"))
                                session.commit()
                            st.cache_data.clear() # Limpa cache!
                            st.toast("Data salva!", icon="✅"); st.rerun()

                st.markdown(f"""<div style='display:flex; justify-content:space-around; background-color:#262730; padding:8px; border-radius:5px; margin:5px 0 15px 0; border:1px solid #404040;'><span>📋 Edital: <b>{total_e}</b></span><span>👥 Real: <b>{total_r}</b></span><span>⚖️ Saldo: <b style='color:{cor}'>{sinal}{saldo}</b></span></div>""", unsafe_allow_html=True)

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

                c_txt, c_add = st.columns([0.95, 0.05]) 
                with c_txt: st.markdown("#### 📋 Colaboradores (Selecione para Editar)")
                with c_add:
                    if st.button("➕", key=f"add_{unidade_id}", help="Adicionar Colaborador"):
                        adicionar_colaborador(unidade_id, escola, df_cargos_all)

                p_show = df_pessoas[df_pessoas['Escola'] == escola]
                if termo_busca: p_show = p_show[p_show['Funcionario'].str.contains(termo_busca, case=False, na=False) | p_show['ID'].astype(str).str.contains(termo_busca, na=False)]
                
                if not p_show.empty:
                    event = st.dataframe(p_show[['ID','Funcionario','Cargo']], use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row", key=f"grid_{unidade_id}")
                    if len(event.selection.rows) > 0:
                        editar_colaborador(p_show.iloc[event.selection.rows[0]], df_unidades_all, df_cargos_all)
                else:
                    st.warning("Nenhum colaborador encontrado.")

    except Exception as e:
        st.error(f"Erro no sistema: {e}")