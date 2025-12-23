import streamlit as st 
import streamlit_authenticator as stauth
import pandas as pd
import plotly.express as px
import requests
from PIL import Image
from sqlalchemy import text
from datetime import datetime

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

# ==========================================
# 1. FUNÇÕES AUXILIARES DA NOVA PÁGINA (API)
# ==========================================
def get_headers():
    try:
        secrets = st.secrets["api_teknisa"]
        return {
            "accept": "application/json, text/plain, */*",
            "oauth-cdoperador": secrets["cd_operador"],
            "oauth-nrorg": secrets["nr_org"],
            "oauth-token": secrets["token"],
            "User-Agent": "Streamlit/1.0"
        }
    except KeyError:
        st.error("Erro: Configure [api_teknisa] no secrets.toml"); st.stop()

@st.cache_data(ttl=3600)
def get_periodo_aberto():
    url = "https://portalgestor.teknisa.com/backend/index.php/getPeriodosDemonstrativo"
    secrets = st.secrets["api_teknisa"]
    params = {
        "requestType": "FilterData",
        "NRORG": secrets["nr_org"],
        "CDOPERADOR": secrets["cd_operador"]
    }
    try:
        response = requests.get(url, headers=get_headers(), params=params)
        data = response.json()
        periodos = [p for p in data['dataset']['data'] if p['IDPERIODOAPURACAO'] == 'ABERTO']
        if periodos:
            return sorted(periodos, key=lambda x: int(x['NRPERIODOAPURACAO']), reverse=True)[0]
        return None
    except Exception as e:
        st.error(f"Erro ao buscar período: {e}")
        return None

def get_mesa_operacoes_api(data_consulta, unidade_id):
    url = "https://portalgestor.teknisa.com/backend/index.php/getMesaOperacoes"
    secrets = st.secrets["api_teknisa"]
    params = {
        "requestType": "FilterData",
        "DIA": data_consulta,
        "NRESTRUTURAM": unidade_id,
        "NRORG": secrets["nr_org"],
        "CDOPERADOR": secrets["cd_operador"]
    }
    try:
        response = requests.get(url, headers=get_headers(), params=params)
        return response.json()['dataset']['data']
    except Exception:
        return []

def processar_status_api(funcionario):
    # Lógica de prioridade igual ao Vue.js
    if funcionario.get('IS_FERIAS') == 'S': return "Férias", "🟦"
    if funcionario.get('IS_AFASTAMENTO') == 'S': return "Afastamento", "🟧"
    if funcionario.get('IS_ABONO') == 'S': return "Abono", "Dv"
    
    horas_escala = funcionario.get('horas_escala', [])
    horas_trabalhadas = funcionario.get('horas_trabalhadas', [])
    
    if len(horas_trabalhadas) > 0: return "Trabalhado", "🟩"
    if len(horas_escala) > 0 and len(horas_trabalhadas) == 0: return "Não Trabalhou", "🟥"
        
    return "Folga / N.A.", "⬜"

# ==========================================
# 2. DIALOGS (DO SISTEMA ORIGINAL)
# ==========================================
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

# ==========================================
# 3. PÁGINA NOVA: STATUS POSTOS
# ==========================================
def show_status_postos(conn):
    st.title("📍 Status Postos (Tempo Real)")
    # 

