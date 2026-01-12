import streamlit as st
import pandas as pd
import requests
import urllib.parse
from datetime import datetime, time, date
from PIL import Image
from sqlalchemy import text
import io

# ==============================================================================
# 1. CONFIGURAÇÃO DA PÁGINA
# ==============================================================================
st.set_page_config(page_title="Monitoramento de Faltas", layout="wide", page_icon="📉")

# ==============================================================================
# 2. SEGURANÇA E ESTADO
# ==============================================================================
if not st.session_state.get("authentication_status"):
    st.warning("🔒 Acesso restrito. Faça login na página inicial.")
    st.stop()

if 'mesa_dados' not in st.session_state:
    st.session_state['mesa_dados'] = None
if 'mesa_data_ref' not in st.session_state:
    st.session_state['mesa_data_ref'] = None

# Recupera Credenciais
try:
    TOKEN_FIXO = st.secrets["api_portal_gestor"]["token_fixo"]
    CD_OPERADOR = st.secrets["api_portal_gestor"].get("cd_operador", "033555692836")
    NR_ORG = st.secrets["api_portal_gestor"].get("nr_org", "3260")
except Exception as e:
    st.error("⚠️ Erro de Configuração: Credenciais da API não encontradas no secrets.toml.")
    st.stop()

# ==============================================================================
# 3. BANCO DE DADOS (CONSULTAS)
# ==============================================================================
@st.cache_data(ttl=600)
def fetch_dados_auxiliares_db():
    try:
        conn = st.connection("postgres", type="sql")
        
        # 1. Relação Escola -> Supervisor
        q_unidades = """
        SELECT u."UnidadeID", s."NomeSupervisor" as "Supervisor", u."NomeUnidade"
        FROM "Unidades" u
        JOIN "Supervisores" s ON u."SupervisorID" = s."SupervisorID"
        """
        df_unidades = conn.query(q_unidades)
        df_unidades['UnidadeID'] = pd.to_numeric(df_unidades['UnidadeID'], errors='coerce').fillna(0).astype(int)
        
        # 2. Relação Supervisor -> Celular
        q_telefones = 'SELECT "NomeSupervisor", "Celular" FROM "Supervisores"'
        df_telefones = conn.query(q_telefones)
        
        map_telefones = dict(zip(
            df_telefones['NomeSupervisor'].str.strip().str.upper(), 
            df_telefones['Celular']
        ))
        
        return df_unidades, map_telefones
    except Exception as e:
        st.error(f"Erro DB: {e}")
        return pd.DataFrame(), {}

def fetch_dados_conae_local(unidade_id):
    """Busca comparativo unitário (usado no detalhe da escola)"""
    try:
        conn = st.connection("postgres", type="sql")
        
        q_resumo = """
        WITH ContagemReal AS (
            SELECT "UnidadeID", "CargoID", COUNT(*) as "QtdReal"
            FROM "Colaboradores"
            WHERE "Ativo" = TRUE
            GROUP BY "UnidadeID", "CargoID"
        )
        SELECT 
            c."NomeCargo" AS "Cargo", 
            q."Quantidade" AS "Edital",
            COALESCE(cr."QtdReal", 0) AS "Real",
            (COALESCE(cr."QtdReal", 0) - q."Quantidade") AS "Saldo"
        FROM "QuadroEdital" q
        JOIN "Unidades" u ON q."UnidadeID" = u."UnidadeID"
        JOIN "Cargos" c ON q."CargoID" = c."CargoID"
        LEFT JOIN ContagemReal cr ON q."UnidadeID" = cr."UnidadeID" AND q."CargoID" = cr."CargoID"
        WHERE q."UnidadeID" = :uid
        ORDER BY c."NomeCargo";
        """
        
        q_pessoas = """
        SELECT c."NomeCargo" as "Cargo", col."Nome" as "Funcionario", col."ColaboradorID" as "ID"
        FROM "Colaboradores" col
        JOIN "Cargos" c ON col."CargoID" = c."CargoID"
        WHERE col."UnidadeID" = :uid AND col."Ativo" = TRUE
        ORDER BY c."NomeCargo", col."Nome"
        """

        df_resumo = conn.query(q_resumo, params={"uid": int(unidade_id)}, ttl=0)
        df_pessoas = conn.query(q_pessoas, params={"uid": int(unidade_id)}, ttl=0)
        
        if not df_pessoas.empty:
            df_pessoas['ID'] = pd.to_numeric(df_pessoas['ID'], errors='coerce').fillna(0).astype(int)

        return df_resumo, df_pessoas
    except Exception as e:
        return pd.DataFrame(), pd.DataFrame()

