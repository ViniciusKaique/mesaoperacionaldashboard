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
# 5. LÓGICA CENTRAL (PROCESSAMENTO)
# ==============================================================================

def analisar_funcionario(row, nr_periodo):
    """
    Analisa os dias para classificar em: Não Apurado, Faltas, Atrasos ou Ponto Vazio.
    """
    id_func = row['ID']
    nome_func = row['Funcionario']
    escola = row['Escola']
    
    dias = fetch_detalhe_ponto(id_func, nr_periodo)
    
    if not dias:
        return {
            "ID": int(id_func), "Funcionario": nome_func, "Escola": escola,
            "Total_Dias": 0, "Nao_Apurado": 0, "Faltas": 0, 
            "Pontos_Vazios": 0, "Atraso_Horas": 0.0, "Status": "Sem Dados"
        }
        
    total_dias = len(dias)
    qtd_nao_apurado = 0
    qtd_faltas = 0
    qtd_pontos_vazios = 0
    atraso_acumulado_decimal = 0.0
    
    for dia in dias:
        # 1. NÃO APURADO (Prioridade Máxima)
        if dia.get("ID_DIAAPURADO") == "N":
            qtd_nao_apurado += 1
            continue # Se não está apurado, não verificamos o resto

        # Se chegou aqui, ID_DIAAPURADO == 'S'
        
        # 2. FALTA (Se FL_DIAS tem valor)
        fl_dias = dia.get("FL_DIAS")
        has_falta = fl_dias is not None and str(fl_dias).strip() != ""
        
        if has_falta:
            qtd_faltas += 1
        
        else:
            # Não é falta explícita, vamos ver se é ATRASO ou PONTO VAZIO
            
            # Checagem de Ponto Vazio (Sem batida e sem falta)
            # Regra: Apurado 'S', Normal, Sem Entrada, Sem Falta
            entrada = dia.get("ENTRADA")
            tipo_horario = dia.get("DSTIPOHORARIO")
            is_feriado = dia.get("OCORRENCIA_FERIADO")
            
            # Consideramos vazio se for dia Normal, não for feriado, e não tiver entrada
            if (tipo_horario == "Normal" and 
                not is_feriado and 
                (entrada is None or entrada == "")):
                
                qtd_pontos_vazios += 1
            
            else:
                # 3. ATRASOS (Só conta se não for Falta nem Vazio completo)
                bh_desc = dia.get("BH_DESC_DIA")
                if bh_desc:
                    try:
                        val_str = str(bh_desc).replace(',', '.')
                        valor = float(val_str)
                        if valor < 0:
                            atraso_acumulado_decimal += abs(valor)
                    except:
                        pass

    # --- DEFINIÇÃO DE STATUS HIERÁRQUICO ---
    # Ordem pedida: Não Apurado > Faltas > Atrasos (e Vazios entram no meio para alerta)
    
    status = "✅ 100% Apurado e OK"
    
    if qtd_nao_apurado > 0:
        if qtd_nao_apurado == total_dias:
            status = "🚨 PENDENTE TOTAL (Nada Apurado)"
        else:
            status = "⚠️ Pendente Parcial"
    
    elif qtd_faltas > 0:
        if (qtd_faltas / total_dias) > 0.5:
            status = "🔥 Absenteísmo Crítico (>50%)"
        else:
            status = "❌ Com Faltas"
            
    elif qtd_pontos_vazios > 0:
        status = "⚪ Ponto Vazio (Sem Batida/Falta)"
        
    elif atraso_acumulado_decimal > 0:
        status = "📉 Com Atrasos"

    return {
        "ID": int(id_func),
        "Funcionario": nome_func,
        "Escola": escola,
        "Total_Dias": total_dias,
        "Nao_Apurado": qtd_nao_apurado,
        "Faltas": qtd_faltas,
        "Pontos_Vazios": qtd_pontos_vazios,
        "Atraso_Horas": atraso_acumulado_decimal,
        "Status": status
    }

# ==============================================================================
# 6. INTERFACE
# ==============================================================================

