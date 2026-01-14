import streamlit as st
import pandas as pd
import requests
import concurrent.futures
import time
from datetime import datetime

# ==============================================================================
# 1. CONFIGURAÇÃO DA PÁGINA
# ==============================================================================
st.set_page_config(
    page_title="Diagnóstico de Ponto",
    page_icon="⏱️",
    layout="wide"
)

# ==============================================================================
# 2. SEGURANÇA E CREDENCIAIS
# ==============================================================================
if not st.session_state.get("authentication_status"):
    st.warning("🔒 Acesso restrito. Faça login na página inicial.")
    st.stop()

try:
    api_creds = st.secrets["api_portal_gestor"]
    TOKEN_FIXO = api_creds["token_fixo"]
    CD_OPERADOR = api_creds["cd_operador"]
    NR_ORG = api_creds["nr_org"]
except Exception as e:
    st.error("⚠️ Erro de Configuração: Credenciais não encontradas no secrets.toml.")
    st.stop()

# ==============================================================================
# 3. FUNÇÕES DE SUPORTE (FORMATACAO)
# ==============================================================================
def decimal_para_hora_str(valor_decimal):
    """Converte 1.50 para '01:30', por exemplo."""
    if not valor_decimal: return "00:00"
    horas = int(valor_decimal)
    minutos = int((valor_decimal - horas) * 60)
    return f"{horas:02d}:{minutos:02d}"

# ==============================================================================
# 4. FUNÇÕES DE API
# ==============================================================================