@st.cache_data(ttl=300)
def fetch_censo_completo_conae():
    """
    Busca TODOS os funcionários ativos de TODAS as escolas para diagnóstico global.
    """
    try:
        conn = st.connection("postgres", type="sql")
        query = """
        SELECT 
            u."NomeUnidade" as "Escola_DB",
            s."NomeSupervisor" as "Supervisor_DB",
            c."NomeCargo" as "Cargo", 
            col."Nome" as "Funcionario", 
            col."ColaboradorID" as "ID",
            col."UnidadeID"
        FROM "Colaboradores" col
        JOIN "Unidades" u ON col."UnidadeID" = u."UnidadeID"
        JOIN "Cargos" c ON col."CargoID" = c."CargoID"
        JOIN "Supervisores" s ON u."SupervisorID" = s."SupervisorID"
        WHERE col."Ativo" = TRUE
        """
        df = conn.query(query, ttl=0)
        df['ID'] = pd.to_numeric(df['ID'], errors='coerce').fillna(0).astype(int)
        df['UnidadeID'] = pd.to_numeric(df['UnidadeID'], errors='coerce').fillna(0).astype(int)
        return df
    except Exception as e:
        st.error(f"Erro ao buscar censo completo: {e}")
        return pd.DataFrame()

# ==============================================================================
# 4. API REQUISITION
# ==============================================================================
def fetch_mesa_operacional(data_selecionada):
    url = "https://portalgestor.teknisa.com/backend/index.php/getMesaOperacoes"
    data_str = data_selecionada.strftime("%d/%m/%Y")
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
                return pd.DataFrame(data["dataset"]["data"])
    except Exception as e:
        st.error(f"Erro API: {e}")
    return pd.DataFrame()

# ==============================================================================
# 5. PROCESSAMENTO E LÓGICA
# ==============================================================================
def processar_dados_unificados(df_api, df_unidades, map_telefones, data_analise):
    if df_api.empty: return df_api

    if 'NMSITUFUNCH' in df_api.columns:
        df_api = df_api[df_api['NMSITUFUNCH'] == 'Atividade Normal'].copy()
    
    if df_api.empty: return df_api

    # Ajuste IDs e Tipos
    df_api['UnidadeID'] = pd.to_numeric(df_api['NRESTRUTGEREN'], errors='coerce').fillna(0).astype(int)
    
    # Merge com Unidades
    df_merged = pd.merge(df_api, df_unidades, on="UnidadeID", how="left")
    
    # Fallback de nome de escola se a API não trouxe ou para garantir o nome interno
    if 'NomeUnidade' in df_merged.columns:
        df_merged['Escola_Interna'] = df_merged['NomeUnidade']
    
    df_merged['Supervisor'] = df_merged['Supervisor'].fillna("Não Identificado")
    df_merged['Supervisor_Key'] = df_merged['Supervisor'].str.strip().str.upper()
    df_merged['Celular'] = df_merged['Supervisor_Key'].map(map_telefones)

    df_merged = df_merged.rename(columns={
        'NMESTRUTGEREN': 'Escola_API', 
        'NMVINCULOM': 'Funcionario',
        'NRVINCULOM': 'ID', 
        'NMOCUPACAOH': 'Cargo',
        'horas_trabalhadas': 'Batidas',
        'horas_escala': 'Escala',
        'OBSERVACAO': 'Obs'
    })

    df_merged['ID'] = pd.to_numeric(df_merged['ID'], errors='coerce').fillna(0).astype(int)
    df_merged['Escola'] = df_merged['Escola_API'] # Usa o nome da API por padrão na visualização

    # Horários e Status
    hoje = date.today()
    agora = datetime.now().time()
    eh_hoje = (data_analise == hoje)
    eh_passado = (data_analise < hoje)
    
    def extrair_hora_inicio(lista_escala):
        if not isinstance(lista_escala, list) or not lista_escala: return None
        try:
            str_hora = lista_escala[0][0] 
            h, m = map(int, str_hora.split(':'))
            return time(h, m)
        except: return None

    def get_status(row):
        batidas = row.get('Batidas')
        escala = row.get('Escala')
        tem_batida = isinstance(batidas, list) and len(batidas) > 0
        if tem_batida: return '🟢 Presente'
        tem_escala = isinstance(escala, list) and len(escala) > 0
        if tem_escala:
            if eh_passado: return '🔴 Falta'
            if eh_hoje:
                hora_inicio = extrair_hora_inicio(escala)
                if hora_inicio:
                    if agora >= hora_inicio: return '🔴 Falta'
                    else: return '⏳ A Iniciar'
                else: return '🔴 Falta'
            return '⏳ A Iniciar'
        return '🟡 S/ Escala'

    df_merged['Status_Individual'] = df_merged.apply(get_status, axis=1)

    def format_hora(lista):
        if not isinstance(lista, list) or not lista: return "-"
        try: return " | ".join([f"{x[0]}-{x[1]}" for x in lista if len(x) == 2])
        except: return "-"

    df_merged['Escala_Formatada'] = df_merged['Escala'].apply(format_hora)
    df_merged['Ponto_Real'] = df_merged['Batidas'].apply(format_hora)
    
    return df_merged

