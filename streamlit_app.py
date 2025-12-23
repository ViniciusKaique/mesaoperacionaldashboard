import streamlit as st 
import streamlit_authenticator as stauth
import pandas as pd
import plotly.express as px
import numpy as np 
from PIL import Image
from sqlalchemy import text

# --- 1. CONFIGURAÇÃO E ESTILO ---
def configurar_pagina():
    st.set_page_config(page_title="Mesa Operacional", layout="wide", page_icon="📊")
    # CSS Reduzido (Removido o excesso, mantido o essencial)
    st.markdown("""
    <style>
        .block-container { padding-top: 1rem; }
        [data-testid="stMetricValue"] { font-size: 32px; font-weight: bold; }
        .stDataFrame { font-size: 14px; }
        div[data-testid="stSpinner"] > div { color: #ff4b4b; }
    </style>
    """, unsafe_allow_html=True)

def carregar_logo():
    try: return Image.open("logo.png")
    except: return None

# --- 2. AUTENTICAÇÃO ---
def realizar_login():
    try:
        auth_secrets = st.secrets["auth"]
        config = {
            'credentials': {'usernames': {auth_secrets["username"]: {'name': auth_secrets["name"], 'password': auth_secrets["password_hash"], 'email': auth_secrets["email"]}}},
            'cookie': {'name': auth_secrets["cookie_name"], 'key': auth_secrets["cookie_key"], 'expiry_days': auth_secrets["cookie_expiry_days"]}
        }
        authenticator = stauth.Authenticate(config['credentials'], config['cookie']['name'], config['cookie']['key'], config['cookie']['expiry_days'])
        
        if not st.session_state.get("authentication_status"):
            st.write(""); st.write(""); st.write(""); st.write(""); st.write("")
            col_esq, col_centro, col_dir = st.columns([3, 2, 3])
            with col_centro:
                try: authenticator.login(location='main')
                except: authenticator.login()
            if st.session_state.get("authentication_status") is False:
                with col_centro: st.error('Usuário ou senha incorretos')
            return None, None
            
        return authenticator, st.session_state.get("name")
    except Exception as e:
        st.error("Erro Crítico de Autenticação."); st.stop()

# --- 3. DADOS ---
@st.cache_data(ttl=600, show_spinner=False)
def buscar_dados_auxiliares(_conn):
    df_unidades = _conn.query('SELECT "UnidadeID", "NomeUnidade" FROM "Unidades" ORDER BY "NomeUnidade"')
    df_cargos = _conn.query('SELECT "CargoID", "NomeCargo" FROM "Cargos" ORDER BY "NomeCargo"')
    return df_unidades, df_cargos

