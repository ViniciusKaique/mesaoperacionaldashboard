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
    st.markdown("""
    <style>
        .block-container { padding-top: 1rem; }
        .stButton button { background-color: #ff4b4b; color: white; border-radius: 8px; }
        [data-testid="stMetricValue"] { font-size: 32px; font-weight: bold; }
        .dataframe { font-size: 14px !important; }
        th, td { text-align: center !important; }
        div[data-testid="stSpinner"] > div { color: #ff4b4b !important; }
        div.stButton > button { width: 100%; display: block; margin: 0 auto; }
    </style>
    """, unsafe_allow_html=True)

def carregar_logo():
    try: return Image.open("logo.png")
    except: return None

# --- OTIMIZAÇÃO: FUNÇÃO DE ESTILO GLOBAL (Tirada de dentro do loop) ---
def estilo_linha_escola(row):
    styles = ['text-align: center;'] * 5
    val = str(row['Diferenca'])
    
    # Lógica de cor condicional
    if '-' in val: styles[3] += 'color: #ff4b4b; font-weight: bold;'
    elif '+' in val: styles[3] += 'color: #29b6f6; font-weight: bold;'
    else: styles[3] += 'color: #00c853; font-weight: bold;'
    
    stt = str(row['Status'])
    if '🔴' in stt: styles[4] += 'color: #ff4b4b; font-weight: bold;'
    elif '🔵' in stt: styles[4] += 'color: #29b6f6; font-weight: bold;'
    else: styles[4] += 'color: #00c853; font-weight: bold;'
    
    return styles

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
            _, col_centro, _ = st.columns([3, 2, 3])
            with col_centro:
                try: authenticator.login(location='main')
                except: authenticator.login()
            if st.session_state.get("authentication_status") is False:
                with col_centro: st.error('Usuário ou senha incorretos')
            return None, None
            
        return authenticator, st.session_state.get("name")
    except Exception as e:
        st.error(f"Erro Auth: {e}"); st.stop()

# --- 3. DADOS ---
@st.cache_data(ttl=600, show_spinner=False)
def buscar_dados_auxiliares(_conn):
    df_u = _conn.query('SELECT "UnidadeID", "NomeUnidade" FROM "Unidades" ORDER BY "NomeUnidade"')
    df_c = _conn.query('SELECT "CargoID", "NomeCargo" FROM "Cargos" ORDER BY "NomeCargo"')
    return df_u, df_c

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
    query_func = """
    SELECT u."NomeUnidade" AS "Escola", c."NomeCargo" AS "Cargo", col."Nome" AS "Funcionario", col."ColaboradorID" AS "ID"
    FROM "Colaboradores" col
    JOIN "Unidades" u ON col."UnidadeID" = u."UnidadeID"
    JOIN "Cargos" c ON col."CargoID" = c."CargoID"
    WHERE col."Ativo" = TRUE ORDER BY u."NomeUnidade", col."Nome";
    """
    df_resumo = _conn.query(query_resumo)
    df_pessoas = _conn.query(query_func)

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
def dialog_editar(dados, df_u, df_c, conn):
    st.write(f"Func: **{dados['Funcionario']}**")
    with st.form("edit"):
        l_u = df_u['NomeUnidade'].tolist()
        l_c = df_c['NomeCargo'].tolist()
        
        idx_u = l_u.index(dados['Escola']) if dados['Escola'] in l_u else 0
        idx_c = l_c.index(dados['Cargo']) if dados['Cargo'] in l_c else 0
        
        n_esc = st.selectbox("Escola", l_u, index=idx_u)
        n_car = st.selectbox("Cargo", l_c, index=idx_c)
        n_atv = st.checkbox("Ativo", value=True)
        
        if st.form_submit_button("Salvar"):
            uid = int(df_u[df_u['NomeUnidade'] == n_esc]['UnidadeID'].iloc[0])
            cid = int(df_c[df_c['NomeCargo'] == n_car]['CargoID'].iloc[0])
            with conn.session as session:
                session.execute(text("UPDATE \"Colaboradores\" SET \"UnidadeID\"=:u, \"CargoID\"=:c, \"Ativo\"=:a WHERE \"ColaboradorID\"=:id"), 
                                {"u":uid, "c":cid, "a":n_atv, "id":int(dados['ID'])})
                session.commit()
            st.cache_data.clear(); st.rerun()