# ==============================================================================
# 6. DIAGNÓSTICO GLOBAL
# ==============================================================================
@st.dialog("📊 Diagnóstico Global de Divergências", width="large")
def modal_diagnostico_global(df_mesa):
    st.caption("Comparação completa entre Funcionários na API (Mesa) e Funcionários Ativos no Banco de Dados.")
    
    with st.spinner("Baixando censo completo do banco..."):
        df_banco = fetch_censo_completo_conae()
    
    if df_banco.empty:
        st.error("Não foi possível carregar os dados do banco.")
        return
    
    if df_mesa is None or df_mesa.empty:
        st.error("Não há dados da Mesa Operacional carregados. Aguarde o processamento da tela principal.")
        return

    # --- PROCESSAMENTO DAS DIVERGÊNCIAS ---
    divergencias = []

    # 1. Agrupar Mesa por Escola (ID) para comparação eficiente
    # Criamos um set de IDs presentes na mesa
    ids_mesa_ativos = set(df_mesa[df_mesa['ID'] > 0]['ID'].unique())
    
    # 2. Agrupar Banco
    ids_banco_ativos = set(df_banco[df_banco['ID'] > 0]['ID'].unique())

    # --- CASO A: NO BANCO MAS NÃO NA MESA ---
    # Colaboradores ativos no DB que não apareceram na lista da API hoje
    diff_banco_mesa = list(ids_banco_ativos - ids_mesa_ativos)
    
    if diff_banco_mesa:
        # Filtra os detalhes desses IDs no dataframe do banco
        df_missing_mesa = df_banco[df_banco['ID'].isin(diff_banco_mesa)].copy()
        df_missing_mesa['Tipo_Divergencia'] = "⚠️ No Banco, Fora da Mesa"
        df_missing_mesa = df_missing_mesa[['Escola_DB', 'Supervisor_DB', 'Tipo_Divergencia', 'ID', 'Funcionario', 'Cargo']]
        # Renomear para padronizar
        df_missing_mesa.columns = ['Escola', 'Supervisor', 'Divergencia', 'Matricula', 'Funcionario', 'Cargo']
        divergencias.append(df_missing_mesa)

    # --- CASO B: NA MESA MAS NÃO NO BANCO ---
    # Colaboradores que estão na escala da API mas não constam como ativos no DB
    diff_mesa_banco = list(ids_mesa_ativos - ids_banco_ativos)
    
    if diff_mesa_banco:
        df_missing_banco = df_mesa[df_mesa['ID'].isin(diff_mesa_banco)].copy()
        df_missing_banco['Tipo_Divergencia'] = "🚫 Na Mesa, Sem Cadastro Ativo"
        # Tenta pegar nome da escola, priorizando o da API
        df_missing_banco = df_missing_banco[['Escola', 'Supervisor', 'Tipo_Divergencia', 'ID', 'Funcionario', 'Cargo']]
        df_missing_banco.columns = ['Escola', 'Supervisor', 'Divergencia', 'Matricula', 'Funcionario', 'Cargo']
        divergencias.append(df_missing_banco)

    # --- CONSOLIDAÇÃO ---
    if divergencias:
        df_final = pd.concat(divergencias, ignore_index=True)
        # Ordenar
        df_final = df_final.sort_values(by=['Divergencia', 'Escola', 'Funcionario'])
        
        # Métricas
        qtd_banco_fora = len(df_final[df_final['Divergencia'].str.contains("No Banco")])
        qtd_mesa_fora = len(df_final[df_final['Divergencia'].str.contains("Na Mesa")])
        
        c1, c2 = st.columns(2)
        c1.metric("Faltando na Mesa (Erro Integração?)", qtd_banco_fora, delta_color="inverse")
        c2.metric("Sobrando na Mesa (Inativo/Sem Cadastro?)", qtd_mesa_fora, delta_color="inverse")
        
        st.markdown("---")
        
        # Filtros no Modal
        f_sup = st.selectbox("Filtrar Supervisor (Relatório):", ["Todos"] + sorted(df_final['Supervisor'].unique()))
        if f_sup != "Todos":
            df_final = df_final[df_final['Supervisor'] == f_sup]

        st.dataframe(
            df_final,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Matricula": st.column_config.NumberColumn("Matrícula", format="%d")
            }
        )
        
        # Botão Exportar
        csv = df_final.to_csv(index=False, sep=';', encoding='utf-8-sig')
        st.download_button(
            label="📥 Baixar Relatório Completo (CSV)",
            data=csv,
            file_name=f"diagnostico_divergencias_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
            use_container_width=True
        )
        
    else:
        st.success("🎉 Incrível! Nenhuma divergência encontrada entre Mesa e Banco de Dados.")


