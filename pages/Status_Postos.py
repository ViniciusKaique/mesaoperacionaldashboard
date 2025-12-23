import streamlit as st
import pandas as pd
import requests
import plotly.express as px
from datetime import datetime
from sqlalchemy import text

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Status Postos", layout="wide", page_icon="📍")

# --- VERIFICAÇÃO DE LOGIN (Herdado da Página Principal) ---
if not st.session_state.get("authentication_status"):
    st.warning("Por favor, faça login na página inicial primeiro.")
    st.stop()

# --- CSS (Mesmo padrão visual) ---
st.markdown("""
<style>
    .block-container { padding-top: 1rem; }
    .stButton button { background-color: #ff4b4b; color: white; border-radius: 8px; }
    div[data-testid="stMetricValue"] { font-size: 24px; font-weight: bold; }
    div.stButton > button { width: 100%; display: block; margin: 0 auto; }
</style>
""", unsafe_allow_html=True)

# --- FUNÇÕES DE API ---
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
        st.error("Configure [api_teknisa] no secrets.toml"); st.stop()

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
        st.error(f"Erro API Periodo: {e}")
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
    if funcionario.get('IS_FERIAS') == 'S': return "Férias", "🟦"
    if funcionario.get('IS_AFASTAMENTO') == 'S': return "Afastamento", "🟧"
    if funcionario.get('IS_ABONO') == 'S': return "Abono", "Dv"
    
    horas_escala = funcionario.get('horas_escala', [])
    horas_trabalhadas = funcionario.get('horas_trabalhadas', [])
    
    if len(horas_trabalhadas) > 0: return "Trabalhado", "🟩"
    if len(horas_escala) > 0 and len(horas_trabalhadas) == 0: return "Não Trabalhou", "🟥"
        
    return "Folga / N.A.", "⬜"

# --- TELA PRINCIPAL DA PÁGINA ---
st.title("📍 Status Postos (Tempo Real)")
st.info("Visualização integrada com a Mesa de Operações da Teknisa.")

# Conexão SQL (Reaproveitando a lógica de conexão para pegar nomes das escolas)
try:
    conn = st.connection("postgres", type="sql")
    df_unidades = conn.query('SELECT "UnidadeID", "NomeUnidade" FROM "Unidades" ORDER BY "NomeUnidade"', ttl=600)
except Exception as e:
    st.error(f"Erro ao conectar no banco SQL: {e}")
    st.stop()

# Filtros
col_sel, col_info = st.columns([3, 1])
with col_sel:
    unidade_selecionada = st.selectbox("Selecione a Unidade:", df_unidades['NomeUnidade'].unique())

# API Check
periodo = get_periodo_aberto()
hoje_str = datetime.now().strftime("%d/%m/%Y")

with col_info:
    st.markdown(f"**Data:** {hoje_str}")
    if periodo:
        st.caption(f"Período: {periodo['DSPERIODOAPURACAO']}")

if st.button("🔄 Atualizar Dados"):
    st.cache_data.clear()
    st.rerun()

# Busca Dados
if periodo:
    try:
        row_unidade = df_unidades[df_unidades['NomeUnidade'] == unidade_selecionada].iloc[0]
        id_api = str(row_unidade['UnidadeID']) 
        
        with st.spinner("Consultando Teknisa..."):
            dados_api = get_mesa_operacoes_api(hoje_str, id_api)
            
        if not dados_api:
            st.warning("Nenhum dado encontrado para hoje nesta unidade.")
        else:
            # Processamento
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

            # KPIs
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
            
            # Gráficos e Tabela
            c_graf, c_tab = st.columns([1, 2])
            
            with c_graf:
                if not df_status.empty:
                    color_map = {
                        "Trabalhado": "#00c853", "Não Trabalhou": "#ff4b4b",
                        "Férias": "#29b6f6", "Afastamento": "#ffb74d", "Abono": "#ff7043", "Folga / N.A.": "#e0e0e0"
                    }
                    contagem = df_status['Status'].value_counts().reset_index()
                    contagem.columns = ['Status', 'Qtd']
                    fig = px.pie(contagem, values='Qtd', names='Status', color='Status', color_discrete_map=color_map, hole=0.4)
                    st.plotly_chart(fig, use_container_width=True)

            with c_tab:
                def style_status(row):
                    if row['Status'] == 'Não Trabalhou': return ['background-color: #ffebee; color: #c62828'] * len(row)
                    elif row['Status'] == 'Trabalhado': return ['background-color: #e8f5e9; color: #2e7d32'] * len(row)
                    elif row['Status'] == 'Férias': return ['background-color: #e1f5fe; color: #0277bd'] * len(row)
                    return [''] * len(row)

                st.dataframe(
                    df_status.style.apply(style_status, axis=1), 
                    use_container_width=True, 
                    hide_index=True,
                    column_config={
                        "Icone": st.column_config.TextColumn(" ", width="small"),
                        "Nome": st.column_config.TextColumn("Colaborador", width="medium")
                    }
                )

    except Exception as e:
        st.error(f"Erro ao processar unidade: {e}")