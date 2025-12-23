import streamlit as st, streamlit_authenticator as stauth, pandas as pd, plotly.express as px, numpy as np 
from PIL import Image
from sqlalchemy import text

def configurar_pagina():
    st.set_page_config(page_title="Mesa Operacional", layout="wide", page_icon="📊")
    st.markdown("""<style>.block-container{padding-top:1rem}.stButton button{background-color:#ff4b4b;color:white;border-radius:8px}[data-testid="stMetricValue"]{font-size:32px;font-weight:bold}.dataframe{font-size:14px!important}th,td{text-align:center!important}.stDataFrame div[data-testid="stDataFrame"] div[role="grid"] div[role="row"] div{justify-content:center!important;text-align:center!important}div[data-testid="stSpinner"]>div{font-size:28px!important;font-weight:bold!important;color:#ff4b4b!important;white-space:nowrap}div.stButton>button{width:100%;display:block;margin:0 auto}</style>""", unsafe_allow_html=True)

def realizar_login():
    try:
        s = st.secrets["auth"]
        creds = {'usernames': {s["username"]: {'name': s["name"], 'password': s["password_hash"], 'email': s["email"]}}}
        auth = stauth.Authenticate(creds, s["cookie_name"], s["cookie_key"], s["cookie_expiry_days"])
        if not st.session_state.get("authentication_status"):
            st.write("\n"*5); c1, c2, c3 = st.columns([3, 2, 3])
            with c2:
                try: auth.login(location='main')
                except: auth.login()
            if st.session_state.get("authentication_status") is False: c2.error('Usuário ou senha incorretos')
            return None, None
        return auth, st.session_state.get("name")
    except Exception as e: st.error("Erro Crítico: Secrets não configurados."); st.stop()

@st.cache_data(ttl=600, show_spinner=False)
def buscar_dados(_conn):
    # Queries compactadas
    df_u = _conn.query('SELECT "UnidadeID", "NomeUnidade" FROM "Unidades" ORDER BY "NomeUnidade"')
    df_c = _conn.query('SELECT "CargoID", "NomeCargo" FROM "Cargos" ORDER BY "NomeCargo"')
    
    q_resumo = """WITH ContagemReal AS (SELECT "UnidadeID", "CargoID", COUNT(*) as "QtdReal" FROM "Colaboradores" WHERE "Ativo" = TRUE GROUP BY "UnidadeID", "CargoID") SELECT t."NomeTipo" AS "Tipo", u."UnidadeID", u."NomeUnidade" AS "Escola", u."DataConferencia", s."NomeSupervisor" AS "Supervisor", c."NomeCargo" AS "Cargo", q."Quantidade" AS "Edital", COALESCE(cr."QtdReal", 0) AS "Real" FROM "QuadroEdital" q JOIN "Unidades" u ON q."UnidadeID" = u."UnidadeID" JOIN "Cargos" c ON q."CargoID" = c."CargoID" JOIN "TiposUnidades" t ON u."TipoID" = t."TipoID" JOIN "Supervisores" s ON u."SupervisorID" = s."SupervisorID" LEFT JOIN ContagemReal cr ON q."UnidadeID" = cr."UnidadeID" AND q."CargoID" = cr."CargoID" ORDER BY u."NomeUnidade", c."NomeCargo";"""
    q_func = """SELECT u."NomeUnidade" AS "Escola", c."NomeCargo" AS "Cargo", col."Nome" AS "Funcionario", col."ColaboradorID" AS "ID" FROM "Colaboradores" col JOIN "Unidades" u ON col."UnidadeID" = u."UnidadeID" JOIN "Cargos" c ON col."CargoID" = c."CargoID" WHERE col."Ativo" = TRUE ORDER BY u."NomeUnidade", c."NomeCargo", col."Nome";"""

    df_r, df_p = _conn.query(q_resumo), _conn.query(q_func)
    df_r['Diferenca_num'] = df_r['Real'] - df_r['Edital']
    cond = [df_r['Diferenca_num'] < 0, df_r['Diferenca_num'] > 0]
    df_r['Status_Display'], df_r['Status_Codigo'] = np.select(cond, ['🔴 FALTA', '🔵 EXCEDENTE'], '🟢 OK'), np.select(cond, ['FALTA', 'EXCEDENTE'], 'OK')
    df_r['Diferenca_Display'] = df_r['Diferenca_num'].apply(lambda x: f"+{x}" if x > 0 else str(int(x)))
    df_r['DataConferencia'] = pd.to_datetime(df_r['DataConferencia'])
    return df_u, df_c, df_r, df_p