# ==============================================================================
# 7. UI - SIDEBAR
# ==============================================================================
def carregar_logo():
    try: return Image.open("logo.png")
    except: return None

if logo := carregar_logo(): 
    st.sidebar.image(logo, use_container_width=True)
st.sidebar.divider()

if "name" in st.session_state: 
    st.sidebar.write(f"👤 **{st.session_state['name']}**")
    st.sidebar.divider()

st.sidebar.markdown("### 📅 Configuração")
data_selecionada = st.sidebar.date_input("Data de Análise", datetime.now())

if st.session_state['mesa_data_ref'] != data_selecionada:
    st.session_state['mesa_dados'] = None 

if st.sidebar.button("🔄 Atualizar Dados", use_container_width=True):
    st.session_state['mesa_dados'] = None
    st.cache_data.clear()
    st.rerun()

st.sidebar.divider()

# VARIÁVEL DE CONTROLE DE DIALOG
abriu_modal_diagnostico = False

# --- NOVO BOTÃO DE DIAGNÓSTICO ---
if st.sidebar.button("🏥 Diagnóstico Geral", use_container_width=True):
    dados = st.session_state.get('mesa_dados')
    if dados is not None and not dados.empty:
        abriu_modal_diagnostico = True
        modal_diagnostico_global(dados)
    else:
        st.sidebar.warning("⚠️ Carregue os dados primeiro (Aguarde o processamento da tela principal).")

# ==============================================================================
# 8. CARREGAMENTO DOS DADOS
# ==============================================================================
if st.session_state['mesa_dados'] is None:
    with st.spinner(f"Buscando dados de {data_selecionada.strftime('%d/%m/%Y')}..."):
        df_unidades, map_telefones = fetch_dados_auxiliares_db()
        raw_api = fetch_mesa_operacional(data_selecionada)
        df_proc = processar_dados_unificados(raw_api, df_unidades, map_telefones, data_selecionada)
        
        st.session_state['mesa_dados'] = df_proc
        st.session_state['mesa_data_ref'] = data_selecionada

