import streamlit as st 
import streamlit_authenticator as stauth
import pandas as pd
import plotly.express as px
import numpy as np
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
    
    /* Otimização de renderização de tabela */
    .dataframe { font-size: 14px !important; }
    th, td { text-align: center !important; }
    
    div[data-testid="stSpinner"] > div {
        font-size: 28px !important; font-weight: bold !important; color: #ff4b4b !important; white-space: nowrap;
    }
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

# --- DIALOGS ---
@st.dialog("✏️ Editar Colaborador")
def editar_colaborador(colab_data, df_unidades_all, df_cargos_all, conn):
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
            novo_unidade_id = int(df_unidades_all[df_unidades_all['NomeUnidade'] == nova_escola_nome]['UnidadeID'].iloc[0])
            novo_cargo_id = int(df_cargos_all[df_cargos_all['NomeCargo'] == novo_cargo_nome]['CargoID'].iloc[0])
            colab_id = int(colab_data['ID'])
            try:
                with conn.session as session:
                    session.execute(text("UPDATE \"Colaboradores\" SET \"UnidadeID\" = :uid, \"CargoID\" = :cid, \"Ativo\" = :ativo WHERE \"ColaboradorID\" = :id"), 
                                    {"uid": novo_unidade_id, "cid": novo_cargo_id, "ativo": novo_status, "id": colab_id})
                    session.commit()
                st.cache_data.clear() 
                st.toast("Atualizado!", icon="🎉"); st.rerun()
            except Exception as e: st.error(f"Erro: {e}")

