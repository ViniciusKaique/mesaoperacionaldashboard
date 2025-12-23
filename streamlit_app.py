import streamlit as st
import streamlit_authenticator as stauth
import pandas as pd
import plotly.express as px
import numpy as np
from PIL import Image
from sqlalchemy import text

def configurar_pagina():
    st.set_page_config(page_title="Mesa Operacional", layout="wide", page_icon="📊")
    st.markdown("""
    <style>
        .block-container { padding-top: 1rem; }
        .stButton button { background-color: #ff4b4b; color: white; border-radius: 8px; width: 100%; display: block; margin: 0 auto; }
        [data-testid="stMetricValue"] { font-size: 32px; font-weight: bold; }
        .dataframe { font-size: 14px !important; }
        th, td { text-align: center !important; }
        .stDataFrame div[data-testid="stDataFrame"] div[role="grid"] div[role="row"] div { justify-content: center !important; text-align: center !important; }
        div[data-testid="stSpinner"] > div { font-size: 28px !important; font-weight: bold !important; color: #ff4b4b !important; white-space: nowrap; }
    </style>
    """, unsafe_allow_html=True)

def carregar_logo():
    try: return Image.open("logo.png")
    except: return None

def realizar_login():
    try:
        s = st.secrets["auth"]
        creds = {'usernames': {s["username"]: {'name': s["name"], 'password': s["password_hash"], 'email': s["email"]}}}
        cookie = {'name': s["cookie_name"], 'key': s["cookie_key"], 'expiry_days': s["cookie_expiry_days"]}
        authenticator = stauth.Authenticate(creds, cookie['name'], cookie['key'], cookie['expiry_days'])
        
        if not st.session_state.get("authentication_status"):
            st.write("\n" * 5)
            col1, col2, col3 = st.columns([3, 2, 3])
            with col2:
                try: authenticator.login(location='main')
                except: authenticator.login()
            if st.session_state.get("authentication_status") is False:
                with col2: st.error('Usuário ou senha incorretos')
            return None, None
        return authenticator, st.session_state.get("name")
    except Exception:
        st.error("Erro Crítico: Secrets não configurados."); st.stop()

@st.cache_data(ttl=600, show_spinner=False)
def buscar_dados_auxiliares(_conn):
    return (_conn.query('SELECT "UnidadeID", "NomeUnidade" FROM "Unidades" ORDER BY "NomeUnidade"'),
            _conn.query('SELECT "CargoID", "NomeCargo" FROM "Cargos" ORDER BY "NomeCargo"'))

@st.cache_data(ttl=600, show_spinner=False)
def buscar_dados_operacionais(_conn):
    q_resumo = """
    WITH ContagemReal AS (
        SELECT "UnidadeID", "CargoID", COUNT(*) as "QtdReal"
        FROM "Colaboradores" WHERE "Ativo" = TRUE GROUP BY "UnidadeID", "CargoID"
    )
    SELECT 
        t."NomeTipo" AS "Tipo", u."UnidadeID", u."NomeUnidade" AS "Escola", u."DataConferencia",
        s."NomeSupervisor" AS "Supervisor", c."NomeCargo" AS "Cargo", q."Quantidade" AS "Edital",
        COALESCE(cr."QtdReal", 0) AS "Real"
    FROM "QuadroEdital" q
    JOIN "Unidades" u ON q."UnidadeID" = u."UnidadeID"
    JOIN "Cargos" c ON q."CargoID" = c."CargoID"
    JOIN "TiposUnidades" t ON u."TipoID" = t."TipoID"
    JOIN "Supervisores" s ON u."SupervisorID" = s."SupervisorID"
    LEFT JOIN ContagemReal cr ON q."UnidadeID" = cr."UnidadeID" AND q."CargoID" = cr."CargoID"
    ORDER BY u."NomeUnidade", c."NomeCargo";
    """
    q_func = """
    SELECT u."NomeUnidade" AS "Escola", c."NomeCargo" AS "Cargo", col."Nome" AS "Funcionario", col."ColaboradorID" AS "ID"
    FROM "Colaboradores" col
    JOIN "Unidades" u ON col."UnidadeID" = u."UnidadeID"
    JOIN "Cargos" c ON col."CargoID" = c."CargoID"
    WHERE col."Ativo" = TRUE
    ORDER BY u."NomeUnidade", c."NomeCargo", col."Nome";
    """
    df_res = _conn.query(q_resumo)
    df_pes = _conn.query(q_func)

    df_res['Diferenca_num'] = df_res['Real'] - df_res['Edital']
    conds = [df_res['Diferenca_num'] < 0, df_res['Diferenca_num'] > 0]
    df_res['Status_Codigo'] = np.select(conds, ['FALTA', 'EXCEDENTE'], default='OK')
    df_res['Status_Display'] = np.select(conds, ['🔴 FALTA', '🔵 EXCEDENTE'], default='🟢 OK')
    df_res['DataConferencia'] = pd.to_datetime(df_res['DataConferencia'])
    
    return df_res, df_pes