@st.dialog("✏️ Editar Colaborador")
def dialog_editar(dados, df_u, df_c, conn):
    st.write(f"Editando: **{dados['Funcionario']}** (ID: {dados['ID']})")
    with st.form("form_edicao"):
        l_esc, l_carg = df_u['NomeUnidade'].tolist(), df_c['NomeCargo'].tolist()
        n_esc = st.selectbox("🏫 Escola:", l_esc, index=l_esc.index(dados['Escola']) if dados['Escola'] in l_esc else 0)
        n_carg = st.selectbox("💼 Cargo:", l_carg, index=l_carg.index(dados['Cargo']) if dados['Cargo'] in l_carg else 0)
        ativo = st.checkbox("✅ Ativo?", value=True)
        if st.form_submit_button("💾 Salvar"):
            uid = int(df_u.loc[df_u['NomeUnidade']==n_esc, 'UnidadeID'].values[0])
            cid = int(df_c.loc[df_c['NomeCargo']==n_carg, 'CargoID'].values[0])
            try:
                with conn.session as s:
                    s.execute(text("UPDATE \"Colaboradores\" SET \"UnidadeID\"=:u, \"CargoID\"=:c, \"Ativo\"=:a WHERE \"ColaboradorID\"=:id"), {"u":uid,"c":cid,"a":ativo,"id":int(dados['ID'])})
                    s.commit()
                st.cache_data.clear(); st.toast("Atualizado!", icon="🎉"); st.rerun()
            except Exception as e: st.error(f"Erro: {e}")