@st.cache_data(ttl=600, show_spinner=False)
def buscar_dados_operacionais(_conn):
    query_resumo = """
    WITH ContagemReal AS (
        SELECT "UnidadeID", "CargoID", COUNT(*) as "QtdReal"
        FROM "Colaboradores" WHERE "Ativo" = TRUE GROUP BY "UnidadeID", "CargoID"
    )
    SELECT 
        u."UnidadeID", u."NomeUnidade" AS "Escola", u."DataConferencia",
        s."NomeSupervisor" AS "Supervisor", c."NomeCargo" AS "Cargo", 
        q."Quantidade" AS "Edital", COALESCE(cr."QtdReal", 0) AS "Real"
    FROM "QuadroEdital" q
    JOIN "Unidades" u ON q."UnidadeID" = u."UnidadeID"
    JOIN "Cargos" c ON q."CargoID" = c."CargoID"
    JOIN "Supervisores" s ON u."SupervisorID" = s."SupervisorID"
    LEFT JOIN ContagemReal cr ON q."UnidadeID" = cr."UnidadeID" AND q."CargoID" = cr."CargoID"
    ORDER BY u."NomeUnidade", c."NomeCargo";
    """
    df_resumo = _conn.query(query_resumo)
    
    # Query de Funcionários otimizada (buscando apenas o necessário)
    query_funcionarios = """
    SELECT u."NomeUnidade" AS "Escola", c."NomeCargo" AS "Cargo", col."Nome" AS "Funcionario", col."ColaboradorID" AS "ID"
    FROM "Colaboradores" col
    JOIN "Unidades" u ON col."UnidadeID" = u."UnidadeID"
    JOIN "Cargos" c ON col."CargoID" = c."CargoID"
    WHERE col."Ativo" = TRUE
    ORDER BY u."NomeUnidade", col."Nome";
    """
    df_pessoas = _conn.query(query_funcionarios)

    # Processamento Vetorizado
    df_resumo['Diferenca_num'] = df_resumo['Real'] - df_resumo['Edital']
    condicoes = [df_resumo['Diferenca_num'] < 0, df_resumo['Diferenca_num'] > 0]
    
    df_resumo['Status_Display'] = np.select(condicoes, ['🔴 FALTA', '🔵 EXCEDENTE'], default='🟢 OK')
    df_resumo['Status_Codigo'] = np.select(condicoes, ['FALTA', 'EXCEDENTE'], default='OK')
    df_resumo['Diferenca_Display'] = df_resumo['Diferenca_num'].apply(lambda x: f"+{x}" if x > 0 else str(int(x)))
    df_resumo['DataConferencia'] = pd.to_datetime(df_resumo['DataConferencia'])
    
    return df_resumo, df_pessoas

# --- 4. AÇÕES ---
@st.dialog("✏️ Editar")
def dialog_editar_colaborador(dados_colab, df_unidades, df_cargos, conn):
    st.write(f"Func: **{dados_colab['Funcionario']}**")
    with st.form("form_edicao"):
        l_esc = df_unidades['NomeUnidade'].tolist()
        l_car = df_cargos['NomeCargo'].tolist()
        
        # Índices seguros
        idx_e = l_esc.index(dados_colab['Escola']) if dados_colab['Escola'] in l_esc else 0
        idx_c = l_car.index(dados_colab['Cargo']) if dados_colab['Cargo'] in l_car else 0
        
        nova_escola = st.selectbox("Escola", l_esc, index=idx_e)
        novo_cargo = st.selectbox("Cargo", l_car, index=idx_c)
        novo_status = st.checkbox("Ativo", value=True)
        
        if st.form_submit_button("Salvar"):
            uid = int(df_unidades[df_unidades['NomeUnidade'] == nova_escola]['UnidadeID'].iloc[0])
            cid = int(df_cargos[df_cargos['NomeCargo'] == novo_cargo]['CargoID'].iloc[0])
            try:
                with conn.session as session:
                    session.execute(text("UPDATE \"Colaboradores\" SET \"UnidadeID\" = :uid, \"CargoID\" = :cid, \"Ativo\" = :ativo WHERE \"ColaboradorID\" = :id"), 
                                    {"uid": uid, "cid": cid, "ativo": novo_status, "id": int(dados_colab['ID'])})
                    session.commit()
                st.cache_data.clear() 
                st.rerun()
            except Exception as e: st.error(f"Erro: {e}")

def acao_atualizar_data(unidade_id, nova_data, conn):
    with conn.session as session:
        session.execute(text(f"UPDATE \"Unidades\" SET \"DataConferencia\" = '{nova_data}' WHERE \"UnidadeID\" = {unidade_id}"))
        session.commit()
    st.cache_data.clear()
    # Não precisa de rerun se usar fragmento, mas mantemos por segurança
    st.rerun() 

# --- 5. UI COMPONENTS ---
def exibir_kpis(df):
    c1, c2, c3 = st.columns(3)
    c1.metric("📋 Total Edital", int(df['Edital'].sum()))
    c2.metric("👥 Efetivo Atual", int(df['Real'].sum()))
    c3.metric("⚖️ Saldo Geral", int(df['Real'].sum() - df['Edital'].sum()))