def atualizar_data(uid, data, conn):
    with conn.session as session:
        session.execute(text(f"UPDATE \"Unidades\" SET \"DataConferencia\"='{data}' WHERE \"UnidadeID\"={uid}"))
        session.commit()
    st.cache_data.clear(); st.rerun()

# --- 5. UI ---
def exibir_kpis(df):
    c1, c2, c3 = st.columns(3)
    c1.metric("📋 Total Edital", int(df['Edital'].sum()))
    c2.metric("👥 Efetivo Atual", int(df['Real'].sum()))
    c3.metric("⚖️ Saldo Geral", int(df['Real'].sum() - df['Edital'].sum()))

def exibir_graficos(df):
    with st.expander("📈 Ver Gráficos", expanded=True):
        df_g = df.groupby('Cargo')[['Edital','Real']].sum().reset_index()
        df_g['Dif'] = (df_g['Real'] - df_g['Edital']).apply(lambda x: f"+{x}" if x > 0 else str(x))
        
        c1, c2 = st.columns([2,1])
        c1.plotly_chart(px.bar(df_g.melt(id_vars=['Cargo'], value_vars=['Edital','Real']), x='Cargo', y='value', color='variable', barmode='group', template="seaborn"), use_container_width=True)
        
        def style_g(row):
            s = ['text-align: center'] * 2
            v = str(row['Dif'])
            c = '#ff4b4b' if '-' in v else '#29b6f6' if '+' in v else '#00c853'
            s.append(f'text-align: center; color: {c}; font-weight: bold')
            return s
            
        c2.dataframe(df_g[['Cargo','Edital','Real','Dif']].style.apply(style_g, axis=1), use_container_width=True, hide_index=True)

