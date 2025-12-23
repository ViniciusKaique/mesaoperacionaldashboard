import streamlit as st 
import streamlit_authenticator as stauth
import pandas as pd
import json
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
    
    /* CSS Grid para KPI da Escola */
    .kpi-box {
        display: flex; justify-content: space-around; 
        background-color: #262730; padding: 10px; 
        border-radius: 8px; margin-bottom: 15px; border: 1px solid #404040;
    }
    .kpi-item { font-size: 16px; color: white; }
    .kpi-val { font-weight: bold; font-size: 18px; }
    
    /* Tabelas HTML puras (Mais rápido que st.dataframe para visualização simples) */
    .simple-table { width: 100%; border-collapse: collapse; font-size: 14px; margin-bottom: 10px; }
    .simple-table th { background-color: #333; color: white; padding: 6px; text-align: center; }
    .simple-table td { padding: 6px; text-align: center; border-bottom: 1px solid #444; color: #ddd; }
    
    div[data-testid="stSpinner"] > div { font-size: 28px !important; color: #ff4b4b !important; }
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
def editar_colaborador(colab_id, nome_atual, escola_atual, cargo_atual, lista_escolas, lista_cargos, conn):
    st.write(f"Editando: **{nome_atual}**")
    with st.form("form_edicao"):
        nova_escola = st.selectbox("🏫 Escola:", lista_escolas, index=lista_escolas.index(escola_atual) if escola_atual in lista_escolas else 0)
        novo_cargo = st.selectbox("💼 Cargo:", lista_cargos, index=lista_cargos.index(cargo_atual) if cargo_atual in lista_cargos else 0)
        novo_status = st.checkbox("✅ Ativo?", value=True)
        
        if st.form_submit_button("💾 Salvar"):
            try:
                # Busca IDs (Poderia vir direto no JSON, mas aqui simplifica a query principal)
                query_ids = text("""
                    SELECT 
                        (SELECT "UnidadeID" FROM "Unidades" WHERE "NomeUnidade" = :ue) as uid,
                        (SELECT "CargoID" FROM "Cargos" WHERE "NomeCargo" = :nc) as cid
                """)
                res = conn.query(query_ids, params={"ue": nova_escola, "nc": novo_cargo})
                
                # Correção: Verificar se retornou resultado antes de acessar
                if not res.empty:
                    uid, cid = res.iloc[0]['uid'], res.iloc[0]['cid']
                    with conn.session as session:
                        session.execute(text("UPDATE \"Colaboradores\" SET \"UnidadeID\" = :uid, \"CargoID\" = :cid, \"Ativo\" = :ativo WHERE \"ColaboradorID\" = :id"), 
                                        {"uid": int(uid), "cid": int(cid), "ativo": novo_status, "id": int(colab_id)})
                        session.commit()
                    st.cache_data.clear()
                    st.toast("Salvo!", icon="🚀"); st.rerun()
                else:
                    st.error("Erro ao localizar IDs de Escola ou Cargo.")
            except Exception as e: st.error(f"Erro: {e}")

# --- SISTEMA PRINCIPAL ---
if st.session_state.get("authentication_status"):
    name = st.session_state.get("name")
    with st.sidebar:
        if logo := carregar_logo(): st.image(logo, use_container_width=True); st.divider()
        st.write(f"👤 **{name}**"); authenticator.logout(location='sidebar'); st.divider(); st.info("Modo Turbo (JSON SQL)")

    try:
        conn = st.connection("postgres", type="sql")

        # === CORREÇÃO AQUI: Consultas separadas para evitar erro de chave ===
        df_unidades = conn.query('SELECT "NomeUnidade" FROM "Unidades" ORDER BY 1', ttl=600)
        lista_escolas_all = df_unidades['NomeUnidade'].tolist()
        
        df_cargos = conn.query('SELECT "NomeCargo" FROM "Cargos" ORDER BY 1', ttl=600)
        lista_cargos_all = df_cargos['NomeCargo'].tolist()
        # ===================================================================

        # === A QUERY SUPREMA (RETORNA JSON) ===
        # Esta query monta tudo que o Streamlit precisa num único objeto por escola
        query_json = """
        WITH DadosReais AS (
            SELECT "UnidadeID", "CargoID", COUNT(*) as qtd 
            FROM "Colaboradores" WHERE "Ativo" = TRUE GROUP BY "UnidadeID", "CargoID"
        ),
        ListaPessoas AS (
            SELECT 
                c."UnidadeID",
                jsonb_agg(jsonb_build_object(
                    'id', c."ColaboradorID", 
                    'nome', c."Nome", 
                    'cargo', cg."NomeCargo"
                ) ORDER BY c."Nome") as pessoas_json
            FROM "Colaboradores" c
            JOIN "Cargos" cg ON c."CargoID" = cg."CargoID"
            WHERE c."Ativo" = TRUE
            GROUP BY c."UnidadeID"
        ),
        Quadro AS (
            SELECT 
                u."UnidadeID",
                jsonb_agg(jsonb_build_object(
                    'cargo', c."NomeCargo",
                    'edital', q."Quantidade",
                    'real', COALESCE(dr.qtd, 0),
                    'saldo', (COALESCE(dr.qtd, 0) - q."Quantidade")
                ) ORDER BY c."NomeCargo") as quadro_json,
                SUM(q."Quantidade") as total_edital,
                SUM(COALESCE(dr.qtd, 0)) as total_real
            FROM "QuadroEdital" q
            JOIN "Unidades" u ON q."UnidadeID" = u."UnidadeID"
            JOIN "Cargos" c ON q."CargoID" = c."CargoID"
            LEFT JOIN DadosReais dr ON q."UnidadeID" = dr."UnidadeID" AND q."CargoID" = dr."CargoID"
            GROUP BY u."UnidadeID"
        )
        SELECT 
            u."UnidadeID",
            u."NomeUnidade" as escola,
            s."NomeSupervisor" as supervisor,
            u."DataConferencia",
            COALESCE(q.total_edital, 0) as t_edital,
            COALESCE(q.total_real, 0) as t_real,
            COALESCE(q.quadro_json, '[]'::jsonb) as quadro,
            COALESCE(lp.pessoas_json, '[]'::jsonb) as pessoas
        FROM "Unidades" u
        JOIN "Supervisores" s ON u."SupervisorID" = s."SupervisorID"
        LEFT JOIN Quadro q ON u."UnidadeID" = q."UnidadeID"
        LEFT JOIN ListaPessoas lp ON u."UnidadeID" = lp."UnidadeID"
        ORDER BY u."NomeUnidade";
        """

        # Carrega dados já estruturados (MUITO RÁPIDO)
        df_main = conn.query(query_json, ttl=300) 
        
        # Converte DataConferencia para datetime
        df_main['DataConferencia'] = pd.to_datetime(df_main['DataConferencia'])

        # === KPI SUPERIOR ===
        total_edital_geral = df_main['t_edital'].sum()
        total_real_geral = df_main['t_real'].sum()
        saldo_geral = total_real_geral - total_edital_geral
        
        st.title("📊 Mesa Operacional (Modo Turbo JSON)")
        c1, c2, c3 = st.columns(3)
        with c1: st.metric("📋 Total Edital", int(total_edital_geral))
        with c2: st.metric("👥 Efetivo Atual", int(total_real_geral))
        with c3: st.metric("⚖️ Saldo Geral", int(saldo_geral))
        
        st.markdown("---")

        # === FILTROS (PYTHON - RÁPIDO POIS SÃO POUCAS LINHAS DE ESCOLAS) ===
        c_f1, c_f2, c_f3, c_f4 = st.columns([1, 1, 1, 1])
        with c_f1: f_escola = st.selectbox("Escola:", ["Todas"] + df_main['escola'].tolist())
        with c_f2: f_super = st.selectbox("Supervisor:", ["Todos"] + sorted(df_main['supervisor'].unique().tolist()))
        with c_f3: f_status = st.selectbox("Situação:", ["Todas", "🔴 FALTA", "🔵 EXCEDENTE", "🟡 AJUSTE", "🟢 OK"])
        with c_f4: f_busca = st.text_input("Buscar Pessoa:", "")

        # Lógica de Filtragem
        filtered_df = df_main.copy()
        
        if f_escola != "Todas": filtered_df = filtered_df[filtered_df['escola'] == f_escola]
        if f_super != "Todos": filtered_df = filtered_df[filtered_df['supervisor'] == f_super]
        
        # Função para calcular status da linha (Rápida)
        def get_status(row):
            saldo = row['t_real'] - row['t_edital']
            if saldo > 0: return "🔵 EXCEDENTE"
            if saldo < 0: return "🔴 FALTA"
            # Verifica JSON interno para ajuste
            quadro = row['quadro'] # Já é uma lista de dicts ou json string
            if isinstance(quadro, str): quadro = json.loads(quadro)
            for item in quadro:
                if item['saldo'] != 0: return "🟡 AJUSTE"
            return "🟢 OK"

        if f_status != "Todas":
            filtered_df['status_calc'] = filtered_df.apply(get_status, axis=1)
            filtered_df = filtered_df[filtered_df['status_calc'] == f_status]
        
        if f_busca:
            # Busca dentro do JSON de pessoas (Search Text)
            filtered_df = filtered_df[filtered_df['pessoas'].astype(str).str.contains(f_busca, case=False)]

        st.info(f"**{len(filtered_df)} Escolas encontradas.**")

        # === RENDERIZAÇÃO OTIMIZADA ===
        for index, row in filtered_df.iterrows():
            escola = row['escola']
            supervisor = row['supervisor']
            data_conf = row['DataConferencia']
            t_edital = row['t_edital']
            t_real = row['t_real']
            saldo = t_real - t_edital
            unidade_id = row['UnidadeID']
            
            # Status e Ícone
            icon = "✅"
            cor_saldo = "#00c853" # Green
            if saldo > 0: 
                icon = "🔵"; cor_saldo = "#29b6f6"
            elif saldo < 0: 
                icon = "🔴"; cor_saldo = "#ff4b4b"
            else:
                # Checa ajuste fino
                quadro_data = row['quadro'] if isinstance(row['quadro'], list) else json.loads(row['quadro'])
                if any(q['saldo'] != 0 for q in quadro_data): icon = "🟡"

            with st.expander(f"{icon} {escola}", expanded=False):
                # Header Interno
                c_sup, c_data = st.columns([3, 1])
                with c_sup: st.markdown(f"**Supervisor:** {supervisor}")
                with c_data:
                    lbl = "⚠️ Pendente" if pd.isnull(data_conf) else data_conf.strftime('%d/%m/%Y')
                    if st.button(f"📅 {lbl}", key=f"btn_d_{unidade_id}"):
                        # Dialog simples para data
                        @st.dialog("Data")
                        def modal_data(uid):
                            d = st.date_input("Nova data")
                            if st.button("Salvar Data"):
                                with conn.session as session:
                                    session.execute(text(f"UPDATE \"Unidades\" SET \"DataConferencia\" = '{d}' WHERE \"UnidadeID\" = {uid}"))
                                    session.commit()
                                st.cache_data.clear(); st.rerun()
                        modal_data(unidade_id)

                # HTML KPI
                st.markdown(f"""
                <div class='kpi-box'>
                    <div class='kpi-item'>Edital: <span class='kpi-val'>{t_edital}</span></div>
                    <div class='kpi-item'>Real: <span class='kpi-val'>{t_real}</span></div>
                    <div class='kpi-item'>Saldo: <span class='kpi-val' style='color:{cor_saldo}'>{'+' if saldo > 0 else ''}{saldo}</span></div>
                </div>
                """, unsafe_allow_html=True)

                # Renderiza Tabela de Cargos (HTML Puro)
                quadro_data = row['quadro'] if isinstance(row['quadro'], list) else json.loads(row['quadro'])
                html_quadro = "<table class='simple-table'><thead><tr><th>Cargo</th><th>Edital</th><th>Real</th><th>Dif</th><th>Status</th></tr></thead><tbody>"
                for item in quadro_data:
                    dif = item['saldo']
                    cor = "green"
                    stt = "OK"
                    if dif > 0: cor = "#29b6f6"; stt = "EXCEDENTE"
                    elif dif < 0: cor = "#ff4b4b"; stt = "FALTA"
                    else: cor = "#00c853"
                    
                    dif_txt = f"+{dif}" if dif > 0 else str(dif)
                    html_quadro += f"<tr><td>{item['cargo']}</td><td>{item['edital']}</td><td>{item['real']}</td><td style='color:{cor}; font-weight:bold'>{dif_txt}</td><td style='color:{cor}'>{stt}</td></tr>"
                html_quadro += "</tbody></table>"
                st.markdown(html_quadro, unsafe_allow_html=True)
                
                # Renderiza Pessoas
                st.markdown("**👥 Colaboradores**")
                pessoas_data = row['pessoas'] if isinstance(row['pessoas'], list) else json.loads(row['pessoas'])
                
                if pessoas_data:
                    df_p = pd.DataFrame(pessoas_data)
                    df_p = df_p.rename(columns={'nome': 'Nome', 'cargo': 'Cargo', 'id': 'ID'})
                    event = st.dataframe(df_p[['ID', 'Nome', 'Cargo']], hide_index=True, use_container_width=True, selection_mode="single-row", on_select="rerun", key=f"grid_{unidade_id}")
                    
                    if len(event.selection.rows) > 0:
                        sel_idx = event.selection.rows[0]
                        p_sel = df_p.iloc[sel_idx]
                        editar_colaborador(p_sel['ID'], p_sel['Nome'], escola, p_sel['Cargo'], lista_escolas_all, lista_cargos_all, conn)
                else:
                    st.caption("Nenhum colaborador alocado.")

    except Exception as e:
        st.error(f"Erro: {e}")