# --- SISTEMA PRINCIPAL ---
if st.session_state.get("authentication_status"):
    name = st.session_state.get("name")
    with st.sidebar:
        if logo := carregar_logo(): st.image(logo, use_container_width=True); st.divider()
        st.write(f"👤 **{name}**"); authenticator.logout(location='sidebar'); st.divider(); st.info("Painel Gerencial + Detalhe")

    try:
        conn = st.connection("postgres", type="sql")

        # Dados Auxiliares (Cache de 10 min)
        df_unidades_all = conn.query('SELECT "UnidadeID", "NomeUnidade" FROM "Unidades" ORDER BY "NomeUnidade"', ttl=600, show_spinner=False)
        df_cargos_all = conn.query('SELECT "CargoID", "NomeCargo" FROM "Cargos" ORDER BY "NomeCargo"', ttl=600, show_spinner=False)

        # --- SQL ULTRA OTIMIZADO (CTE + LEFT JOIN) ---
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
            COALESCE(cr."QtdReal", 0) AS "Real"
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

        df_resumo = conn.query(query_resumo, ttl=600, show_spinner=False)
        df_pessoas = conn.query(query_funcionarios, ttl=600, show_spinner=False)

        # --- PROCESSAMENTO VETORIZADO (INSTANTÂNEO) ---
        df_resumo['Diferenca_num'] = df_resumo['Real'] - df_resumo['Edital']
        
        # Define arrays para numpy.select (substitui .apply)
        cond_neg = df_resumo['Diferenca_num'] < 0
        cond_pos = df_resumo['Diferenca_num'] > 0
        
        df_resumo['Status_display'] = np.select([cond_neg, cond_pos], ['🔴 FALTA', '🔵 EXCEDENTE'], default='🟢 OK')
        df_resumo['Status'] = np.select([cond_neg, cond_pos], ['FALTA', 'EXCEDENTE'], default='OK')

        # Formatação (String)
        df_resumo['Diferenca_display'] = df_resumo['Diferenca_num'].apply(lambda x: f"+{x}" if x > 0 else str(int(x)))
        df_resumo['DataConferencia'] = pd.to_datetime(df_resumo['DataConferencia'])

        # === DASHBOARD ===
        st.title("📊 Mesa Operacional")
        c1, c2, c3 = st.columns(3)
        total_edital = int(df_resumo['Edital'].sum())
        total_real = int(df_resumo['Real'].sum())
        with c1: st.metric("📋 Total Edital", total_edital)
        with c2: st.metric("👥 Efetivo Atual", total_real)
        with c3: st.metric("⚖️ Saldo Geral", total_real - total_edital)

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
        
        # --- FILTROS ---
        c_f1, c_f2, c_f3, c_f4 = st.columns([1.2, 1.2, 1, 1])
        with c_f1: filtro_escola = st.selectbox("🔍 Escola:", ["Todas"] + sorted(list(df_resumo['Escola'].unique())))
        with c_f2: filtro_supervisor = st.selectbox("👔 Supervisor:", ["Todos"] + sorted(list(df_resumo['Supervisor'].unique())))
        with c_f3: filtro_situacao = st.selectbox("🚦 Situação:", ["Todas", "🔴 FALTA", "🔵 EXCEDENTE", "🟡 AJUSTE", "🟢 OK"])
        with c_f4: termo_busca = st.text_input("👤 Buscar Colaborador:", "")

        col_cargos = sorted(list(df_resumo['Cargo'].unique()))
        filtro_comb = {}
        if col_cargos:
            cols = st.columns(5)
            for i, cargo in enumerate(col_cargos):
                with cols[i % 5]:
                    if (sel := st.selectbox(cargo, ["Todos","FALTA","EXCEDENTE","OK"], key=f'f_{i}')) != "Todos": filtro_comb[cargo] = sel

        mask = pd.Series([True] * len(df_resumo))
        if filtro_escola != "Todas": mask &= (df_resumo['Escola'] == filtro_escola)
        if filtro_supervisor != "Todos": mask &= (df_resumo['Supervisor'] == filtro_supervisor)
        
        # Filtro de Situação (Lógica agregada)
        if filtro_situacao != "Todas":
            agg = df_resumo.groupby('Escola').agg({'Real':'sum', 'Edital':'sum', 'Status': list}).reset_index()
            agg['Saldo'] = agg['Real'] - agg['Edital']
            
            def get_status_agg(row):
                if row['Saldo'] > 0: return "🔵 EXCEDENTE"
                if row['Saldo'] < 0: return "🔴 FALTA"
                if any(s != 'OK' for s in row['Status']): return "🟡 AJUSTE"
                return "🟢 OK"
                
            escolas_alvo = agg[agg.apply(get_status_agg, axis=1) == filtro_situacao]['Escola']
            mask &= df_resumo['Escola'].isin(escolas_alvo)

        if filtro_comb:
            for c, s in filtro_comb.items():
                escolas_validas = df_resumo[(df_resumo['Cargo'] == c) & (df_resumo['Status'] == s)]['Escola']
                mask &= df_resumo['Escola'].isin(escolas_validas)

        if termo_busca:
            match = df_pessoas[df_pessoas['Funcionario'].str.contains(termo_busca, case=False, na=False) | df_pessoas['ID'].astype(str).str.contains(termo_busca, na=False)]['Escola'].unique()
            mask &= df_resumo['Escola'].isin(match)

        df_final = df_resumo[mask]
        
        # --- LOOP OTIMIZADO (GROUPBY) ---
        # Groupby é mais rápido que filtrar dentro do loop
        if not df_final.empty:
            st.info(f"**Encontradas {df_final['Escola'].nunique()} escolas.**")
            
            # Agrupa dados para iterar apenas 1 vez por escola
            grouped = df_final.groupby(['Escola', 'UnidadeID', 'Supervisor', 'DataConferencia'])
            
            # Ordena as escolas alfabeticamente
            sorted_groups = sorted(grouped, key=lambda x: x[0][0]) 

            for (nome_escola, unidade_id, supervisor, data_conf), df_e in sorted_groups:
                status_list = df_e['Status'].tolist()
                
                total_edital_esc = int(df_e['Edital'].sum())
                total_real_esc = int(df_e['Real'].sum())
                saldo_esc = total_real_esc - total_edital_esc
                
                # Definição visual rápida
                cor_saldo = "red" if saldo_esc < 0 else "blue" if saldo_esc > 0 else "green"
                sinal_saldo = "+" if saldo_esc > 0 else ""
                
                icon = "✅"
                if saldo_esc > 0: icon = "🔵"
                elif saldo_esc < 0: icon = "🔴"
                elif saldo_esc == 0 and any(s != 'OK' for s in status_list): icon = "🟡"

                with st.expander(f"{icon} {nome_escola}", expanded=False):
                    c_sup, c_btn = st.columns([3, 1.5])
                    with c_sup: st.markdown(f"**👨‍💼 Supervisor:** {supervisor}")
                    with c_btn:
                        # Popover ainda é necessário para edição de data
                        label_botao = "⚠️ Pendente" if pd.isnull(data_conf) else f"📅 Conferido: {data_conf.strftime('%d/%m/%Y')}"
                        with st.popover(label_botao, use_container_width=True):
                            st.markdown("Alterar data")
                            nova_data = st.date_input("Nova Data:", value=pd.Timestamp.today() if pd.isnull(data_conf) else data_conf, format="DD/MM/YYYY", key=f"dt_{unidade_id}")
                            if st.button("💾 Salvar", key=f"save_{unidade_id}"):
                                with conn.session as session:
                                    session.execute(text(f"UPDATE \"Unidades\" SET \"DataConferencia\" = '{nova_data}' WHERE \"UnidadeID\" = {unidade_id};"))
                                    session.commit()
                                st.cache_data.clear()
                                st.toast("Data salva!", icon="✅"); st.rerun()

                    st.markdown(f"""
                    <div style='display: flex; justify-content: space-around; background-color: #262730; padding: 8px; border-radius: 5px; margin: 5px 0 15px 0; border: 1px solid #404040;'>
                        <span>📋 Edital: <b>{total_edital_esc}</b></span>
                        <span>👥 Real: <b>{total_real_esc}</b></span>
                        <span>⚖️ Saldo: <b style='color: {cor_saldo}'>{sinal_saldo}{saldo_esc}</b></span>
                    </div>
                    """, unsafe_allow_html=True)

                    # Tabela de Cargos
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

                    # Tabela de Pessoas
                    st.markdown("#### 📋 Colaboradores (Selecione para Editar)")
                    # Filtro prévio fora do expander se possível, mas aqui filtramos localmente apenas o necessário
                    p_show = df_pessoas[df_pessoas['Escola'] == nome_escola]
                    if termo_busca: p_show = p_show[p_show['Funcionario'].str.contains(termo_busca, case=False, na=False) | p_show['ID'].astype(str).str.contains(termo_busca, na=False)]
                    
                    if not p_show.empty:
                        event = st.dataframe(p_show[['ID','Funcionario','Cargo']], use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row", key=f"grid_{unidade_id}")
                        if len(event.selection.rows) > 0:
                            idx_selecionado = event.selection.rows[0]
                            dados_colaborador = p_show.iloc[idx_selecionado]
                            editar_colaborador(dados_colaborador, df_unidades_all, df_cargos_all, conn)
                    else:
                        st.warning("Nenhum colaborador encontrado.")
        else:
            st.warning("Nenhuma escola encontrada.")

    except Exception as e:
        st.error(f"Erro no sistema: {e}")