df = st.session_state['mesa_dados']
data_exibicao = st.session_state['mesa_data_ref'].strftime("%d/%m/%Y")

# ==============================================================================
# 9. DASHBOARD PRINCIPAL
# ==============================================================================
st.title("📉 Monitoramento de Faltas")
st.caption(f"Dados referentes a: **{data_exibicao}**")

# FUNCIONALIDADE WHATSAPP (HELPER)
def gerar_link_whatsapp(telefone, mensagem):
    texto_encoded = urllib.parse.quote_plus(mensagem)
    fone_limpo = "".join(filter(str.isdigit, str(telefone))) if telefone else ""
    return f"https://api.whatsapp.com/send?phone=55{fone_limpo}&text={texto_encoded}"

# --- FUNÇÃO DO POPUP DE ALERTA ---
@st.dialog("📢 Central de Alertas", width="large")
def dialog_disparar_alertas(df_completo):
    st.caption("Envie mensagens para os supervisores. Prioriza escolas com problema de registro.")
    
    # 1. Filtra apenas as linhas com FALTA
    df_faltas_bruto = df_completo[df_completo['Status_Individual'] == '🔴 Falta']
    
    if df_faltas_bruto.empty:
        st.success("🎉 Nenhuma falta registrada para alerta no momento!")
        return

    supervisores_com_falta = sorted(df_faltas_bruto['Supervisor'].unique())
    
    for supervisor in supervisores_com_falta:
        with st.container(border=True):
            c1, c2 = st.columns([3, 1])
            
            # Dados deste supervisor
            df_sup_faltas = df_faltas_bruto[df_faltas_bruto['Supervisor'] == supervisor]
            df_sup_total = df_completo[df_completo['Supervisor'] == supervisor]
            
            # --- PREPARAÇÃO DOS DADOS (PARA ORDENAÇÃO) ---
            escolas_list = []
            
            # Itera sobre cada escola que tem falta para classificar
            for escola, dados_falta in df_sup_faltas.groupby('Escola'):
                # Verifica se TEM ALGUMA PRESENÇA na escola (no dataframe total)
                tem_presenca = not df_sup_total[
                    (df_sup_total['Escola'] == escola) & 
                    (df_sup_total['Status_Individual'] == '🟢 Presente')
                ].empty
                
                eh_problema_app = not tem_presenca
                
                # Lista de nomes faltantes
                lista_nomes = dados_falta['Funcionario'].tolist()
                
                escolas_list.append({
                    'nome': escola,
                    'funcionarios': lista_nomes,
                    'problema_app': eh_problema_app,
                    'qtd': len(lista_nomes)
                })
            
            # --- ORDENAÇÃO ---
            escolas_list.sort(key=lambda x: x['problema_app'], reverse=True)
            
            # --- CÁLCULO DOS TOTALIZADORES ---
            total_faltas = sum(e['qtd'] for e in escolas_list)
            total_escolas_problema = sum(1 for e in escolas_list if e['problema_app'])
            
            # --- MONTAGEM DA MENSAGEM ---
            msg_lines = [f"Ola *{supervisor}*, resumo de ausencias ({datetime.now().strftime('%H:%M')}):"]
            msg_lines.append("")
            msg_lines.append(f"\U0001F4CA *Total Faltas:* {total_faltas}")
            if total_escolas_problema > 0:
                msg_lines.append(f"\u26A0\uFE0F *Escolas c/ Problema App:* {total_escolas_problema}")
            msg_lines.append("")
            
            for item in escolas_list:
                nomes_str = ", ".join(item['funcionarios'])
                if item['problema_app']:
                    cabecalho = f"\U0001F6A8 *{item['nome']}* (\u26A0\uFE0F POSSIVEL PROBLEMA SMARTPHONE)"
                else:
                    cabecalho = f"\U0001F3EB *{item['nome']}*"
                msg_lines.append(f"{cabecalho}")
                msg_lines.append(f"\U0001F6AB {nomes_str}")
                msg_lines.append("")
            
            msg_final = "\n".join(msg_lines).strip()
            
            # --- UI: EXIBIÇÃO NO STREAMLIT ---
            telefone_bruto = None
            if 'Celular' in df_sup_faltas.columns:
                val = df_sup_faltas['Celular'].iloc[0]
                if pd.notna(val) and str(val).strip() != "" and str(val).strip().lower() != "none":
                    telefone_bruto = val
            
            with c1:
                st.markdown(f"**👤 {supervisor}**")
                kpi1, kpi2 = st.columns(2)
                kpi1.metric("Faltas", total_faltas)
                kpi2.metric("Escolas Críticas", total_escolas_problema)
                with st.expander("Ver mensagem gerada"):
                    st.text(msg_final)
            
            with c2:
                if telefone_bruto:
                    link = gerar_link_whatsapp(telefone_bruto, msg_final)
                    st.link_button("📲 Enviar WhatsApp", link, use_container_width=True)
                else:
                    st.warning("Sem Celular")
                    st.caption("Cadastre no Banco")