[Image of API integration flow]

    st.info("Visualização integrada com a Mesa de Operações da Teknisa.")

    # 1. Carregar Unidades do Banco SQL
    df_unidades = conn.query('SELECT "UnidadeID", "NomeUnidade" FROM "Unidades" ORDER BY "NomeUnidade"', ttl=600)
    
    # 2. Layout de Filtros
    col_sel, col_info = st.columns([3, 1])
    with col_sel:
        unidade_selecionada = st.selectbox("Selecione a Unidade:", df_unidades['NomeUnidade'].unique())
    
    # 3. Buscar Período Atual da API
    periodo = get_periodo_aberto()
    if not periodo:
        st.error("Não há período aberto na Teknisa.")
        return

    hoje_str = datetime.now().strftime("%d/%m/%Y")
    with col_info:
        st.markdown(f"**Data:** {hoje_str}")
        st.caption(f"Período: {periodo['DSPERIODOAPURACAO']}")

    if st.button("🔄 Atualizar Dados da Mesa"):
        st.cache_data.clear()
        st.rerun()

    # 4. Buscar Dados API
    try:
        # Tenta vincular o ID do banco SQL com a API
        row_unidade = df_unidades[df_unidades['NomeUnidade'] == unidade_selecionada].iloc[0]
        id_api = str(row_unidade['UnidadeID']) 
        
        with st.spinner("Consultando Teknisa..."):
            dados_api = get_mesa_operacoes_api(hoje_str, id_api)
    except Exception as e:
        st.error(f"Erro ao vincular ID da unidade: {e}"); return

    if not dados_api:
        st.warning("Nenhum dado encontrado para hoje nesta unidade.")
        return

    # 5. Processar Dados
    lista_proc = []
    for func in dados_api:
        status, icon = processar_status_api(func)
        lista_proc.append({
            "Icone": icon,
            "Colaborador": func.get('NMVINCULOM', 'Sem Nome'),
            "Cargo": func.get('NMESTRUTGEREN', '-'),
            "Status": status,
            "Entrada": func.get('horas_trabalhadas', [['--:--']])[0][0] if func.get('horas_trabalhadas') else "--:--",
            "Escala": func.get('horas_escala', [['--:--']])[0][0] if func.get('horas_escala') else "Sem Escala"
        })
    
    df_status = pd.DataFrame(lista_proc)

    # 6. Métricas e Visualização
    k1, k2, k3, k4 = st.columns(4)
    total = len(df_status)
    presentes = len(df_status[df_status['Status'] == 'Trabalhado'])
    faltas = len(df_status[df_status['Status'] == 'Não Trabalhou'])
    outros = total - presentes - faltas

    k1.metric("Total Previsto", total)
    k2.metric("Presentes", presentes)
    k3.metric("Possíveis Faltas", faltas, delta_color="inverse")
    k4.metric("Afast./Férias", outros)

    st.markdown("---")
    c_graf, c_tab = st.columns([1, 2])
    
    with c_graf:
        if not df_status.empty:
            color_map = {
                "Trabalhado": "#00c853", "Não Trabalhou": "#ff4b4b", "Férias": "#29b6f6",
                "Afastamento": "#ffb74d", "Abono": "#ff7043", "Folga / N.A.": "#e0e0e0"
            }
            contagem = df_status['Status'].value_counts().reset_index()
            contagem.columns = ['Status', 'Qtd']
            fig = px.pie(contagem, values='Qtd', names='Status', color='Status', color_discrete_map=color_map, hole=0.4)
            st.plotly_chart(fig, use_container_width=True)

    with c_tab:
        def style_status(row):
            if row['Status'] == 'Não Trabalhou': return ['background-color: #ffebee; color: #c62828'] * len(row)
            if row['Status'] == 'Trabalhado': return ['background-color: #e8f5e9; color: #2e7d32'] * len(row)
            if row['Status'] == 'Férias': return ['background-color: #e1f5fe; color: #0277bd'] * len(row)
            return [''] * len(row)

        st.dataframe(df_status.style.apply(style_status, axis=1), use_container_width=True, hide_index=True)