def fetch_lista_funcionarios_ativos(data_ref):
    """
    Busca funcionários onde NMSITUFUNCH == 'Atividade Normal'.
    """
    url = "https://portalgestor.teknisa.com/backend/index.php/getMesaOperacoes"
    data_str = data_ref.strftime("%d/%m/%Y")
    
    params = {
        "requestType": "FilterData",
        "DIA": data_str,
        "NRESTRUTURAM": "101091998",
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
                if not df.empty and 'NMSITUFUNCH' in df.columns:
                    # Filtra apenas Atividade Normal
                    df = df[df['NMSITUFUNCH'].str.strip() == 'Atividade Normal']
                    if not df.empty:
                        return df[['NRVINCULOM', 'NMVINCULOM', 'NMESTRUTGEREN']].rename(columns={
                            'NRVINCULOM': 'ID',
                            'NMVINCULOM': 'Funcionario',
                            'NMESTRUTGEREN': 'Escola'
                        })
    except Exception as e:
        st.error(f"Erro Lista: {e}")
    return pd.DataFrame()

def fetch_detalhe_ponto(id_funcionario, nr_periodo):
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
# 5. LÓGICA CENTRAL (PROCESSAMENTO)
# ==============================================================================

def analisar_funcionario(row, nr_periodo):
    """
    Retorna métricas completas do funcionário, mesmo que esteja tudo OK.
    """
    id_func = row['ID']
    nome_func = row['Funcionario']
    escola = row['Escola']
    
    dias = fetch_detalhe_ponto(id_func, nr_periodo)
    
    if not dias:
        # Se não trouxe dias, pode ser erro ou período sem dados
        return {
            "ID": int(id_func), "Funcionario": nome_func, "Escola": escola,
            "Total_Dias": 0, "Nao_Apurado": 0, "Faltas": 0, 
            "Atraso_Horas": 0.0, "Status": "Sem Dados"
        }
        
    total_dias = len(dias)
    qtd_nao_apurado = 0
    qtd_faltas = 0
    atraso_acumulado_decimal = 0.0
    
    for dia in dias:
        # 1. Contagem de Não Apurados
        if dia.get("ID_DIAAPURADO") == "N":
            qtd_nao_apurado += 1
            
        # 2. Contagem de Faltas
        fl_dias = dia.get("FL_DIAS")
        if fl_dias is not None and str(fl_dias).strip() != "":
            qtd_faltas += 1
        else:
            # 3. Soma de Atrasos (Se não for falta)
            bh_desc = dia.get("BH_DESC_DIA")
            if bh_desc:
                try:
                    # Ex: "-7.71" ou "-0,50" -> converte para float
                    val_str = str(bh_desc).replace(',', '.')
                    valor = float(val_str)
                    if valor < 0:
                        atraso_acumulado_decimal += abs(valor) # Soma positivo para o KPI
                except:
                    pass

    # DEFINIÇÃO DE STATUS
    status = "✅ OK"
    if total_dias > 0 and qtd_nao_apurado == total_dias:
        status = "🚨 PONTO ZERADO (Totalmente Aberto)"
    elif qtd_nao_apurado > 0:
        status = "⚠️ Pendente Parcial"
    
    # Se tiver muitas faltas (>50%)
    if total_dias > 0 and (qtd_faltas / total_dias) > 0.5:
        status = "🔥 Absenteísmo Crítico"

    return {
        "ID": int(id_func),
        "Funcionario": nome_func,
        "Escola": escola,
        "Total_Dias": total_dias,
        "Nao_Apurado": qtd_nao_apurado,
        "Faltas": qtd_faltas,
        "Atraso_Horas": atraso_acumulado_decimal,
        "Status": status
    }

# ==============================================================================
# 6. INTERFACE
# ==============================================================================

st.title("⏱️ Monitoramento de Ponto & Atrasos")
st.caption("Diagnóstico de performance, atrasos acumulados e dias não apurados.")

with st.sidebar:
    st.header("Parâmetros")
    data_ref = st.date_input("Data Base (Ativos)", datetime.now())
    nr_periodo = st.text_input("Cód. Período", value="1904")
    st.divider()
    btn_run = st.button("🚀 Processar Agora", type="primary", use_container_width=True)

if btn_run:
    if not nr_periodo:
        st.error("Informe o Código do Período.")
        st.stop()
        
    with st.status("🔄 Executando varredura rápida...", expanded=True) as status:
        # 1. LISTA
        status.write("Obtendo funcionários em Atividade Normal...")
        df_funcionarios = fetch_lista_funcionarios_ativos(data_ref)
        
        if df_funcionarios.empty:
            status.update(label="❌ Ninguém encontrado.", state="error")
            st.stop()
            
        total = len(df_funcionarios)
        status.write(f"✅ {total} colaboradores listados.")
        status.write("🚀 Baixando cartões de ponto (25 conexões simultâneas)...")
        
        # 2. PROCESSAMENTO (25 WORKERS PARA VELOCIDADE)
        resultados = []
        pbar = st.progress(0)
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=25) as executor:
            futures = {executor.submit(analisar_funcionario, row, nr_periodo): row for _, row in df_funcionarios.iterrows()}
            done = 0
            for future in concurrent.futures.as_completed(futures):
                res = future.result()
                resultados.append(res)
                done += 1
                pbar.progress(done / total)
        
        status.update(label="Concluído!", state="complete", expanded=False)

    # 3. TRATAMENTO DOS DADOS
    df = pd.DataFrame(resultados)
    
    # Coluna Formatada de Horas
    df['Tempo Atraso'] = df['Atraso_Horas'].apply(decimal_para_hora_str)
    
    # KPIs GERAIS
    total_funcs = len(df)
    total_ok = len(df[ (df['Nao_Apurado'] == 0) & (df['Status'] != "Sem Dados") ])
    total_zerados = len(df[df['Status'].str.contains("PONTO ZERADO")])
    total_criticos = len(df[ (df['Faltas'] / df['Total_Dias'].replace(0,1)) > 0.5 ])
    
    perc_apurado = (total_ok / total_funcs * 100) if total_funcs > 0 else 0
    
    # DISPLAY KPIs
    st.markdown("### 📊 Visão Geral do Período")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Analisado", total_funcs)
    k2.metric("Totalmente Apurados", f"{total_ok} ({perc_apurado:.1f}%)", help="Funcionários com zero dias pendentes.")
    k3.metric("Ponto Zerado (Em Branco)", total_zerados, delta_color="inverse", help="Funcionários que não tiveram NENHUM dia apurado.")
    k4.metric("Absenteísmo Crítico (>50%)", total_criticos, delta_color="inverse")
    
    st.divider()
    
    # ABAS PARA ORGANIZAÇÃO
    tab1, tab2, tab3, tab4 = st.tabs(["📉 Ranking de Atrasos", "🚨 Pendências de Apuração", "🔥 Absenteísmo Alto", "📋 Lista Geral"])
    
    with tab1:
        st.subheader("Top Atrasos Acumulados (Horas)")
        # Filtra quem tem atraso > 0 e ordena
        df_atrasos = df[df['Atraso_Horas'] > 0].sort_values(by='Atraso_Horas', ascending=False)
        
        st.dataframe(
            df_atrasos[['ID', 'Funcionario', 'Escola', 'Tempo Atraso', 'Faltas']],
            use_container_width=True,
            hide_index=True,
            column_config={
                "ID": st.column_config.NumberColumn("Matrícula", format="%d"),
                "Tempo Atraso": st.column_config.TextColumn("Tempo Total", help="Soma das horas negativas convertidas."),
                "Faltas": st.column_config.NumberColumn("Qtd. Faltas")
            }
        )
    
    with tab2:
        st.subheader("Dias Não Apurados / Ponto em Branco")
        # Filtra quem tem pendencia
        df_pend = df[df['Nao_Apurado'] > 0].sort_values(by=['Nao_Apurado'], ascending=False)
        
        st.dataframe(
            df_pend[['ID', 'Funcionario', 'Escola', 'Status', 'Nao_Apurado', 'Total_Dias']],
            use_container_width=True,
            hide_index=True,
            column_config={
                "Nao_Apurado": st.column_config.ProgressColumn("Dias Pendentes", format="%d", min_value=0, max_value=30),
                "Status": st.column_config.TextColumn("Diagnóstico")
            }
        )
        
    with tab3:
        st.subheader("Funcionários com > 50% de Falta")
        df_crit = df[ (df['Faltas'] / df['Total_Dias'].replace(0,1)) > 0.5 ].sort_values(by='Faltas', ascending=False)
        st.dataframe(
            df_crit[['ID', 'Funcionario', 'Escola', 'Faltas', 'Total_Dias', 'Tempo Atraso']],
            use_container_width=True,
            hide_index=True
        )

    with tab4:
        st.subheader("Base Completa")
        st.dataframe(df, use_container_width=True, hide_index=True)
        
        csv = df.to_csv(index=False, sep=';', encoding='utf-8-sig')
        st.download_button("📥 Baixar Planilha Completa", csv, "diagnostico_ponto.csv", "text/csv")