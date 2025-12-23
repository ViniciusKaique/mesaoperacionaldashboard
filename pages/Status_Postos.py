import streamlit as st
import pandas as pd
import requests
import plotly.express as px
from datetime import datetime

# --- FUNÇÕES DE API ---
def get_headers():
    secrets = st.secrets["api_teknisa"]
    return {
        "accept": "application/json, text/plain, */*",
        "oauth-cdoperador": secrets["cd_operador"],
        "oauth-nrorg": secrets["nr_org"],
        "oauth-token": secrets["token"],
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

@st.cache_data(ttl=3600) # Cache de 1 hora para periodos
def get_periodo_aberto():
    url = f"{st.secrets['api_teknisa']['base_url']}/getPeriodosDemonstrativo"
    params = {
        "requestType": "FilterData",
        "NRORG": st.secrets["api_teknisa"]["nr_org"],
        "CDOPERADOR": st.secrets["api_teknisa"]["cd_operador"]
    }
    
    try:
        response = requests.get(url, headers=get_headers(), params=params)
        data = response.json()
        
        # Filtra apenas os ABERTOS e pega o maior NRPERIODOAPURACAO
        periodos = [p for p in data['dataset']['data'] if p['IDPERIODOAPURACAO'] == 'ABERTO']
        if periodos:
            # Ordena decrescente pelo número do periodo e pega o primeiro
            periodo_atual = sorted(periodos, key=lambda x: int(x['NRPERIODOAPURACAO']), reverse=True)[0]
            return periodo_atual
        return None
    except Exception as e:
        st.error(f"Erro ao buscar período: {e}")
        return None

def get_mesa_operacoes(data_consulta, unidade_id):
    url = f"{st.secrets['api_teknisa']['base_url']}/getMesaOperacoes"
    params = {
        "requestType": "FilterData",
        "DIA": data_consulta, # Formato DD/MM/YYYY
        "NRESTRUTURAM": unidade_id,
        "NRORG": st.secrets["api_teknisa"]["nr_org"],
        "CDOPERADOR": st.secrets["api_teknisa"]["cd_operador"]
    }
    
    try:
        response = requests.get(url, headers=get_headers(), params=params)
        return response.json()['dataset']['data']
    except Exception as e:
        # Se der erro (ex: unidade não encontrada na API), retorna lista vazia
        return []

# --- LÓGICA DE NEGÓCIO (Port do Vue.js) ---
def processar_status(funcionario):
    """
    Replica a lógica de prioridade:
    1. Férias
    2. Afastamento
    3. Abono
    4. Trabalhado (se tem hora trabalhada registrada)
    5. Falta (se tem escala mas não tem trabalho)
    """
    # Verifica Flags
    if funcionario.get('IS_FERIAS') == 'S':
        return "Férias", "🟦" # Azul Claro
    if funcionario.get('IS_AFASTAMENTO') == 'S':
        return "Afastamento", "🟧" # Laranja Claro
    if funcionario.get('IS_ABONO') == 'S':
        return "Abono", "Dv" # Laranja Escuro
    
    # Verifica Horas
    horas_escala = funcionario.get('horas_escala', [])
    horas_trabalhadas = funcionario.get('horas_trabalhadas', [])
    
    # Se tem registro de trabalho (mesmo que parcial)
    if len(horas_trabalhadas) > 0:
        return "Trabalhado", "🟩" # Verde
    
    # Se tem escala mas NÃO tem trabalho
    if len(horas_escala) > 0 and len(horas_trabalhadas) == 0:
        return "Não Trabalhou", "🟥" # Vermelho
        
    return "Folga / N.A.", "⬜" # Cinza

# --- PÁGINA PRINCIPAL ---
def show_status_postos(conn):
    st.title("📍 Status Postos (Tempo Real)")
    st.info("Dados sincronizados diretamente da Mesa de Operações.")

    # 1. Obter Período Atual
    periodo = get_periodo_aberto()
    if not periodo:
        st.error("Não foi possível identificar um período de apuração aberto.")
        st.stop()
        
    # Data de hoje para consulta
    hoje_str = datetime.now().strftime("%d/%m/%Y")
    
    # 2. Seleção de Unidade (Integrado ao seu banco SQL existente)
    df_unidades = conn.query('SELECT "UnidadeID", "NomeUnidade", "CodigoExterno" FROM "Unidades" ORDER BY "NomeUnidade"', ttl=600)
    
    col_filtro, col_data = st.columns([3, 1])
    with col_filtro:
        unidade_selecionada = st.selectbox("Selecione a Unidade:", df_unidades['NomeUnidade'].unique())
    with col_data:
        st.markdown(f"**Período:** {periodo['DSPERIODOAPURACAO']}")
        st.markdown(f"**Data Ref:** {hoje_str}")

    # Pega o ID para a API (Supomos que 'CodigoExterno' no SQL seja o 'NRESTRUTURAM' da API)
    # Se não tiver essa coluna, precisará fazer um De/Para manual ou usar o UnidadeID convertendo string
    try:
        row_unidade = df_unidades[df_unidades['NomeUnidade'] == unidade_selecionada].iloc[0]
        # AJUSTE AQUI: Qual campo do seu banco corresponde ao '101091998' da API?
        # Vou assumir que é o UnidadeID ou um campo CodigoExterno.
        id_api = str(row_unidade['UnidadeID']) 
    except:
        st.error("Erro ao vincular unidade.")
        st.stop()

    if st.button("🔄 Atualizar Dados da Mesa"):
        st.cache_data.clear()
        st.rerun()

    with st.spinner(f"Buscando dados da mesa para {unidade_selecionada}..."):
        dados_api = get_mesa_operacoes(hoje_str, id_api)

    if not dados_api:
        st.warning("Nenhum dado encontrado na Mesa de Operações para esta unidade hoje.")
    else:
        # 3. Processamento dos Dados
        lista_processada = []
        for func in dados_api:
            status_txt, icon = processar_status(func)
            lista_processada.append({
                "Nome": func.get('NMVINCULOM', 'Sem Nome'),
                "Cargo": func.get('NMESTRUTGEREN', 'Geral'), # Ou outro campo de cargo da API
                "Status": status_txt,
                "Icone": icon,
                "Entrada": func.get('horas_trabalhadas', [['--:--']])[0][0] if func.get('horas_trabalhadas') else "--:--",
                "Escala": func.get('horas_escala', [['--:--']])[0][0] if func.get('horas_escala') else "Sem Escala"
            })
        
        df_status = pd.DataFrame(lista_processada)

        # 4. KPIs
        total = len(df_status)
        faltas = len(df_status[df_status['Status'] == 'Não Trabalhou'])
        presentes = len(df_status[df_status['Status'] == 'Trabalhado'])
        outros = total - faltas - presentes

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Total Previsto", total)
        k2.metric("Presentes", presentes, delta=f"{round((presentes/total)*100,1)}%" if total else 0)
        k3.metric("Possíveis Faltas", faltas, delta_color="inverse")
        k4.metric("Afast./Férias", outros)

        # 5. Gráfico e Tabela
        st.markdown("---")
        c_graf, c_tab = st.columns([1, 2])

        with c_graf:
            st.subheader("Distribuição")
            if not df_status.empty:
                contagem = df_status['Status'].value_counts().reset_index()
                contagem.columns = ['Status', 'Qtd']
                
                # Cores baseadas na Legenda
                color_map = {
                    "Trabalhado": "#00c853", # Verde
                    "Não Trabalhou": "#ff4b4b", # Vermelho
                    "Férias": "#29b6f6", # Azul
                    "Afastamento": "#ffb74d", # Laranja Claro
                    "Abono": "#ff7043", # Laranja Escuro
                    "Folga / N.A.": "#e0e0e0"
                }
                
                fig = px.pie(contagem, values='Qtd', names='Status', color='Status', 
                             color_discrete_map=color_map, hole=0.4)
                st.plotly_chart(fig, use_container_width=True)

        with c_tab:
            st.subheader("Detalhamento de Colaboradores")
            
            # Filtro Rápido na Tabela
            filtro_status_tab = st.multiselect("Filtrar Status:", df_status['Status'].unique(), default=df_status['Status'].unique())
            
            df_show = df_status[df_status['Status'].isin(filtro_status_tab)]
            
            # Estilização da Tabela
            def style_status_rows(row):
                if row['Status'] == 'Não Trabalhou':
                    return ['background-color: #ffebee; color: #c62828'] * len(row)
                elif row['Status'] == 'Trabalhado':
                    return ['background-color: #e8f5e9; color: #2e7d32'] * len(row)
                elif row['Status'] == 'Férias':
                    return ['background-color: #e1f5fe; color: #0277bd'] * len(row)
                return [''] * len(row)

            st.dataframe(
                df_show[['Icone', 'Nome', 'Status', 'Escala', 'Entrada']],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Icone": st.column_config.TextColumn(" ", width="small"),
                    "Nome": st.column_config.TextColumn("Colaborador", width="large"),
                }
            )

# Chamar a função se estiver na aba correta
# show_status_postos(conn)