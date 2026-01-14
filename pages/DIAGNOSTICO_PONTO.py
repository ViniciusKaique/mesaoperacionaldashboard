import streamlit as st
import pandas as pd
import requests
import concurrent.futures
from datetime import datetime

# ==============================================================================
# 1. CONFIGURAÇÃO DA PÁGINA
# ==============================================================================
st.set_page_config(
    page_title="Diagnóstico de Ponto",
    page_icon="🕵️‍♀️",
    layout="wide"
)

# ==============================================================================
# 2. SEGURANÇA E CREDENCIAIS (DO SECRETS)
# ==============================================================================
if not st.session_state.get("authentication_status"):
    st.warning("🔒 Acesso restrito. Faça login na página inicial.")
    st.stop()

# Carrega TUDO do st.secrets["api_portal_gestor"]
try:
    api_creds = st.secrets["api_portal_gestor"]
    
    TOKEN_FIXO = api_creds["token_fixo"]
    CD_OPERADOR = api_creds["cd_operador"] # Agora pega direto do secrets
    NR_ORG = api_creds["nr_org"]           # Agora pega direto do secrets
    
except Exception as e:
    st.error("⚠️ Erro de Configuração: As credenciais (token_fixo, cd_operador, nr_org) não foram encontradas no secrets.toml.")
    st.error(f"Detalhe do erro: {e}")
    st.stop()

# ==============================================================================
# 3. FUNÇÕES DE API
# ==============================================================================

def fetch_lista_funcionarios(data_ref):
    """
    Busca a lista de funcionários ativos usando getMesaOperacoes
    para pegar os IDs (NRVINCULOM).
    """
    url = "https://portalgestor.teknisa.com/backend/index.php/getMesaOperacoes"
    data_str = data_ref.strftime("%d/%m/%Y")
    
    params = {
        "requestType": "FilterData",
        "DIA": data_str,
        "NRESTRUTURAM": "101091998", # Estrutura padrão (ajustar se necessário)
        "NRORG": NR_ORG,
        "CDOPERADOR": CD_OPERADOR
    }
    
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "OAuth-Token": TOKEN_FIXO,
        "OAuth-Cdoperador": CD_OPERADOR,
        "OAuth-Nrorg": NR_ORG
    }
    
    try:
        r = requests.get(url, params=params, headers=headers, timeout=30)
        if r.status_code == 200:
            data = r.json()
            if "dataset" in data and "data" in data["dataset"]:
                df = pd.DataFrame(data["dataset"]["data"])
                if not df.empty:
                    # Retorna DF limpo com colunas essenciais
                    return df[['NRVINCULOM', 'NMVINCULOM', 'NMESTRUTGEREN']].rename(columns={
                        'NRVINCULOM': 'ID',
                        'NMVINCULOM': 'Funcionario',
                        'NMESTRUTGEREN': 'Escola'
                    })
    except Exception as e:
        st.error(f"Erro ao buscar lista de funcionários: {e}")
    
    return pd.DataFrame()

def fetch_detalhe_ponto(id_funcionario, nr_periodo):
    """
    Busca o detalhe dos dias (cartão de ponto) para um ID específico.
    """
    url = "https://portalgestor.teknisa.com/backend/index.php/getDiasDemonstrativo"
    
    params = {
        "requestType": "FilterData",
        "NRVINCULOM": str(id_funcionario),
        "NRPERIODOAPURACAO": str(nr_periodo),
        "NRORG": NR_ORG,
        "CDOPERADOR": CD_OPERADOR
    }
    
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "OAuth-Token": TOKEN_FIXO,
        "OAuth-Cdoperador": CD_OPERADOR,
        "OAuth-Nrorg": NR_ORG
    }
    
    try:
        r = requests.get(url, params=params, headers=headers, timeout=20)
        if r.status_code == 200:
            data = r.json()
            if "dataset" in data and "data" in data["dataset"]:
                return data["dataset"]["data"]
    except:
        pass
    return []

# ==============================================================================
# 4. LÓGICA DE DIAGNÓSTICO
# ==============================================================================

def analisar_funcionario(row, nr_periodo):
    """
    Processa as regras de negócio:
    1. ID_DIAAPURADO == 'N' -> Não Apurado
    2. FL_DIAS preenchido -> Falta
    3. BH_DESC_DIA negativo -> Atraso
    """
    id_func = row['ID']
    nome_func = row['Funcionario']
    escola = row['Escola']
    
    dias = fetch_detalhe_ponto(id_func, nr_periodo)
    
    if not dias:
        return None 
        
    qtd_nao_apurado = 0
    qtd_atrasos = 0
    qtd_faltas = 0
    detalhes_log = []
    
    for dia in dias:
        data_dia = dia.get("DIA", "")
        
        # REGRA 1: NÃO APURADO
        if dia.get("ID_DIAAPURADO") == "N":
            qtd_nao_apurado += 1
            detalhes_log.append(f"{data_dia} (Pendente Apuração)")
            
        # REGRA 2: FALTAS (FL_DIAS possui valor)
        fl_dias = dia.get("FL_DIAS")
        if fl_dias is not None and str(fl_dias).strip() != "":
            qtd_faltas += 1
            detalhes_log.append(f"{data_dia} (Falta)")
        
        # REGRA 3: ATRASOS (BH_DESC_DIA < 0)
        # (Consideramos atraso apenas se não for falta integral)
        else:
            bh_desc = dia.get("BH_DESC_DIA")
            if bh_desc:
                try:
                    # Troca vírgula por ponto para converter
                    val_str = str(bh_desc).replace(',', '.')
                    valor = float(val_str)
                    if valor < 0:
                        qtd_atrasos += 1
                        detalhes_log.append(f"{data_dia} (Atraso: {valor}h)")
                except:
                    pass

    # Se encontrou algum problema, retorna o objeto
    if qtd_nao_apurado > 0 or qtd_atrasos > 0 or qtd_faltas > 0:
        return {
            "ID": int(id_func),
            "Funcionario": nome_func,
            "Escola": escola,
            "Nao_Apurado": qtd_nao_apurado,
            "Faltas": qtd_faltas,
            "Atrasos": qtd_atrasos,
            "Log": "; ".join(detalhes_log)
        }
    return None