# --- MAIN ---
def main():
    configurar_pagina()
    auth, user = realizar_login()
    
    if auth:
        with st.sidebar:
            if l := carregar_logo(): st.image(l, use_container_width=True)
            st.write(f"👤 **{user}**"); auth.logout(location='sidebar')
        
        try:
            conn = st.connection("postgres", type="sql")
            df_u, df_c = buscar_dados_auxiliares(conn)
            df_r, df_p = buscar_dados_operacionais(conn)
            
            st.title("📊 Mesa Operacional")
            exibir_kpis(df_r)
            exibir_graficos(df_r)
            st.markdown("---")

            # Filtros
            c1, c2, c3, c4 = st.columns([1.2, 1.2, 1, 1])
            f_esc = c1.selectbox("Escola", ["Todas"] + sorted(list(df_r['Escola'].unique())))
            f_sup = c2.selectbox("Supervisor", ["Todos"] + sorted(list(df_r['Supervisor'].unique())))
            f_sit = c3.selectbox("Situação", ["Todas", "🔴 FALTA", "🔵 EXCEDENTE", "🟡 AJUSTE", "🟢 OK"])
            f_bus = c4.text_input("Buscar Pessoa")

            l_cargos = list(df_r['Cargo'].unique())
            f_comb = {}
            cols = st.columns(5)
            for i, cg in enumerate(l_cargos):
                with cols[i % 5]:
                    if (sel := st.selectbox(cg, ["Todos","FALTA","EXCEDENTE","OK"], key=f'f_{i}')) != "Todos": f_comb[cg] = sel

            # Aplicação Filtros
            mask = pd.Series([True] * len(df_r))
            if f_esc != "Todas": mask &= (df_r['Escola'] == f_esc)
            if f_sup != "Todos": mask &= (df_r['Supervisor'] == f_sup)
            
            if f_sit != "Todas":
                agg = df_r.groupby('Escola').agg({'Edital':'sum', 'Real':'sum', 'Status_Codigo':list}).reset_index()
                agg['S'] = agg['Real'] - agg['Edital']
                conds = [agg['S']>0, agg['S']<0, (agg['S']==0) & (agg['Status_Codigo'].apply(lambda x: any(s!='OK' for s in x)))]
                agg['St'] = np.select(conds, ["🔵 EXCEDENTE", "🔴 FALTA", "🟡 AJUSTE"], default="🟢 OK")
                mask &= df_r['Escola'].isin(agg[agg['St'] == f_sit]['Escola'])

            if f_comb:
                for c, s in f_comb.items():
                    mask &= df_r['Escola'].isin(df_r[(df_r['Cargo'] == c) & (df_r['Status_Codigo'] == s)]['Escola'])

            if f_bus:
                match = df_p[df_p['Funcionario'].str.contains(f_bus, case=False, na=False)]['Escola'].unique()
                mask &= df_r['Escola'].isin(match)

            df_final = df_r[mask]
            st.info(f"**Escolas: {df_final['Escola'].nunique()}**")

            # --- OTIMIZAÇÃO: PRÉ-PROCESSAMENTO GLOBAL (Fora do Loop) ---
            if not df_final.empty:
                # 1. Prepara dados de exibição UMA vez
                df_view = df_final.copy()
                df_view[['Edital', 'Real']] = df_view[['Edital', 'Real']].astype(str)
                df_view = df_view.rename(columns={'Diferenca_Display': 'Diferenca', 'Status_Display': 'Status'})
                
                # 2. Agrupa pessoas antecipadamente (Dicionário de DataFrames é mais rápido que filtrar no loop)
                pessoas_por_escola = {k: v for k, v in df_p[df_p['Escola'].isin(df_view['Escola'])].groupby('Escola')}
                
                # 3. Loop Limpo (Apenas renderização)
                for nome, df_e in df_view.sort_values('Escola').groupby('Escola'):
                    row1 = df_e.iloc[0]
                    uid = int(row1['UnidadeID'])
                    
                    # Totais (Convertendo de volta apenas para o card, rápido)
                    t_edt = pd.to_numeric(df_e['Edital']).sum()
                    t_real = pd.to_numeric(df_e['Real']).sum()
                    sld = t_real - t_edt
                    
                    icon = "✅"
                    if sld > 0: icon = "🔵"
                    elif sld < 0: icon = "🔴"
                    elif sld == 0 and any(s != 'OK' for s in df_e['Status_Codigo']): icon = "🟡"
                    
                    with st.expander(f"{icon} {nome}", expanded=False):
                        c1, c2 = st.columns([3, 1.5])
                        c1.markdown(f"**Supervisor:** {row1['Supervisor']}")
                        
                        lbl = "⚠️ Pendente" if pd.isnull(row1['DataConferencia']) else f"📅 {row1['DataConferencia'].strftime('%d/%m')}"
                        with c2.popover(lbl, use_container_width=True):
                            dt = st.date_input("Data", value=pd.Timestamp.today() if pd.isnull(row1['DataConferencia']) else row1['DataConferencia'], key=f"d_{uid}")
                            if st.button("Salvar", key=f"s_{uid}"): atualizar_data(uid, dt, conn)

                        cor = "red" if sld < 0 else "blue" if sld > 0 else "green"
                        sinal = "+" if sld > 0 else ""
                        st.markdown(f"""<div style='display:flex; justify-content:space-around; background:#262730; padding:5px; border-radius:5px; border:1px solid #404040'>
                            <span>📋 {t_edt}</span><span>👥 {t_real}</span><span>⚖️ <b style='color:{cor}'>{sinal}{sld}</b></span></div>""", unsafe_allow_html=True)

                        # Tabela Vagas (Usando estilo global e dados já formatados)
                        cols_show = ['Cargo','Edital','Real','Diferenca','Status']
                        st.dataframe(df_e[cols_show].style.apply(estilo_linha_escola, axis=1), use_container_width=True, hide_index=True)

                        # Tabela Pessoas (Busca O(1) no dicionário pré-agrupado)
                        st.markdown("#### 📋 Colaboradores")
                        df_pes = pessoas_por_escola.get(nome, pd.DataFrame())
                        
                        if f_bus and not df_pes.empty:
                            df_pes = df_pes[df_pes['Funcionario'].str.contains(f_bus, case=False, na=False)]

                        if not df_pes.empty:
                            evt = st.dataframe(df_pes[['ID','Funcionario','Cargo']], use_container_width=True, hide_index=True, selection_mode="single-row", on_select="rerun", key=f"p_{uid}")
                            if evt.selection.rows:
                                dialog_editar(df_pes.iloc[evt.selection.rows[0]], df_u, df_c, conn)
                        else:
                            st.warning("Nenhum colaborador.")
            else:
                st.warning("Sem resultados.")

        except Exception as e:
            st.error(f"Erro: {e}")

if __name__ == "__main__":
    main()