# --- OTIMIZAÇÃO: Função de Estilo fora do loop (Global) ---
def estilo_tabela_global(row):
    # Lógica simplificada para ser mais rápida
    val = row['Diferenca'] # Já vem como string do pré-processamento
    color = '#00c853' # Green default
    weight = 'bold'
    
    if '-' in val: color = '#ff4b4b'
    elif '+' in val: color = '#29b6f6'
    
    # Retorna array de estilos (Otimizado: cria lista uma vez e só muda as cores necessárias)
    base = ['text-align: center'] * 5
    base[3] = f'text-align: center; color: {color}; font-weight: {weight}'
    
    stt = row['Status']
    color_st = '#00c853'
    if '🔴' in stt: color_st = '#ff4b4b'
    elif '🔵' in stt: color_st = '#29b6f6'
    base[4] = f'text-align: center; color: {color_st}; font-weight: {weight}'
    
    return base

# --- OTIMIZAÇÃO: Fragmento para isolar a renderização da escola ---
# Se o Streamlit for antigo (<1.37), remova o @st.fragment
@st.fragment
def renderizar_cartao_escola(nome_escola, df_escola, df_pessoas_escola, conn, df_unidades, df_cargos):
    # Extração de dados (Head)
    primeira_linha = df_escola.iloc[0]
    unidade_id = int(primeira_linha['UnidadeID'])
    data_atual = primeira_linha['DataConferencia']
    
    # Cálculos Rápidos
    t_edital = int(df_escola['Edital'].sum())
    t_real = int(df_escola['Real'].sum())
    saldo = t_real - t_edital
    
    # Visual
    cor = "red" if saldo < 0 else "blue" if saldo > 0 else "green"
    sinal = "+" if saldo > 0 else ""
    icone = "✅"
    if saldo > 0: icone = "🔵"
    elif saldo < 0: icone = "🔴"
    elif saldo == 0 and any(s != 'OK' for s in df_escola['Status_Codigo']): icone = "🟡"

    with st.expander(f"{icone} {nome_escola}", expanded=False):
        c1, c2 = st.columns([3, 1.5])
        c1.markdown(f"**Supervisor:** {primeira_linha['Supervisor']}")
        
        # Botão de Data
        lbl = "⚠️ Pendente" if pd.isnull(data_atual) else f"📅 {data_atual.strftime('%d/%m')}"
        with c2.popover(lbl, use_container_width=True):
            nova_dt = st.date_input("Data", value=pd.Timestamp.today() if pd.isnull(data_atual) else data_atual, key=f"d_{unidade_id}")
            if st.button("Salvar", key=f"s_{unidade_id}"):
                acao_atualizar_data(unidade_id, nova_dt, conn)

        # KPI Interno (HTML Puro é mais leve que st.metric repetido)
        st.markdown(f"""
        <div style='display:flex; justify-content:space-around; background:#262730; padding:5px; border-radius:5px; margin-bottom:10px;'>
            <span>📋: <b>{t_edital}</b></span><span>👥: <b>{t_real}</b></span><span>⚖️: <b style='color:{cor}'>{sinal}{saldo}</b></span>
        </div>""", unsafe_allow_html=True)

        # Tabela Vagas (Usando dados pré-processados)
        # OTIMIZAÇÃO: Renomear colunas aqui é rápido pois o df é pequeno
        df_show = df_escola[['Cargo','Edital','Real','Diferenca_Display','Status_Display']].rename(
            columns={'Diferenca_Display':'Diferenca','Status_Display':'Status'}
        )
        st.dataframe(df_show.style.apply(estilo_tabela_global, axis=1), use_container_width=True, hide_index=True)

        # Tabela Pessoas
        st.markdown("#### 📋 Colaboradores")
        if not df_pessoas_escola.empty:
            evt = st.dataframe(df_pessoas_escola[['ID','Funcionario','Cargo']], 
                               use_container_width=True, hide_index=True, 
                               selection_mode="single-row", on_select="rerun", key=f"p_{unidade_id}")
            
            if evt.selection.rows:
                dialog_editar_colaborador(df_pessoas_escola.iloc[evt.selection.rows[0]], df_unidades, df_cargos, conn)
        else:
            st.caption("Nenhum colaborador.")