# ==============================================================================
# 5. INTERFACE (FRONT-END)
# ==============================================================================

st.title("🕵️‍♀️ Diagnóstico de Apuração de Ponto")
st.markdown("Auditoria completa de **Faltas**, **Atrasos** e **Dias Não Apurados** via API.")

# --- SIDEBAR DE FILTROS ---
with st.sidebar:
    st.header("⚙️ Parâmetros")
    
    # Data usada apenas para buscar quem está ativo na 'Mesa' hoje
    data_ref = st.date_input("Data Base (Status Ativo)", datetime.now())
    
    # Campo para o código do período (ex: 1904)
    nr_periodo = st.text_input("Cód. Período Apuração", value="1904", help="Ex: 1904. Verifique no Portal Gestor qual o período aberto.")
    
    st.info(f"🔑 Operador: {CD_OPERADOR}\n🏢 Org: {NR_ORG}")
    
    st.divider()
    btn_run = st.button("🚀 Executar Diagnóstico", type="primary", use_container_width=True)

# --- EXECUÇÃO ---
if btn_run:
    if not nr_periodo:
        st.error("Informe o Código do Período de Apuração.")
        st.stop()
        
    # 1. Busca lista de funcionários
    with st.status("🔄 Conectando ao Portal Gestor...", expanded=True) as status:
        status.write("Obtendo lista de colaboradores ativos...")
        df_funcionarios = fetch_lista_funcionarios(data_ref)
        
        if df_funcionarios.empty:
            status.update(label="❌ Erro: Nenhum funcionário encontrado ou falha na API.", state="error")
            st.stop()
            
        total_funcs = len(df_funcionarios)
        status.write(f"✅ Lista carregada: **{total_funcs}** colaboradores.")
        status.write("🔍 Analisando cartões de ponto individualmente (Multithreading)...")
        
        # 2. Processamento Paralelo (rápido)
        resultados = []
        progress_bar = st.progress(0)
        
        # Max Workers = 10 requisições simultâneas
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(analisar_funcionario, row, nr_periodo): row for _, row in df_funcionarios.iterrows()}
            
            concluidos = 0
            for future in concurrent.futures.as_completed(futures):
                res = future.result()
                if res:
                    resultados.append(res)
                
                concluidos += 1
                progress_bar.progress(concluidos / total_funcs)
        
        status.update(label="✅ Diagnóstico Finalizado!", state="complete", expanded=False)

    # 3. Resultados
    st.divider()
    
    if resultados:
        df_res = pd.DataFrame(resultados)
        
        # Ordenar por criticidade (Faltas > Não Apurado > Atrasos)
        df_res = df_res.sort_values(by=['Faltas', 'Nao_Apurado', 'Atrasos'], ascending=False)
        
        # Placar Geral
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Funcionários c/ Ocorrência", len(df_res))
        col2.metric("Total Faltas", df_res['Faltas'].sum())
        col3.metric("Dias Pendentes (N. Apurado)", df_res['Nao_Apurado'].sum())
        col4.metric("Ocorrências de Atraso", df_res['Atrasos'].sum())
        
        st.subheader("📋 Detalhamento")
        
        st.dataframe(
            df_res,
            use_container_width=True,
            hide_index=True,
            column_config={
                "ID": st.column_config.NumberColumn("Matrícula", format="%d"),
                "Funcionario": st.column_config.TextColumn("Colaborador"),
                "Nao_Apurado": st.column_config.ProgressColumn("Pendências", format="%d", min_value=0, max_value=30),
                "Faltas": st.column_config.NumberColumn("Faltas", format="%d ❌"),
                "Atrasos": st.column_config.NumberColumn("Atrasos", format="%d ⚠️"),
                "Log": st.column_config.TextColumn("Detalhes (Datas)", width="large")
            }
        )
        
        # Download
        csv = df_res.to_csv(index=False, sep=';', encoding='utf-8-sig')
        st.download_button(
            label="📥 Baixar Relatório (CSV)",
            data=csv,
            file_name=f"diagnostico_periodo_{nr_periodo}_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv"
        )
        
    else:
        st.balloons()
        st.success(f"🎉 Tudo limpo! Nenhuma pendência encontrada para os {total_funcs} funcionários no período {nr_periodo}.")