@st.dialog("✏️ Editar Colaborador")
def dialog_editar_colaborador(dados, df_u, df_c, conn):
    st.write(f"Editando: **{dados['Funcionario']}** (ID: {dados['ID']})")
    with st.form("form_edicao"):
        try: idx_e = df_u['NomeUnidade'].tolist().index(dados['Escola'])
        except: idx_e = 0
        nescola = st.selectbox("🏫 Escola:", df_u['NomeUnidade'], index=idx_e)

        try: idx_c = df_c['NomeCargo'].tolist().index(dados['Cargo'])
        except: idx_c = 0
        ncargo = st.selectbox("💼 Cargo:", df_c['NomeCargo'], index=idx_c)
        nativo = st.checkbox("✅ Ativo?", value=True)
        
        if st.form_submit_button("💾 Salvar"):
            uid = int(df_u.loc[df_u['NomeUnidade'] == nescola, 'UnidadeID'].values[0])
            cid = int(df_c.loc[df_c['NomeCargo'] == ncargo, 'CargoID'].values[0])
            with conn.session as s:
                s.execute(text("UPDATE \"Colaboradores\" SET \"UnidadeID\"=:u, \"CargoID\"=:c, \"Ativo\"=:a WHERE \"ColaboradorID\"=:id"),
                          {"u": uid, "c": cid, "a": nativo, "id": int(dados['ID'])})
                s.commit()
            st.cache_data.clear()
            st.toast("Atualizado!", icon="🎉"); st.rerun()

def acao_atualizar_data(uid, ndata, conn):
    with conn.session as s:
        s.execute(text("UPDATE \"Unidades\" SET \"DataConferencia\" = :d WHERE \"UnidadeID\" = :u"), {"d": ndata, "u": uid})
        s.commit()
    st.cache_data.clear()
    st.toast("Data salva!", icon="✅"); st.rerun()

def exibir_sidebar(auth, user):
    with st.sidebar:
        if logo := carregar_logo(): st.image(logo, use_container_width=True); st.divider()
        st.write(f"👤 **{user}**"); auth.logout(location='sidebar'); st.divider(); st.info("Painel Gerencial")

def exibir_metricas_topo(df):
    c1, c2, c3 = st.columns(3)
    te, tr = int(df['Edital'].sum()), int(df['Real'].sum())
    with c1: st.metric("📋 Total Edital", te)
    with c2: st.metric("👥 Efetivo Atual", tr)
    with c3: st.metric("⚖️ Saldo Geral", tr - te)
    st.markdown("---")

def exibir_graficos_gerais(df):
    with st.expander("📈 Ver Gráficos e Resumo Geral", expanded=True):
        grp = df.groupby('Cargo')[['Edital','Real']].sum().reset_index()
        grp['Dif'] = grp['Real'] - grp['Edital']
        
        c1, c2 = st.columns([2,1])
        with c1:
            st.plotly_chart(px.bar(grp.melt('Cargo', ['Edital','Real'], 'Tipo', 'Qtd'), x='Cargo', y='Qtd', color='Tipo', 
                            barmode='group', color_discrete_map={'Edital': '#808080','Real': '#00bfff'}, text_auto=True, template="seaborn"), use_container_width=True)
        with c2:
            st.dataframe(grp[['Cargo','Edital','Real','Dif']].style.apply(lambda r: ['color: #ff4b4b; font-weight: bold' if r['Dif'] < 0 else 'color: #29b6f6; font-weight: bold' if r['Dif'] > 0 else 'color: #00c853; font-weight: bold' if c == 'Dif' else '' for c in r.index], axis=1), use_container_width=True, hide_index=True)