# --- MAIN ---
def main():
    configurar_pagina()
    authenticator, user = realizar_login()
    
    if authenticator:
        with st.sidebar:
            if l := carregar_logo(): st.image(l, use_container_width=True)
            st.write(f"👤 **{user}**"); authenticator.logout(location='sidebar')
        
        try:
            conn = st.connection("postgres", type="sql")
            df_unidades, df_cargos = buscar_dados_auxiliares(conn)
            df_resumo, df_pessoas = buscar_dados_operacionais(conn)
            
            st.title("📊 Mesa Operacional")
            exibir_kpis(df_resumo)
            
            # --- OTIMIZAÇÃO: PRÉ-PROCESSAMENTO GLOBAL ---
            # Convertemos tudo para string AQUI, UMA VEZ SÓ, fora do loop
            # Isso evita chamar .astype(str) 100 vezes dentro do loop
            df_resumo_view = df_resumo.copy()
            df_resumo_view[['Edital', 'Real']] = df_resumo_view[['Edital', 'Real']].astype(str)
            
            st.markdown("---")
            
            # Filtros
            c1, c2, c3, c4 = st.columns([1,1,1,1])
            f_esc = c1.selectbox("Escola", ["Todas"] + sorted(list(df_resumo['Escola'].unique())))
            f_sup = c2.selectbox("Supervisor", ["Todos"] + sorted(list(df_resumo['Supervisor'].unique())))
            f_sit = c3.selectbox("Situação", ["Todas", "🔴 FALTA", "🔵 EXCEDENTE", "🟡 AJUSTE", "🟢 OK"])
            f_bus = c4.text_input("Buscar Pessoa")

            # Aplicação dos Filtros
            mask = pd.Series([True]*len(df_resumo))
            if f_esc != "Todas": mask &= (df_resumo['Escola'] == f_esc)
            if f_sup != "Todos": mask &= (df_resumo['Supervisor'] == f_sup)
            
            if f_sit != "Todas":
                agg = df_resumo.groupby('Escola').agg({'Edital':'sum', 'Real':'sum', 'Status_Codigo':list}).reset_index()
                agg['S'] = agg['Real'] - agg['Edital']
                conds = [agg['S']>0, agg['S']<0, (agg['S']==0) & (agg['Status_Codigo'].apply(lambda x: any(s!='OK' for s in x)))]
                agg['Final'] = np.select(conds, ["🔵 EXCEDENTE", "🔴 FALTA", "🟡 AJUSTE"], default="🟢 OK")
                mask &= df_resumo['Escola'].isin(agg[agg['Final'] == f_sit]['Escola'])

            if f_bus:
                match = df_pessoas[df_pessoas['Funcionario'].str.contains(f_bus, case=False, na=False)]['Escola'].unique()
                mask &= df_resumo['Escola'].isin(match)

            df_final = df_resumo_view[mask].sort_values('Escola') # Usamos o view (já formatado)
            
            # Loop Otimizado com Fragmentos
            if not df_final.empty:
                st.info(f"Escolas: {df_final['Escola'].nunique()}")
                for nome, df_e in df_final.groupby('Escola'):
                    df_p = df_pessoas[df_pessoas['Escola'] == nome]
                    if f_bus: df_p = df_p[df_p['Funcionario'].str.contains(f_bus, case=False, na=False)]
                    
                    # Chama o fragmento (isolado)
                    renderizar_cartao_escola(nome, df_e, df_p, conn, df_unidades, df_cargos)
            else:
                st.warning("Sem resultados.")

        except Exception as e:
            st.error(f"Erro: {e}")

if __name__ == "__main__":
    main()