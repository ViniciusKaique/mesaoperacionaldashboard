import streamlit as st
import pandas as pd
import requests
import concurrent.futures
from datetime import datetime

# ==============================================================================
# 1. CONFIGURAÇÃO DA PÁGINA
# ==============================================================================
st.set_page_config(
    page_title="Auditoria de Ponto",
    page_icon="🕵️‍♂️",
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
# 3. FUNÇÕES AUXILIARES
# ==============================================================================
def decimal_para_hora_str(valor_decimal):
    if not valor_decimal: return "00:00"
    horas = int(valor_decimal)
    minutos = int((valor_decimal - horas) * 60)
    return f"{horas:02d}:{minutos:02d}"

# ==============================================================================
# 4. FUNÇÕES DE API
# ==============================================================================

def fetch_lista_funcionarios_ativos(data_ref):
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
# 5. LÓGICA CENTRAL (PROCESSAMENTO INTELIGENTE)
# ==============================================================================

def analisar_funcionario(row, nr_periodo):
    id_func = row['ID']
    nome_func = row['Funcionario']
    escola = row['Escola']
    
    dias = fetch_detalhe_ponto(id_func, nr_periodo)
    
    if not dias:
        return {
            "ID": int(id_func), "Funcionario": nome_func, "Escola": escola,
            "Total_Dias": 0, "Nao_Apurado": 0, "Faltas": 0, 
            "Atraso_Horas": 0.0, "Status": "Sem Dados", "Algum_Trabalho": False
        }
        
    total_dias = len(dias)
    qtd_nao_apurado = 0
    qtd_faltas = 0
    atraso_acumulado_decimal = 0.0
    
    # Flag para saber se a pessoa trabalhou PELO MENOS UM DIA no período
    teve_algum_trabalho = False 
    
    for dia in dias:
        # Verifica se teve algum sinal de vida (Entrada ou Horas Trabalhadas > 0)
        entrada = dia.get("ENTRADA")
        trabalhado = dia.get("TRABALH")
        
        if (entrada is not None and entrada != ""):
            teve_algum_trabalho = True
        elif (trabalhado is not None and trabalhado != "0" and trabalhado != "00:00"):
            teve_algum_trabalho = True

        # 1. Contagem de Não Apurados
        if dia.get("ID_DIAAPURADO") == "N":
            qtd_nao_apurado += 1
            
        # 2. Contagem de Faltas (Lançadas no sistema)
        fl_dias = dia.get("FL_DIAS")
        if fl_dias is not None and str(fl_dias).strip() != "":
            qtd_faltas += 1
            
        # 3. Atrasos
        bh_desc = dia.get("BH_DESC_DIA")
        if bh_desc:
            try:
                val_str = str(bh_desc).replace(',', '.')
                valor = float(val_str)
                if valor < 0:
                    atraso_acumulado_decimal += abs(valor)
            except:
                pass

    # --- HIERARQUIA DE STATUS ---
    
    status = "✅ Regular"
    
    # REGRA PRIORITÁRIA: PONTO EM BRANCO
    # Se não trabalhou nenhum dia E tem dias no período
    if not teve_algum_trabalho and total_dias > 0:
        status = "⚪ PONTO TOTALMENTE EM BRANCO"
        # Opcional: Zerar contadores de falta para não poluir o outro gráfico, 
        # já que aqui o problema é macro (cadastro/abandono) e não dia-a-dia.
        # Mas mantivemos a contagem para referência.
        
    elif qtd_nao_apurado > 0:
        if qtd_nao_apurado == total_dias:
            status = "🚨 PENDENTE TOTAL (Nada Apurado)"
        else:
            status = "⚠️ Pendente Parcial"
            
    elif qtd_faltas > 0:
        if (qtd_faltas / total_dias) > 0.5:
            status = "🔥 Absenteísmo Crítico (>50%)"
        else:
            status = "❌ Com Faltas Pontuais"
            
    elif atraso_acumulado_decimal > 0:
        status = "📉 Com Atrasos"

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

st.title("🕵️‍♂️ Auditoria Avançada de Ponto")
st.markdown("""
Esta ferramenta diagnostica a saúde do ponto eletrônico com a seguinte prioridade:
1. **⚪ Ponto Totalmente em Branco**: Colaborador **sem nenhuma marcação** no período todo (Possível demissão não processada, licença ou abandono).
2. **🚨 Não Apurado**: Dias que o sistema ainda não processou.
3. **🔥 Absenteísmo Crítico**: Mais de 50% de faltas, mas com alguma presença.
4. **❌ Faltas e 📉 Atrasos**: Ocorrências pontuais.
""")

with st.sidebar:
    st.header("Parâmetros")
    data_ref = st.date_input("Data Base (Ativos)", datetime.now())
    nr_periodo = st.text_input("Cód. Período", value="1904")
    st.divider()
    btn_run = st.button("🚀 Processar Diagnóstico", type="primary", use_container_width=True)

if btn_run:
    if not nr_periodo:
        st.error("Informe o Código do Período.")
        st.stop()
        
    with st.status("🔄 Executando varredura inteligente...", expanded=True) as status:
        status.write("Obtendo funcionários em Atividade Normal...")
        df_funcionarios = fetch_lista_funcionarios_ativos(data_ref)
        
        if df_funcionarios.empty:
            status.update(label="❌ Ninguém encontrado.", state="error")
            st.stop()
            
        total = len(df_funcionarios)
        status.write(f"✅ {total} colaboradores listados.")
        status.write("🚀 Analisando cartões de ponto (25 conexões simultâneas)...")
        
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
        
        status.update(label="Diagnóstico Concluído!", state="complete", expanded=False)

    # TRATAMENTO
    df = pd.DataFrame(resultados)
    df['Tempo Atraso'] = df['Atraso_Horas'].apply(decimal_para_hora_str)
    
    # --- MÉTRICAS ---
    total_funcs = len(df)
    
    # 1. Grupo Crítico: Ponto em Branco
    df_branco = df[df['Status'] == "⚪ PONTO TOTALMENTE EM BRANCO"]
    count_branco = len(df_branco)
    
    # 2. Grupo: Apurados 100% OK (Sem pendencia, sem branco, sem falta, sem atraso)
    df_ok = df[df['Status'] == "✅ Regular"]
    count_ok = len(df_ok)
    
    # 3. Grupo: Faltas (Excluindo os "Em branco")
    # Pega quem tem falta > 0 MAS NÃO está no status de "Em branco"
    total_faltas_reais = df[df['Status'] != "⚪ PONTO TOTALMENTE EM BRANCO"]['Faltas'].sum()

    st.markdown("### 📊 Resultado da Auditoria")
    
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Analisado", total_funcs)
    k2.metric("Ponto em Branco (Crítico)", count_branco, delta_color="inverse", help="Funcionários sem NENHUM registro no período inteiro.")
    k3.metric("Faltas Totais (Reais)", int(total_faltas_reais), help="Soma das faltas de quem está trabalhando.")
    k4.metric("Atrasos (Horas)", f"{df['Atraso_Horas'].sum():.1f}h")
    
    st.divider()
    
    # ABAS
    tab_branco, tab_faltas, tab_pend, tab_atraso, tab_geral = st.tabs([
        "⚪ Totalmente em Branco", 
        "❌ Ranking Faltas", 
        "🚨 Pendências Apuração",
        "📉 Ranking Atrasos",
        "📋 Visão Geral"
    ])
    
    with tab_branco:
        st.subheader(f"Funcionários sem registro algum no período ({count_branco})")
        st.warning("⚠️ Estes colaboradores constam como 'Ativos', mas não têm nenhuma entrada ou hora trabalhada no período. Verifique se são desligamentos não processados ou licenças.")
        st.dataframe(
            df_branco[['ID', 'Funcionario', 'Escola', 'Total_Dias']],
            use_container_width=True,
            hide_index=True
        )

    with tab_faltas:
        st.subheader("Quem está trabalhando mas possui Faltas")
        # Filtra fora os brancos para não poluir
        df_f = df[(df['Faltas'] > 0) & (df['Status'] != "⚪ PONTO TOTALMENTE EM BRANCO")].sort_values(by='Faltas', ascending=False)
        st.dataframe(
            df_f[['ID', 'Funcionario', 'Escola', 'Faltas', 'Status']],
            use_container_width=True,
            hide_index=True
        )

    with tab_pend:
        st.subheader("Pendências de Apuração (Sistema)")
        df_pend = df[df['Nao_Apurado'] > 0].sort_values(by='Nao_Apurado', ascending=False)
        st.dataframe(
            df_pend[['ID', 'Funcionario', 'Escola', 'Nao_Apurado', 'Status']],
            use_container_width=True,
            hide_index=True,
            column_config={"Nao_Apurado": st.column_config.ProgressColumn("Dias Pendentes", format="%d", min_value=0, max_value=30)}
        )
        
    with tab_atraso:
        st.subheader("Acúmulo de Atrasos (Horas)")
        df_atrasos = df[df['Atraso_Horas'] > 0].sort_values(by='Atraso_Horas', ascending=False)
        st.dataframe(
            df_atrasos[['ID', 'Funcionario', 'Escola', 'Tempo Atraso', 'Faltas']],
            use_container_width=True,
            hide_index=True
        )

    with tab_geral:
        st.subheader("Base Completa")
        st.dataframe(df, use_container_width=True, hide_index=True)
        csv = df.to_csv(index=False, sep=';', encoding='utf-8-sig')
        st.download_button("📥 Baixar CSV Completo", csv, "auditoria_ponto_completa.csv", "text/csv")