st.title("⏱️ Diagnóstico de Apuração e Ocorrências")
st.markdown("""
**Critérios de Análise:**
1. **Não Apurado**: Dias com `ID_DIAAPURADO = 'N'`.
2. **Faltas**: Dias apurados com lançamento em `FL_DIAS`.
3. **Pontos Vazios**: Dias apurados, normais, **sem batida** e **sem falta lançada**.
4. **Atrasos**: Soma das horas negativas (`BH_DESC_DIA`).
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
        
    with st.status("🔄 Executando varredura...", expanded=True) as status:
        status.write("Obtendo funcionários em Atividade Normal...")
        df_funcionarios = fetch_lista_funcionarios_ativos(data_ref)
        
        if df_funcionarios.empty:
            status.update(label="❌ Ninguém encontrado.", state="error")
            st.stop()
            
        total = len(df_funcionarios)
        status.write(f"✅ {total} colaboradores listados.")
        status.write("🚀 Analisando cartões de ponto (25 workers)...")
        
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

    # TRATAMENTO
    df = pd.DataFrame(resultados)
    df['Tempo Atraso'] = df['Atraso_Horas'].apply(decimal_para_hora_str)
    
    # KPIs
    total_funcs = len(df)
    # 100% Apurado = Quem tem ZERO dias não apurados
    total_apurados = len(df[df['Nao_Apurado'] == 0])
    perc_apurado = (total_apurados / total_funcs * 100) if total_funcs > 0 else 0
    
    total_faltas = df['Faltas'].sum()
    total_vazios = df['Pontos_Vazios'].sum()
    
    st.markdown("### 📊 Métricas do Período")
    
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Analisado", total_funcs)
    k2.metric("100% Apurados", f"{total_apurados} ({perc_apurado:.1f}%)", help="Funcionários com zero dias pendentes de apuração.")
    k3.metric("Faltas Totais", int(total_faltas), delta_color="inverse")
    k4.metric("Pontos Vazios", int(total_vazios), help="Dias apurados sem batida e sem falta lançada.", delta_color="off")
    
    st.divider()
    
    # ABAS
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "❌ Faltas", 
        "⚪ Pontos Vazios",
        "🚨 Não Apurados",
        "📉 Ranking Atrasos",
        "📋 Geral"
    ])
    
    with tab1:
        st.subheader("Funcionários com Faltas (Lançadas)")
        df_faltas = df[df['Faltas'] > 0].sort_values(by='Faltas', ascending=False)
        st.dataframe(
            df_faltas[['ID', 'Funcionario', 'Escola', 'Faltas', 'Status']],
            use_container_width=True,
            hide_index=True
        )

    with tab2:
        st.subheader("Pontos Vazios (Sem Batida e Sem Falta)")
        st.info("Estes funcionários têm dias processados ('S') mas sem entrada e sem falta lançada.")
        df_vazios = df[df['Pontos_Vazios'] > 0].sort_values(by='Pontos_Vazios', ascending=False)
        st.dataframe(
            df_vazios[['ID', 'Funcionario', 'Escola', 'Pontos_Vazios', 'Status']],
            use_container_width=True,
            hide_index=True
        )
        
    with tab3:
        st.subheader("Pendências de Apuração")
        df_pend = df[df['Nao_Apurado'] > 0].sort_values(by='Nao_Apurado', ascending=False)
        st.dataframe(
            df_pend[['ID', 'Funcionario', 'Escola', 'Nao_Apurado', 'Total_Dias', 'Status']],
            use_container_width=True,
            hide_index=True,
            column_config={"Nao_Apurado": st.column_config.ProgressColumn("Dias Pendentes", format="%d", min_value=0, max_value=30)}
        )
        
    with tab4:
        st.subheader("Ranking de Atrasos (Horas)")
        df_atrasos = df[df['Atraso_Horas'] > 0].sort_values(by='Atraso_Horas', ascending=False)
        st.dataframe(
            df_atrasos[['ID', 'Funcionario', 'Escola', 'Tempo Atraso', 'Faltas']],
            use_container_width=True,
            hide_index=True
        )

    with tab5:
        st.subheader("Base Completa")
        st.dataframe(df, use_container_width=True, hide_index=True)
        csv = df.to_csv(index=False, sep=';', encoding='utf-8-sig')
        st.download_button("📥 Baixar CSV", csv, "diagnostico_ponto.csv", "text/csv")