# ==========================================
# 4. PÁGINA ORIGINAL: PAINEL GERENCIAL
# ==========================================
def show_painel_gerencial(conn):
    # --- AQUI ESTÁ SEU CÓDIGO ORIGINAL INTACTO ---
    
    # Dados Auxiliares
    df_unidades_all = conn.query('SELECT "UnidadeID", "NomeUnidade" FROM "Unidades" ORDER BY "NomeUnidade"', ttl=600, show_spinner=False)
    df_cargos_all = conn.query('SELECT "CargoID", "NomeCargo" FROM "Cargos" ORDER BY "NomeCargo"', ttl=600, show_spinner=False)

    # Queries
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

    df_resumo = conn.query(query_resumo, ttl=600, show_spinner=False)
    df_pessoas = conn.query(query_funcionarios, ttl=600, show_spinner=False)

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

    mask = pd.Series([True] * len(df_resumo))
    if filtro_escola != "Todas": mask &= (df_resumo['Escola'] == filtro_escola)
    if filtro_supervisor != "Todos": mask &= (df_resumo['Supervisor'] == filtro_supervisor)
    
    if filtro_situacao != "Todas":
        escolas_filtro_status = []
        for escola in df_resumo['Escola'].unique():
            df_e = df_resumo[df_resumo['Escola'] == escola]
            total_edital_e = df_e['Edital'].sum()
            total_real_e = df_e['Real'].sum()
            saldo_e = total_real_e - total_edital_e
            status_list = df_e['Status'].tolist()
            
            status_escola = "🟢 OK"
            if saldo_e > 0: status_escola = "🔵 EXCEDENTE"
            elif saldo_e < 0: status_escola = "🔴 FALTA"
            elif saldo_e == 0 and any(s != 'OK' for s in status_list): status_escola = "🟡 AJUSTE"
            
            if status_escola == filtro_situacao: escolas_filtro_status.append(escola)
        mask &= df_resumo['Escola'].isin(escolas_filtro_status)

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
        match = df_pessoas[df_pessoas['Funcionario'].str.contains(termo_busca, case=False, na=False) | df_pessoas['ID'].astype(str).str.contains(termo_busca, na=False)]['Escola'].unique()
        mask &= df_resumo['Escola'].isin(match)

    df_final = df_resumo[mask]
    st.info(f"**Encontradas {df_final['Escola'].nunique()} escolas.**")

    for escola in df_final['Escola'].unique():
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
        if saldo_esc > 0: icon = "🔵"
        elif saldo_esc < 0: icon = "🔴"
        elif saldo_esc == 0 and any(s != 'OK' for s in status_list): icon = "🟡"

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
                        st.cache_data.clear()
                        st.toast("Data salva!", icon="✅"); st.rerun()

            st.markdown(f"""
            <div style='display: flex; justify-content: space-around; background-color: #262730; padding: 8px; border-radius: 5px; margin: 5px 0 15px 0; border: 1px solid #404040;'>
                <span>📋 Edital: <b>{total_edital_esc}</b></span>
                <span>👥 Real: <b>{total_real_esc}</b></span>
                <span>⚖️ Saldo: <b style='color: {cor_saldo}'>{sinal_saldo}{saldo_esc}</b></span>
            </div>
            """, unsafe_allow_html=True)

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

            st.markdown("#### 📋 Colaboradores (Selecione para Editar)")
            p_show = df_pessoas[df_pessoas['Escola'] == escola]
            if termo_busca: p_show = p_show[p_show['Funcionario'].str.contains(termo_busca, case=False, na=False) | p_show['ID'].astype(str).str.contains(termo_busca, na=False)]
            
            if not p_show.empty:
                event = st.dataframe(p_show[['ID','Funcionario','Cargo']], use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row", key=f"grid_{unidade_id}")
                if len(event.selection.rows) > 0:
                    idx_selecionado = event.selection.rows[0]
                    dados_colaborador = p_show.iloc[idx_selecionado]
                    editar_colaborador(dados_colaborador, df_unidades_all, df_cargos_all, conn)
            else:
                st.warning("Nenhum colaborador encontrado.")

# ==========================================
# 5. CONTROLE PRINCIPAL DE NAVEGAÇÃO
# ==========================================
if st.session_state.get("authentication_status"):
    name = st.session_state.get("name")
    
    # --- BARRA LATERAL COM NAVEGAÇÃO ---
    with st.sidebar:
        if logo := carregar_logo(): 
            st.image(logo, use_container_width=True)
        st.divider()
        
        # AQUI ESTÁ A MÁGICA: O Menu para trocar de tela
        pagina_escolhida = st.radio("Navegar", ["Painel Gerencial", "Status Postos"], index=0)
        
        st.divider()
        st.write(f"👤 **{name}**")
        authenticator.logout(location='sidebar')
        st.info(f"Módulo: {pagina_escolhida}")

    # --- EXECUÇÃO DAS TELAS ---
    try:
        conn = st.connection("postgres", type="sql")
        
        if pagina_escolhida == "Status Postos":
            show_status_postos(conn)
        else:
            show_painel_gerencial(conn) # Chama sua dashboard original sem alterar nada
            
    except Exception as e:
        st.error(f"Erro no sistema: {e}")