if df is not None and not df.empty:
    st.markdown("---")
    c_btn1, c_btn2 = st.columns([3, 1])
    with c_btn1:
        st.info("💡 Clique ao lado para notificar os supervisores sobre as faltas identificadas.")
    with c_btn2:
        if st.button("📢 Disparar Alertas", use_container_width=True):
            dialog_disparar_alertas(df)
    st.markdown("---")

# === FILTROS NA SIDEBAR ===
filtro_supervisor = "Todos"
filtro_status = "TODAS"

if df is not None and not df.empty:
    opcoes = ["Todos"] + sorted(df['Supervisor'].unique().tolist())
    filtro_supervisor = st.sidebar.selectbox("Filtrar por Supervisor:", opcoes)
    
    st.sidebar.markdown("---")
    opcoes_status = ["TODAS", "🌟 ESCOLA COMPLETA", "⚠️ POSSÍVEL PROBLEMA SMARTPHONE"]
    filtro_status = st.sidebar.selectbox("Filtrar por Situação:", opcoes_status)

if df is not None and not df.empty:
    df_filtrado = df.copy()
    
    if filtro_supervisor != "Todos":
        df_filtrado = df_filtrado[df_filtrado['Supervisor'] == filtro_supervisor]

    if df_filtrado.empty:
        st.warning("Nenhum dado encontrado para o filtro selecionado.")
        st.stop()

    qtd_presente = len(df_filtrado[df_filtrado['Status_Individual'] == '🟢 Presente'])
    qtd_falta = len(df_filtrado[df_filtrado['Status_Individual'] == '🔴 Falta'])
    qtd_a_entrar = len(df_filtrado[df_filtrado['Status_Individual'] == '⏳ A Iniciar'])
    qtd_efetivo = qtd_presente + qtd_falta + qtd_a_entrar

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Efetivo Esperado", qtd_efetivo)
    k2.metric("Presentes", qtd_presente)
    k3.metric("Faltas", qtd_falta, delta_color="inverse", help="Postos descobertos")
    k4.metric("Turnos a Iniciar", qtd_a_entrar, delta_color="normal")
    
    st.divider()

    resumo = df_filtrado.groupby(['Escola', 'Supervisor']).agg(
        Efetivo=('Status_Individual', 'count'), 
        Faltas=('Status_Individual', lambda x: (x == '🔴 Falta').sum()),
        Presentes=('Status_Individual', lambda x: (x == '🟢 Presente').sum()),
        A_Entrar=('Status_Individual', lambda x: (x == '⏳ A Iniciar').sum())
    ).reset_index()

    def definir_diagnostico(row):
        presentes = row['Presentes']
        faltas = row['Faltas']
        a_entrar = row['A_Entrar']
        
        if presentes == 0:
            if faltas > 0: return "⚠️ POSSÍVEL PROBLEMA SMARTPHONE"
            elif a_entrar > 0 and faltas == 0: return "🕒 AGUARDANDO INÍCIO"
            else: return "⚠️ VERIFICAR"
        
        if faltas == 0:
            if a_entrar == 0: return "🌟 ESCOLA COMPLETA"
            else: return "✅ PARCIAL (Aguardando Tarde/Noite)"
        
        base_calc = presentes + faltas
        if base_calc > 0:
            perc = (presentes / base_calc) * 100
            return f"{perc:.0f}% Presentes (Turno Atual)"
        return "-"

    resumo['Diagnostico'] = resumo.apply(definir_diagnostico, axis=1)

    if filtro_status == "🌟 ESCOLA COMPLETA":
        resumo = resumo[resumo['Diagnostico'].str.contains("COMPLETA", na=False)]
    elif filtro_status == "⚠️ POSSÍVEL PROBLEMA SMARTPHONE":
        resumo = resumo[resumo['Diagnostico'].str.contains("PROBLEMA", na=False)]

    def get_sort_key(row):
        d = row['Diagnostico']
        if "PROBLEMA" in d: return 0
        if "COMPLETA" in d: return 3
        if "AGUARDANDO" in d: return 2
        return 1

    if not resumo.empty:
        resumo['sort_group'] = resumo.apply(get_sort_key, axis=1)
        resumo['perc_presenca'] = resumo['Presentes'] / (resumo['Efetivo'].replace(0, 1))
        resumo = resumo.sort_values(by=['sort_group', 'perc_presenca'], ascending=[True, True])

    qtd_problema = len(resumo[resumo['Diagnostico'].str.contains("PROBLEMA", na=False)])
    qtd_completas = len(resumo[resumo['Diagnostico'].str.contains("COMPLETA", na=False)])
    
    c_info1, c_info2 = st.columns(2)
    with c_info1:
        if qtd_problema > 0: st.error(f"🚨 **{qtd_problema}** escolas com possível problema no Smartphone.")
    with c_info2:
        if qtd_completas > 0: st.success(f"🌟 **{qtd_completas}** escolas com efetivo 100% completo.")

    st.markdown(f"### 🏫 Visão por Unidade ({filtro_supervisor})")
    
    if resumo.empty:
        st.info("Nenhuma escola corresponde ao filtro selecionado.")
    else:
        event = st.dataframe(
            resumo[['Escola', 'Supervisor', 'Diagnostico', 'Efetivo', 'Presentes', 'Faltas', 'A_Entrar']],
            use_container_width=True,
            hide_index=True,
            selection_mode="single-row",
            on_select="rerun",
            column_config={
                "Escola": st.column_config.TextColumn("Escola", width="large"),
                "Diagnostico": st.column_config.TextColumn("Status", width="medium"),
                "Efetivo": st.column_config.NumberColumn("Total", format="%d 👤"),
                "Presentes": st.column_config.NumberColumn("Ok", format="%d 🟢"),
                "Faltas": st.column_config.NumberColumn("Faltas", format="%d 🔴"),
                "A_Entrar": st.column_config.NumberColumn("A Iniciar", format="%d ⏳"),
            }
        )

        @st.dialog("Detalhe da Escola", width="large")
        def mostrar_detalhe(escola, supervisor, df_local, diag):
            st.subheader(f"🏫 {escola}")
            st.caption(f"Supervisor: {supervisor} | Status: {diag}")
            
            st.markdown("##### 📉 Mesa Operacional (Hoje)")
            mapa_ordem = {'🔴 Falta': 0, '🟢 Presente': 1, '⏳ A Iniciar': 2, '🟡 S/ Escala': 3}
            df_show = df_local.copy()
            df_show['ordem'] = df_show['Status_Individual'].map(mapa_ordem)
            df_show = df_show.sort_values('ordem')

            st.dataframe(
                df_show[['Status_Individual', 'Funcionario', 'Cargo', 'ID', 'Escala_Formatada', 'Ponto_Real']],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Status_Individual": st.column_config.TextColumn("Situação", width="small"),
                    "ID": st.column_config.NumberColumn("Matrícula", format="%d"),
                    "Escala_Formatada": st.column_config.TextColumn("Escala Prevista", width="medium"),
                    "Ponto_Real": st.column_config.TextColumn("Batidas", width="medium"),
                }
            )

            st.divider()

            with st.expander("📊 Ver Quadro Comparativo (CONAE)", expanded=False):
                with st.spinner("Buscando dados do quadro..."):
                    df_conae = pd.DataFrame()
                    df_pessoas_conae = pd.DataFrame()
                    try:
                        if not df_local.empty:
                            uid_target = int(df_local['UnidadeID'].iloc[0])
                            df_conae, df_pessoas_conae = fetch_dados_conae_local(uid_target)
                    except: pass
                
                if not df_conae.empty:
                    total_edital = df_conae['Edital'].sum()
                    total_real = df_conae['Real'].sum()
                    saldo_geral = total_real - total_edital
                    
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Total Edital", total_edital)
                    c2.metric("Total Real", total_real)
                    c3.metric("Saldo", saldo_geral, delta_color="normal")
                    
                    def style_saldo(val):
                        if val < 0: return 'color: #e74c3c; font-weight: bold;'
                        if val > 0: return 'color: #3498db; font-weight: bold;'
                        return 'color: #27ae60; font-weight: bold;'

                    st.dataframe(
                        df_conae.style.map(style_saldo, subset=['Saldo']),
                        use_container_width=True,
                        hide_index=True,
                        column_config={"Saldo": st.column_config.NumberColumn("Saldo", format="%+d")}
                    )

                    if not df_pessoas_conae.empty:
                        st.markdown("---")
                        st.markdown("###### 🔍 Divergências (Cruzamento por Matrícula/ID)")
                        
                        set_mesa = set(df_local['ID'].unique())
                        set_mesa.discard(0) 
                        set_banco = set(df_pessoas_conae['ID'].unique())
                        set_banco.discard(0)

                        ids_fora_mesa = sorted(list(set_banco - set_mesa))
                        ids_sem_cadastro = sorted(list(set_mesa - set_banco))

                        c_div1, c_div2 = st.columns(2)
                        
                        with c_div1:
                            if ids_fora_mesa:
                                st.warning(f"⚠️ {len(ids_fora_mesa)} No Banco, mas fora da Mesa")
                                df_miss = df_pessoas_conae[df_pessoas_conae['ID'].isin(ids_fora_mesa)]
                                st.dataframe(df_miss, hide_index=True, use_container_width=True,
                                    column_config={"ID": st.column_config.NumberColumn("Matrícula", format="%d")})
                            else:
                                st.success("✅ Todos do Banco estão na Mesa")

                        with c_div2:
                            if ids_sem_cadastro:
                                st.error(f"🚫 {len(ids_sem_cadastro)} Na Mesa, mas Inativos/Sem Cadastro")
                                df_extra = df_local[df_local['ID'].isin(ids_sem_cadastro)]
                                st.dataframe(df_extra[['ID', 'Funcionario', 'Cargo']], hide_index=True, use_container_width=True,
                                    column_config={"ID": st.column_config.NumberColumn("Matrícula", format="%d")})
                            else:
                                st.success("✅ Ninguém sobrando na Mesa")
                        
                        st.markdown("---")
                        st.markdown("###### 📋 Lista Nominal Completa (Banco de Dados)")
                        st.dataframe(
                            df_pessoas_conae,
                            use_container_width=True,
                            hide_index=True,
                            column_config={"ID": st.column_config.NumberColumn("Matrícula", format="%d")}
                        )
                else:
                    st.warning("Dados de quadro não encontrados para esta unidade.")

        if len(event.selection.rows) > 0 and not abriu_modal_diagnostico:
            idx = event.selection.rows[0]
            row = resumo.iloc[idx]
            df_detalhe = df_filtrado[df_filtrado['Escola'] == row['Escola']]
            mostrar_detalhe(row['Escola'], row['Supervisor'], df_detalhe, row['Diagnostico'])

elif df is not None and df.empty:
    st.info(f"Nenhum dado encontrado para a data {data_exibicao}.")