def main():
    configurar_pagina()
    auth, user = realizar_login()
    if not auth: return

    exibir_sidebar(auth, user)
    try:
        conn = st.connection("postgres", type="sql")
        df_unidades, df_cargos = buscar_dados_auxiliares(conn)
        df_resumo, df_pessoas = buscar_dados_operacionais(conn)
        
        st.title("📊 Mesa Operacional")
        exibir_metricas_topo(df_resumo)
        exibir_graficos_gerais(df_resumo)
        st.markdown("---"); st.subheader("🏫 Detalhe por Escola")

        cf1, cf2, cf3, cf4 = st.columns([1.2, 1.2, 1, 1])
        f_esc = cf1.selectbox("🔍 Escola:", ["Todas"] + sorted(df_resumo['Escola'].unique().tolist()))
        f_sup = cf2.selectbox("👔 Supervisor:", ["Todos"] + sorted(df_resumo['Supervisor'].unique().tolist()))
        f_sit = cf3.selectbox("🚦 Situação:", ["Todas", "🔴 FALTA", "🔵 EXCEDENTE", "🟡 AJUSTE", "🟢 OK"])
        busca = cf4.text_input("👤 Buscar:", "")

        mask = pd.Series([True] * len(df_resumo))
        if f_esc != "Todas": mask &= (df_resumo['Escola'] == f_esc)
        if f_sup != "Todos": mask &= (df_resumo['Supervisor'] == f_sup)
        
        if f_sit != "Todas":
            agg = df_resumo.groupby('Escola').agg({'Edital':'sum', 'Real':'sum', 'Status_Codigo': list}).reset_index()
            agg['Saldo'] = agg['Real'] - agg['Edital']
            agg['Sit'] = np.select([agg['Saldo']>0, agg['Saldo']<0, (agg['Saldo']==0) & agg['Status_Codigo'].apply(lambda x: any(s!='OK' for s in x))], 
                                   ["🔵 EXCEDENTE", "🔴 FALTA", "🟡 AJUSTE"], default="🟢 OK")
            mask &= df_resumo['Escola'].isin(agg[agg['Sit'] == f_sit]['Escola'])

        if busca:
            mask &= df_resumo['Escola'].isin(df_pessoas[df_pessoas['Funcionario'].str.contains(busca, case=False) | df_pessoas['ID'].astype(str).str.contains(busca)]['Escola'].unique())

        df_final = df_resumo[mask]
        st.info(f"**Escolas encontradas: {df_final['Escola'].nunique()}**")

        for nome, df_esc in df_final.groupby('Escola'):
            row1 = df_esc.iloc[0]
            sup, uid, dt, stt_list = row1['Supervisor'], int(row1['UnidadeID']), row1['DataConferencia'], df_esc['Status_Codigo'].tolist()
            
            te, tr = df_esc['Edital'].sum(), df_esc['Real'].sum()
            saldo = tr - te
            
            icone = "🔵" if saldo > 0 else "🔴" if saldo < 0 else "🟡" if any(s != 'OK' for s in stt_list) else "✅"
            cor = "blue" if saldo > 0 else "red" if saldo < 0 else "green"

            with st.expander(f"{icone} {nome}", expanded=False):
                c_s, c_b = st.columns([3, 1.5])
                c_s.markdown(f"**👨‍💼 Supervisor:** {sup}")
                
                lbl_btn = "⚠️ Pendente" if pd.isnull(dt) else f"📅 {dt.strftime('%d/%m/%Y')}"
                with c_b.popover(lbl_btn, use_container_width=True):
                    nd = st.date_input("Nova Data:", value=pd.Timestamp.today() if pd.isnull(dt) else dt, key=f"d_{uid}")
                    if st.button("💾", key=f"s_{uid}"): acao_atualizar_data(uid, nd, conn)

                st.markdown(f"<div style='background:#262730;padding:8px;border-radius:5px;margin-bottom:15px;display:flex;justify-content:space-around;border:1px solid #404040'><span>📋 Edital: <b>{te}</b></span><span>👥 Real: <b>{tr}</b></span><span>⚖️ Saldo: <b style='color:{cor}'>{saldo:+d}</b></span></div>", unsafe_allow_html=True)

                st.markdown("#### 📊 Quadro")
                df_show = df_esc[['Cargo','Edital','Real','Diferenca_num','Status_Display']].rename(columns={'Diferenca_num':'Dif', 'Status_Display':'Status'})
                
                st.dataframe(df_show.style.apply(lambda r: [
                    'color: #ff4b4b; font-weight: bold' if ('Dif' in c and r['Dif'] < 0) or ('Status' in c and '🔴' in str(r['Status'])) else 
                    'color: #29b6f6; font-weight: bold' if ('Dif' in c and r['Dif'] > 0) or ('Status' in c and '🔵' in str(r['Status'])) else 
                    'color: #00c853; font-weight: bold' if ('Dif' in c or 'Status' in c) else '' 
                    for c in r.index], axis=1).format({'Dif': "{:+d}"}), use_container_width=True, hide_index=True)

                st.markdown("#### 📋 Colaboradores")
                df_p = df_pessoas[(df_pessoas['Escola'] == nome) & (df_pessoas['Funcionario'].str.contains(busca, case=False) if busca else True)]
                
                if not df_p.empty:
                    sel = st.dataframe(df_p[['ID','Funcionario','Cargo']], use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row", key=f"g_{uid}")
                    if len(sel.selection.rows) > 0:
                        dialog_editar_colaborador(df_p.iloc[sel.selection.rows[0]], df_unidades, df_cargos, conn)
                else: st.warning("Nenhum colaborador.")

    except Exception as e: st.error(f"Erro: {e}")

if __name__ == "__main__":
    main()