def main():
    configurar_pagina()
    auth, usuario = realizar_login()
    if not auth: return
    with st.sidebar:
        try: st.image(Image.open("logo.png"), use_container_width=True); st.divider()
        except: pass
        st.write(f"👤 **{usuario}**"); auth.logout(location='sidebar'); st.divider(); st.info("Painel Gerencial + Detalhe")

    try:
        conn = st.connection("postgres", type="sql")
        df_unidades, df_cargos, df_resumo, df_pessoas = buscar_dados(conn)

        st.title("📊 Mesa Operacional")
        c1, c2, c3 = st.columns(3)
        c1.metric("📋 Total Edital", int(df_resumo['Edital'].sum()))
        c2.metric("👥 Efetivo Atual", int(df_resumo['Real'].sum()))
        c3.metric("⚖️ Saldo Geral", int(df_resumo['Real'].sum() - df_resumo['Edital'].sum()))
        st.markdown("---")

        with st.expander("📈 Ver Gráficos e Resumo Geral", expanded=True):
            df_g = df_resumo.groupby('Cargo')[['Edital','Real']].sum().reset_index()
            df_g['Diff_Display'] = (df_g['Real'] - df_g['Edital']).apply(lambda x: f"+{x}" if x > 0 else str(x))
            cg1, cg2 = st.columns([2,1])
            cg1.plotly_chart(px.bar(df_g.melt(id_vars=['Cargo'], value_vars=['Edital','Real']), x='Cargo', y='value', color='variable', barmode='group', color_discrete_map={'Edital':'#808080','Real':'#00bfff'}, text_auto=True), use_container_width=True)
            def style_tbl(r):
                c = '#ff4b4b' if '-' in str(r['Diferenca']) else '#29b6f6' if '+' in str(r['Diferenca']) else '#00c853'
                return ['text-align: center'] * 3 + [f'text-align: center; color: {c}; font-weight: bold']
            cg2.dataframe(df_g[['Cargo','Edital','Real','Diff_Display']].rename(columns={'Diff_Display':'Diferenca'}).style.apply(style_tbl, axis=1), use_container_width=True, hide_index=True)

        st.markdown("---"); st.subheader("🏫 Detalhe por Escola")
        cf1, cf2, cf3, cf4 = st.columns([1.2, 1.2, 1, 1])
        f_esc = cf1.selectbox("🔍 Escola:", ["Todas"] + sorted(df_resumo['Escola'].unique().tolist()))
        f_sup = cf2.selectbox("👔 Supervisor:", ["Todos"] + sorted(df_resumo['Supervisor'].unique().tolist()))
        f_sit = cf3.selectbox("🚦 Situação:", ["Todas", "🔴 FALTA", "🔵 EXCEDENTE", "🟡 AJUSTE", "🟢 OK"])
        busca = cf4.text_input("👤 Buscar Colaborador:")

        f_cargos, cols = {}, st.columns(5)
        for i, c in enumerate(df_resumo['Cargo'].unique()):
            with cols[i % 5]:
                if (sel := st.selectbox(c, ["Todos","FALTA","EXCEDENTE","OK"], key=f'f_{i}')) != "Todos": f_cargos[c] = sel

        mask = pd.Series([True]*len(df_resumo))
        if f_esc != "Todas": mask &= (df_resumo['Escola'] == f_esc)
        if f_sup != "Todos": mask &= (df_resumo['Supervisor'] == f_sup)
        if f_sit != "Todas":
            agg = df_resumo.groupby('Escola').agg({'Edital':'sum', 'Real':'sum', 'Status_Codigo':list}).reset_index()
            agg['Saldo'] = agg['Real'] - agg['Edital']
            agg['S'] = np.select([agg['Saldo']>0, agg['Saldo']<0, (agg['Saldo']==0) & (agg['Status_Codigo'].apply(lambda x: any(s!='OK' for s in x)))], ["🔵 EXCEDENTE", "🔴 FALTA", "🟡 AJUSTE"], "🟢 OK")
            mask &= df_resumo['Escola'].isin(agg[agg['S'] == f_sit]['Escola'])
        for c, s in f_cargos.items(): mask &= df_resumo['Escola'].isin(df_resumo[(df_resumo['Cargo']==c) & (df_resumo['Status_Codigo']==s)]['Escola'])
        if busca: mask &= df_resumo['Escola'].isin(df_pessoas[df_pessoas['Funcionario'].str.contains(busca, case=False, na=False)|df_pessoas['ID'].astype(str).str.contains(busca, na=False)]['Escola'].unique())

        df_final = df_resumo[mask].copy().sort_values('Escola')
        st.info(f"**Encontradas {df_final['Escola'].nunique()} escolas.**")
        if not df_final.empty:
            df_final[['Edital', 'Real']] = df_final[['Edital', 'Real']].astype(str)
            for esc, dfe in df_final.groupby('Escola'):
                row1 = dfe.iloc[0]
                uid, dt, tot_e, tot_r = int(row1['UnidadeID']), row1['DataConferencia'], pd.to_numeric(dfe['Edital']).sum(), pd.to_numeric(dfe['Real']).sum()
                saldo = tot_r - tot_e
                icon = "🔵" if saldo > 0 else "🔴" if saldo < 0 else "🟡" if any(s!='OK' for s in dfe['Status_Codigo']) else "✅"
                with st.expander(f"{icon} {esc}", expanded=False):
                    c_s, c_b = st.columns([3, 1.5])
                    c_s.markdown(f"**👨‍💼 Supervisor:** {row1['Supervisor']}")
                    with c_b.popover("⚠️ Pendente" if pd.isnull(dt) else f"📅 {dt.strftime('%d/%m/%Y')}", use_container_width=True):
                        ndt = st.date_input("Nova Data:", value=pd.Timestamp.today() if pd.isnull(dt) else dt, format="DD/MM/YYYY", key=f"d{uid}")
                        if st.button("💾", key=f"s{uid}"):
                            with conn.session as s: s.execute(text(f"UPDATE \"Unidades\" SET \"DataConferencia\"='{ndt}' WHERE \"UnidadeID\"={uid}")); s.commit()
                            st.cache_data.clear(); st.rerun()

                    cor = "red" if saldo < 0 else "blue" if saldo > 0 else "green"
                    st.markdown(f"<div style='background:#262730;padding:8px;border-radius:5px;border:1px solid #404040;display:flex;justify-content:space-around;margin-bottom:15px'><span>📋 {tot_e}</span><span>👥 {tot_r}</span><span style='color:{cor}'><b>{'+' if saldo>0 else ''}{saldo}</b></span></div>", unsafe_allow_html=True)
                    
                    df_view = dfe[['Cargo','Edital','Real','Diferenca_Display','Status_Display']].rename(columns={'Diferenca_Display':'Diferenca','Status_Display':'Status'})
                    def style_row(r):
                        c = '#ff4b4b' if '-' in str(r['Diferenca']) else '#29b6f6' if '+' in str(r['Diferenca']) else '#00c853'
                        return [f'text-align:center; color:{c if i in [3,4] else "inherit"}; font-weight:{"bold" if i in [3,4] else "normal"}' for i in range(5)]
                    st.dataframe(df_view.style.apply(style_row, axis=1), use_container_width=True, hide_index=True)

                    df_pes = df_pessoas[(df_pessoas['Escola'] == esc) & (df_pessoas['Funcionario'].str.contains(busca, case=False, na=False) if busca else True)]
                    if not df_pes.empty:
                        evt = st.dataframe(df_pes[['ID','Funcionario','Cargo']], use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row", key=f"g{uid}")
                        if len(evt.selection.rows): dialog_editar(df_pes.iloc[evt.selection.rows[0]], df_unidades, df_cargos, conn)
                    else: st.warning("Nenhum colaborador.")
        else: st.warning("Nenhuma escola encontrada.")
    except Exception as e: st.error(f"Erro: {e}")

if __name__ == "__main__": main()