import streamlit as st 
import streamlit_authenticator as stauth
import pandas as pd
import numpy as np
import plotly.express as px
from PIL import Image
from sqlalchemy import text

# ------------------------
# Mesa Operacional - Versão Otimizada
# Substitua seu arquivo atual por este. Mantive as funcionalidades originais
# (login, diálogo de edição, atualização de data, seleção de colaborador),
# mas adicionei cache em session_state, paginação e processamento vetorizado.
# ------------------------

st.set_page_config(page_title="Mesa Operacional", layout="wide", page_icon="📊")

# --- CSS personalizado (mantenha seu estilo) ---
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
</style>
""", unsafe_allow_html=True)

# --- Helpers ---
def carregar_logo():
    try:
        return Image.open("logo.png")
    except Exception:
        return None

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

# --- DIALOG: Editar Colaborador (mantive sua lógica original, apenas leve limpeza) ---
@st.dialog("✏️ Editar Colaborador")
def editar_colaborador(colab_data, df_unidades_all, df_cargos_all, conn):
    st.write(f"Editando: **{colab_data['Funcionario']}** (ID: {colab_data['ID']})")
    with st.form("form_edicao"):
        lista_escolas = df_unidades_all['NomeUnidade'].tolist()
        try:
            idx_escola = lista_escolas.index(colab_data['Escola'])
        except Exception:
            idx_escola = 0
        nova_escola_nome = st.selectbox("🏫 Escola:", lista_escolas, index=idx_escola)

        lista_cargos = df_cargos_all['NomeCargo'].tolist()
        try:
            idx_cargo = lista_cargos.index(colab_data['Cargo'])
        except Exception:
            idx_cargo = 0
        novo_cargo_nome = st.selectbox("💼 Cargo:", lista_cargos, index=idx_cargo)

        novo_status = st.checkbox("✅ Ativo?", value=True)
        if st.form_submit_button("💾 Salvar Alterações"):
            novo_unidade_id = int(df_unidades_all[df_unidades_all['NomeUnidade'] == nova_escola_nome]['UnidadeID'].iloc[0])
            novo_cargo_id = int(df_cargos_all[df_cargos_all['NomeCargo'] == novo_cargo_nome]['CargoID'].iloc[0])
            colab_id = int(colab_data['ID'])
            try:
                with conn.session as session:
                    session.execute(text("UPDATE \"Colaboradores\" SET \"UnidadeID\" = :uid, \"CargoID\" = :cid, \"Ativo\" = :ativo WHERE \"ColaboradorID\" = :id"), 
                                    {"uid": novo_unidade_id, "cid": novo_cargo_id, "ativo": novo_status, "id": colab_id})
                    session.commit()
                st.toast("Atualizado!", icon="🎉")
                # Invalida cache relevante para refletir mudança
                st.session_state.pop("cache_resumo", None)
                st.session_state.pop("cache_pessoas", None)
                st.rerun()
            except Exception as e:
                st.error(f"Erro: {e}")

# --- LOGIN UI ---
if not st.session_state.get("authentication_status"):
    col_esq, col_centro, col_dir = st.columns([3, 2, 3])
    with col_centro:
        try:
            authenticator.login(location='main')
        except Exception:
            authenticator.login()
    if st.session_state.get("authentication_status") is False:
        with col_centro:
            st.error('Usuário ou senha incorretos')

# --- SISTEMA PRINCIPAL ---
if st.session_state.get("authentication_status"):
    name = st.session_state.get("name")
    with st.sidebar:
        if logo := carregar_logo():
            st.image(logo, use_container_width=True)
            st.divider()
        st.write(f"👤 **{name}**")
        authenticator.logout(location='sidebar')
        st.divider()
        st.info("Painel Gerencial + Detalhe")

    try:
        conn = st.connection("postgres", type="sql")

        # ---------- Cache helper (session_state) ----------
        def load_cache_query(key, query):
            # usa cache salvo a menos que force_refresh esteja True
            if st.session_state.get(f"cache_{key}") is not None and not st.session_state.get("force_refresh", False):
                return st.session_state[f"cache_{key}"]
            df = conn.query(query, ttl=0, show_spinner=False)
            st.session_state[f"cache_{key}"] = df
            return df

        # Botão lateral para forçar atualização de dados
        if st.sidebar.button("🔄 Atualizar dados do BD"):
            st.session_state["force_refresh"] = True
        else:
            st.session_state.setdefault("force_refresh", False)

        # Load lookups (cache longo)
        if st.session_state.get("cache_df_unidades_all") is None or st.session_state["force_refresh"]:
            df_unidades_all = conn.query('SELECT "UnidadeID", "NomeUnidade" FROM "Unidades" ORDER BY "NomeUnidade"', ttl=600, show_spinner=False)
            st.session_state["cache_df_unidades_all"] = df_unidades_all
        else:
            df_unidades_all = st.session_state["cache_df_unidades_all"]

        if st.session_state.get("cache_df_cargos_all") is None or st.session_state["force_refresh"]:
            df_cargos_all = conn.query('SELECT "CargoID", "NomeCargo" FROM "Cargos" ORDER BY "NomeCargo"', ttl=600, show_spinner=False)
            st.session_state["cache_df_cargos_all"] = df_cargos_all
        else:
            df_cargos_all = st.session_state["cache_df_cargos_all"]

        # Queries principais (cache curto)
        query_resumo = '''
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
        '''
        df_resumo = load_cache_query("resumo", query_resumo)

        query_funcionarios = '''
        SELECT u."NomeUnidade" AS "Escola", c."NomeCargo" AS "Cargo", col."Nome" AS "Funcionario", col."ColaboradorID" AS "ID"
        FROM "Colaboradores" col
        JOIN "Unidades" u ON col."UnidadeID" = u."UnidadeID"
        JOIN "Cargos" c ON col."CargoID" = c."CargoID"
        WHERE col."Ativo" = TRUE
        ORDER BY u."NomeUnidade", c."NomeCargo", col."Nome";
        '''
        df_pessoas = load_cache_query("pessoas", query_funcionarios)

        # reset force_refresh
        st.session_state["force_refresh"] = False

        # ---------- Processamento vetorizado ----------
        df_resumo['Diferenca_num'] = df_resumo['Real'] - df_resumo['Edital']
        df_resumo['Diferenca_display'] = df_resumo['Diferenca_num'].apply(lambda x: f"+{int(x)}" if x > 0 else str(int(x)))
        df_resumo['DataConferencia'] = pd.to_datetime(df_resumo['DataConferencia'])

        conditions = [
            df_resumo['Diferenca_num'] < 0,
            df_resumo['Diferenca_num'] > 0,
            df_resumo['Diferenca_num'] == 0
        ]
        choices_display = ['🔴 FALTA', '🔵 EXCEDENTE', '🟢 OK']
        df_resumo['Status_display'] = np.select(conditions, choices_display, default='🟡 AJUSTE')
        df_resumo['Status'] = df_resumo['Status_display'].str.split().str[1]

        # precompute por cargo (para gráfico)
        df_por_cargo = df_resumo.groupby('Cargo', as_index=False).agg({'Edital':'sum','Real':'sum'})
        df_por_cargo['Diferenca'] = df_por_cargo['Real'] - df_por_cargo['Edital']
        df_por_cargo['Diferenca_display'] = df_por_cargo['Diferenca'].apply(lambda x: f"+{int(x)}" if x > 0 else str(int(x)))

        # ---------- DASHBOARD ----------
        st.title("📊 Mesa Operacional")
        c1, c2, c3 = st.columns(3)
        with c1: st.markdown("**<div style='font-size:18px'>📋 Total Edital</div>**", unsafe_allow_html=True); st.metric("", int(df_resumo['Edital'].sum()))
        with c2: st.markdown("**<div style='font-size:18px'>👥 Efetivo Atual</div>**", unsafe_allow_html=True); st.metric("", int(df_resumo['Real'].sum()))
        with c3: st.markdown("**<div style='font-size:18px'>⚖️ Saldo Geral</div>**", unsafe_allow_html=True); st.metric("", int(df_resumo['Real'].sum() - df_resumo['Edital'].sum()))

        st.markdown("---")
        with st.expander("📈 Ver Gráficos e Resumo Geral", expanded=True):
            dfm = df_por_cargo.melt(id_vars=['Cargo'], value_vars=['Edital','Real'], var_name='Tipo', value_name='Quantidade')
            fig = px.bar(dfm, x='Cargo', y='Quantidade', color='Tipo', barmode='group', text_auto=True, template="seaborn")
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(df_por_cargo[['Cargo','Edital','Real','Diferenca_display']].rename(columns={'Diferenca_display':'Diferenca'}), use_container_width=True, hide_index=True)

        st.markdown("---"); st.subheader("🏫 Detalhe por Escola")

        # ---------- Filtros UI ----------
        c_f1, c_f2, c_f3, c_f4 = st.columns([1.2, 1.2, 1, 1])
        with c_f1: filtro_escola = st.selectbox("🔍 Escola:", ["Todas"] + sorted(list(df_resumo['Escola'].unique())))
        with c_f2: filtro_supervisor = st.selectbox("👔 Supervisor:", ["Todos"] + sorted(list(df_resumo['Supervisor'].unique())))
        with c_f3: filtro_situacao = st.selectbox("🚦 Situação:", ["Todas", "🔴 FALTA", "🔵 EXCEDENTE", "🟡 AJUSTE", "🟢 OK"])
        with c_f4: termo_busca = st.text_input("👤 Buscar Colaborador:", "")

        col_cargos = list(df_resumo['Cargo'].unique())
        filtro_comb = {}
        cols = st.columns(min(5, len(col_cargos)))
        for i, cargo in enumerate(col_cargos):
            with cols[i % len(cols)]:
                sel = st.selectbox(cargo, ["Todos","FALTA","EXCEDENTE","OK"], key=f'f_{i}')
                if sel != "Todos": filtro_comb[cargo] = sel

        mask = pd.Series(True, index=df_resumo.index)
        if filtro_escola != "Todas": mask &= (df_resumo['Escola'] == filtro_escola)
        if filtro_supervisor != "Todos": mask &= (df_resumo['Supervisor'] == filtro_supervisor)

        # cálculo de status por escola (feito uma vez)
        if filtro_situacao != "Todas":
            escola_status = {}
            for escola, group in df_resumo.groupby('Escola'):
                total_edital_e = int(group['Edital'].sum())
                total_real_e = int(group['Real'].sum())
                saldo_e = total_real_e - total_edital_e
                status_list = group['Status'].tolist()
                status_escola = "🟢 OK"
                if saldo_e == 0 and any(s != 'OK' for s in status_list):
                    status_escola = "🟡 AJUSTE"
                elif "FALTA" in status_list:
                    status_escola = "🔴 FALTA"
                elif "EXCEDENTE" in status_list:
                    status_escola = "🔵 EXCEDENTE"
                escola_status[escola] = status_escola
            escolas_filtro_status = [e for e, s in escola_status.items() if s == filtro_situacao]
            mask &= df_resumo['Escola'].isin(escolas_filtro_status)

        if filtro_comb:
            escolas_validas = []
            for escola, group in df_resumo.groupby('Escola'):
                valid = True
                for c, s in filtro_comb.items():
                    row = group[group['Cargo'] == c]
                    if row.empty or row['Status'].iloc[0] != s: valid = False; break
                if valid: escolas_validas.append(escola)
            mask &= df_resumo['Escola'].isin(escolas_validas)

        if termo_busca:
            match = df_pessoas[df_pessoas['Funcionario'].str.contains(termo_busca, case=False) | df_pessoas['ID'].astype(str).str.contains(termo_busca)]['Escola'].unique()
            mask &= df_resumo['Escola'].isin(match)

        df_final = df_resumo[mask]
        st.info(f"**Encontradas {df_final['Escola'].nunique()} escolas.**")

        # ---------- Paginação para escolas (evita renderizar tudo de uma vez) ----------
        per_page = 15
        st.session_state.setdefault("page_escolas", 0)
        total_pages = max(1, (df_final['Escola'].nunique() + per_page - 1) // per_page)
        cols_nav = st.columns([1,1,6,1,1])
        with cols_nav[0]:
            if st.button("◀ Anterior") and st.session_state["page_escolas"] > 0:
                st.session_state["page_escolas"] -= 1
        with cols_nav[1]:
            if st.button("Próxima ▶") and st.session_state["page_escolas"] < total_pages-1:
                st.session_state["page_escolas"] += 1
        cols_nav[2].write(f"Página {st.session_state['page_escolas']+1} de {total_pages}")

        escolas_list = sorted(df_final['Escola'].unique())
        start = st.session_state["page_escolas"] * per_page
        end = start + per_page
        escolas_page = escolas_list[start:end]

        # loop apenas sobre escolas da página
        for escola in escolas_page:
            df_e = df_final[df_final['Escola'] == escola].copy()
            status_list = df_e['Status'].tolist()
            nome_supervisor = df_e['Supervisor'].iloc[0]
            unidade_id = int(df_e['UnidadeID'].iloc[0])
            data_atual = df_e['DataConferencia'].iloc[0]

            total_edital_esc = int(df_e['Edital'].sum())
            total_real_esc = int(df_e['Real'].sum())
            saldo_esc = total_real_esc - total_edital_esc
            cor_saldo = "red" if saldo_esc < 0 else "blue" if saldo_esc > 0 else "green"
            sinal_saldo = "+" if saldo_esc > 0 else ""

            icon = "✅"
            if saldo_esc == 0 and any(s != 'OK' for s in status_list): icon = "🟡"
            elif "FALTA" in status_list: icon = "🔴"
            elif "EXCEDENTE" in status_list: icon = "🔵"

            with st.expander(f"{icon} {escola}", expanded=False):
                c_sup, c_btn = st.columns([3, 1.5])
                with c_sup: st.markdown(f"**👨‍💼 Supervisor:** {nome_supervisor}")
                with c_btn:
                    label_botao = "⚠️ Pendente" if pd.isnull(data_atual) else f"📅 Conferido: {data_atual.strftime('%d/%m/%Y')}"
                    with st.popover(label_botao, use_container_width=True):
                        nova_data = st.date_input("Nova Data:", value=pd.Timestamp.today() if pd.isnull(data_atual) else data_atual, format="DD/MM/YYYY", key=f"dt_{unidade_id}")
                        if st.button("💾 Salvar", key=f"save_{unidade_id}"):
                            with conn.session as session:
                                session.execute(text(f"UPDATE \"Unidades\" SET \"DataConferencia\" = '{nova_data}' WHERE \"UnidadeID\" = {unidade_id};"))
                                session.commit()
                            st.toast("Data salva!", icon="✅")
                            st.session_state.pop("cache_resumo", None)
                            st.experimental_rerun()

                st.markdown(f"""
                <div style='display: flex; justify-content: space-around; background-color: #262730; padding: 8px; border-radius: 5px; margin: 5px 0 15px 0; border: 1px solid #404040;'>
                    <span>📋 Edital: <b>{total_edital_esc}</b></span>
                    <span>👥 Real: <b>{total_real_esc}</b></span>
                    <span>⚖️ Saldo: <b style='color: {cor_saldo}'>{sinal_saldo}{saldo_esc}</b></span>
                </div>
                """, unsafe_allow_html=True)

                st.markdown("#### 📊 Quadro de Vagas")
                d_show = df_e[['Cargo','Edital','Real','Diferenca_display','Status_display']].rename(columns={'Diferenca_display':'Diferenca','Status_display':'Status'})
                d_show[['Edital','Real']] = d_show[['Edital','Real']].astype(int)
                st.dataframe(d_show, use_container_width=True, hide_index=True)

                st.markdown("#### 📋 Colaboradores (Selecione para Editar)")
                p_show = df_pessoas[df_pessoas['Escola'] == escola]
                if termo_busca:
                    p_show = p_show[p_show['Funcionario'].str.contains(termo_busca, case=False) | p_show['ID'].astype(str).str.contains(termo_busca)]

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
