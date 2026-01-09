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
        [data-testid="stMetricValue"] { font-size: 32px; font-weight: bold; }
        .dataframe { font-size: 14px !important; }
        
        th, td { text-align: center !important; }
        .stDataFrame div[data-testid="stDataFrame"] div[role="grid"] div[role="row"] div {
            justify-content: center !important;
            text-align: center !important;
        }

        div[data-testid="stSpinner"] > div {
            font-size: 28px !important; font-weight: bold !important; color: #ff4b4b !important; white-space: nowrap;
        }

        div.stButton > button { width: 100%; display: block; margin: 0 auto; }
    </style>
    """, unsafe_allow_html=True)

def carregar_logo():
    try: return Image.open("logo.png")
    except: return None

def realizar_login():
    try:
        auth_secrets = st.secrets["auth"]
        config = {
            'credentials': {'usernames': {auth_secrets["username"]: {'name': auth_secrets["name"], 'password': auth_secrets["password_hash"], 'email': auth_secrets["email"]}}},
            'cookie': {'name': auth_secrets["cookie_name"], 'key': auth_secrets["cookie_key"], 'expiry_days': auth_secrets["cookie_expiry_days"]}
        }
        authenticator = stauth.Authenticate(
            config['credentials'], 
            config['cookie']['name'], 
            config['cookie']['key'], 
            config['cookie']['expiry_days']
        )
        
        if not st.session_state.get("authentication_status"):
            st.write(""); st.write(""); st.write(""); st.write(""); st.write("")
            col_esq, col_centro, col_dir = st.columns([3, 2, 3])
            
            with col_centro:
                authenticator.login()
                
            if st.session_state.get("authentication_status") is False:
                with col_centro: st.error('Usuário ou senha incorretos')
            
            return None, None
            
        return authenticator, st.session_state.get("name")
        
    except Exception as e:
        st.error(f"Erro Crítico de Autenticação: {e}")
        st.stop()

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
        FROM "Colaboradores"
        WHERE "Ativo" = TRUE
        GROUP BY "UnidadeID", "CargoID"
    )
    SELECT 
        t."NomeTipo" AS "Tipo", 
        u."UnidadeID", 
        u."NomeUnidade" AS "Escola", 
        u."DataConferencia",
        s."NomeSupervisor" AS "Supervisor", 
        c."NomeCargo" AS "Cargo", 
        q."Quantidade" AS "Edital",
        COALESCE(cr."QtdReal", 0) AS "Real",
        (COALESCE(cr."QtdReal", 0) - q."Quantidade") AS "Diferenca_num"
    FROM "QuadroEdital" q
    JOIN "Unidades" u ON q."UnidadeID" = u."UnidadeID"
    JOIN "Cargos" c ON q."CargoID" = c."CargoID"
    JOIN "TiposUnidades" t ON u."TipoID" = t."TipoID"
    JOIN "Supervisores" s ON u."SupervisorID" = s."SupervisorID"
    LEFT JOIN ContagemReal cr ON q."UnidadeID" = cr."UnidadeID" AND q."CargoID" = cr."CargoID"
    ORDER BY u."NomeUnidade", c."NomeCargo";
    """
    
    query_funcionarios = """
    SELECT u."NomeUnidade" AS "Escola", c."NomeCargo" AS "Cargo", col."Nome" AS "Funcionario", col."ColaboradorID" AS "ID"
    FROM "Colaboradores" col
    JOIN "Unidades" u ON col."UnidadeID" = u."UnidadeID"
    JOIN "Cargos" c ON col."CargoID" = c."CargoID"
    WHERE col."Ativo" = TRUE
    ORDER BY u."NomeUnidade", c."NomeCargo", col."Nome";
    """

    df_resumo = _conn.query(query_resumo)
    df_pessoas = _conn.query(query_funcionarios)

    condicoes = [df_resumo['Diferenca_num'] < 0, df_resumo['Diferenca_num'] > 0]
    
    df_resumo['Status_Display'] = np.select(condicoes, ['🔴 FALTA', '🔵 EXCEDENTE'], default='🟢 OK')
    df_resumo['Status_Codigo'] = np.select(condicoes, ['FALTA', 'EXCEDENTE'], default='OK')

    df_resumo['Diferenca_Display'] = df_resumo['Diferenca_num'].apply(lambda x: f"+{x}" if x > 0 else str(int(x)))
    df_resumo['DataConferencia'] = pd.to_datetime(df_resumo['DataConferencia'])
    
    return df_resumo, df_pessoas

@st.dialog("✏️ Editar Colaborador")
def dialog_editar_colaborador(dados_colab, df_unidades, df_cargos, conn):
    st.write(f"Editando: **{dados_colab['Funcionario']}** (ID: {dados_colab['ID']})")
    with st.form("form_edicao"):
        lista_escolas = df_unidades['NomeUnidade'].tolist()
        try: idx_escola = lista_escolas.index(dados_colab['Escola'])
        except: idx_escola = 0
        nova_escola = st.selectbox("🏫 Escola:", lista_escolas, index=idx_escola)

        lista_cargos = df_cargos['NomeCargo'].tolist()
        try: idx_cargo = lista_cargos.index(dados_colab['Cargo'])
        except: idx_cargo = 0
        novo_cargo = st.selectbox("💼 Cargo:", lista_cargos, index=idx_cargo)

        novo_status = st.checkbox("✅ Ativo?", value=True)
        
        if st.form_submit_button("💾 Salvar Alterações"):
            novo_uid = int(df_unidades[df_unidades['NomeUnidade'] == nova_escola]['UnidadeID'].iloc[0])
            novo_cid = int(df_cargos[df_cargos['NomeCargo'] == novo_cargo]['CargoID'].iloc[0])
            colab_id = int(dados_colab['ID'])
            
            try:
                with conn.session as session:
                    session.execute(text("UPDATE \"Colaboradores\" SET \"UnidadeID\" = :uid, \"CargoID\" = :cid, \"Ativo\" = :ativo WHERE \"ColaboradorID\" = :id"), 
                                    {"uid": novo_uid, "cid": novo_cid, "ativo": novo_status, "id": colab_id})
                    session.commit()
                
                st.cache_data.clear() 
                st.toast("Atualizado!", icon="🎉"); st.rerun()
            except Exception as e: st.error(f"Erro: {e}")

def acao_atualizar_data(unidade_id, nova_data, conn):
    try:
        with conn.session as session:
            session.execute(
                text('UPDATE "Unidades" SET "DataConferencia" = :nova_data WHERE "UnidadeID" = :uid'),
                {'nova_data': nova_data, 'uid': unidade_id}
            )
            session.commit()
        st.cache_data.clear()
        st.toast("Data salva!", icon="✅"); st.rerun()
    except Exception as e:
        st.error(f"Erro ao salvar data: {e}")

def exibir_sidebar(authenticator, nome_usuario):
    with st.sidebar:
        if logo := carregar_logo(): st.image(logo, use_container_width=True); st.divider()
        st.write(f"👤 **{nome_usuario}**"); authenticator.logout(location='sidebar'); st.divider(); st.info("Painel Gerencial + Detalhe")

def exibir_metricas_topo(df):
    c1, c2, c3 = st.columns(3)
    total_edital = int(df['Edital'].sum())
    total_real = int(df['Real'].sum())
    saldo = total_real - total_edital
    
    with c1: st.markdown("**<div style='font-size:18px'>📋 Total Edital</div>**", unsafe_allow_html=True); st.metric("", total_edital)
    with c2: st.markdown("**<div style='font-size:18px'>👥 Efetivo Atual</div>**", unsafe_allow_html=True); st.metric("", total_real)
    with c3: st.markdown("**<div style='font-size:18px'>⚖️ Saldo Geral</div>**", unsafe_allow_html=True); st.metric("", saldo)
    st.markdown("---")

def exibir_graficos_gerais(df):
    with st.expander("📈 Ver Gráficos e Resumo Geral", expanded=True):
        df_agrupado = df.groupby('Cargo')[['Edital','Real']].sum().reset_index()
        df_agrupado['Diff_Display'] = (df_agrupado['Real'] - df_agrupado['Edital']).apply(lambda x: f"+{x}" if x > 0 else str(x))
        
        c_g1, c_g2 = st.columns([2,1])
        with c_g1: 
            fig = px.bar(df_agrupado.melt(id_vars=['Cargo'], value_vars=['Edital','Real'], var_name='Tipo', value_name='Quantidade'), 
                         x='Cargo', y='Quantidade', color='Tipo', barmode='group', 
                         color_discrete_map={'Edital': '#808080','Real': '#00bfff'}, text_auto=True, template="seaborn")
            st.plotly_chart(fig, use_container_width=True)
        
        with c_g2: 
            def estilo_tabela(row):
                styles = ['text-align: center;'] * 4
                val = str(row['Diferenca'])
                if '-' in val: styles[3] += 'color: #ff4b4b; font-weight: bold;'
                elif '+' in val: styles[3] += 'color: #29b6f6; font-weight: bold;'
                else: styles[3] += 'color: #00c853; font-weight: bold;'
                return styles
            
            df_display = df_agrupado[['Cargo','Edital','Real','Diff_Display']].rename(columns={'Diff_Display':'Diferenca'})
            st.dataframe(df_display.style.apply(estilo_tabela, axis=1), use_container_width=True, hide_index=True)

def main():
    configurar_pagina()
    authenticator, nome_usuario = realizar_login()
    
    if authenticator:
        exibir_sidebar(authenticator, nome_usuario)
        
        try:
            conn = st.connection("postgres", type="sql")
            
            df_unidades, df_cargos = buscar_dados_auxiliares(conn)
            df_resumo, df_pessoas = buscar_dados_operacionais(conn)
            
            st.title("📊 Mesa Operacional")
            exibir_metricas_topo(df_resumo)
            exibir_graficos_gerais(df_resumo)

            st.markdown("---"); st.subheader("🏫 Detalhe por Escola")

            c_f1, c_f2, c_f3, c_f4 = st.columns([1.2, 1.2, 1, 1])
            with c_f1: filtro_escola = st.selectbox("🔍 Escola:", ["Todas"] + sorted(list(df_resumo['Escola'].unique())))
            with c_f2: filtro_supervisor = st.selectbox("👔 Supervisor:", ["Todos"] + sorted(list(df_resumo['Supervisor'].unique())))
            with c_f3: filtro_situacao = st.selectbox("🚦 Situação:", ["Todas", "🔴 FALTA", "🔵 EXCEDENTE", "🟡 AJUSTE", "🟢 OK"])
            with c_f4: termo_busca = st.text_input("👤 Buscar Colaborador:", "")

            lista_cargos = list(df_resumo['Cargo'].unique())
            filtro_comb = {}
            cols = st.columns(5)
            for i, cargo in enumerate(lista_cargos):
                with cols[i % 5]:
                    if (sel := st.selectbox(cargo, ["Todos","FALTA","EXCEDENTE","OK"], key=f'f_{i}')) != "Todos": 
                        filtro_comb[cargo] = sel

            mask = pd.Series([True] * len(df_resumo))
            if filtro_escola != "Todas": mask &= (df_resumo['Escola'] == filtro_escola)
            if filtro_supervisor != "Todos": mask &= (df_resumo['Supervisor'] == filtro_supervisor)
            
            if filtro_situacao != "Todas":
                agg = df_resumo.groupby('Escola').agg({
                    'Edital': 'sum', 'Real': 'sum', 'Status_Codigo': list
                }).reset_index()
                
                agg['Saldo'] = agg['Real'] - agg['Edital']
                
                condicoes_agg = [
                    agg['Saldo'] > 0,
                    agg['Saldo'] < 0,
                    (agg['Saldo'] == 0) & (agg['Status_Codigo'].apply(lambda x: any(s != 'OK' for s in x)))
                ]
                escolhas_agg = ["🔵 EXCEDENTE", "🔴 FALTA", "🟡 AJUSTE"]
                agg['Status_Calculado'] = np.select(condicoes_agg, escolhas_agg, default="🟢 OK")
                
                escolas_alvo = agg[agg['Status_Calculado'] == filtro_situacao]['Escola']
                mask &= df_resumo['Escola'].isin(escolas_alvo)

            if filtro_comb:
                for c, s in filtro_comb.items():
                    escolas_validas = df_resumo[(df_resumo['Cargo'] == c) & (df_resumo['Status_Codigo'] == s)]['Escola']
                    mask &= df_resumo['Escola'].isin(escolas_validas)

            if termo_busca:
                match = df_pessoas[df_pessoas['Funcionario'].str.contains(termo_busca, case=False, na=False) | df_pessoas['ID'].astype(str).str.contains(termo_busca, na=False)]['Escola'].unique()
                mask &= df_resumo['Escola'].isin(match)

            df_final = df_resumo[mask]
            st.info(f"**Encontradas {df_final['Escola'].nunique()} escolas.**")

            if not df_final.empty:
                df_view = df_final.copy()
                
                df_view = df_view.rename(columns={
                    'Diferenca_Display': 'Diferenca',
                    'Status_Display': 'Status'
                })
                
                # -------------------------------------------------------------
                # OTIMIZAÇÃO IMPLEMENTADA AQUI: PREPARAÇÃO VETORIZADA DOS DADOS
                # -------------------------------------------------------------
                
                # 1. Converter colunas numéricas de uma vez só
                cols_num = ['Edital', 'Real']
                df_view[cols_num] = df_view[cols_num].apply(pd.to_numeric, errors='coerce').fillna(0).astype(int)
                
                df_view = df_view.sort_values('Escola')

                # 2. Criar tabela resumo auxiliar (df_stats) para evitar somar dentro do loop
                df_stats = df_view.groupby('Escola').agg({
                    'Edital': 'sum',
                    'Real': 'sum',
                    'Status_Codigo': lambda x: any(s != 'OK' for s in x), # True se houver pendência interna
                    'UnidadeID': 'first',      # ID é único por escola
                    'Supervisor': 'first',     # Supervisor é único por escola
                    'DataConferencia': 'first' # Data é única por escola
                })

                # 3. Calcular métricas de visualização de forma vetorial (Cálculo Rápido)
                df_stats['Saldo'] = df_stats['Real'] - df_stats['Edital']
                
                # Ícones
                condicoes_icone = [
                    df_stats['Saldo'] > 0,
                    df_stats['Saldo'] < 0,
                    (df_stats['Saldo'] == 0) & (df_stats['Status_Codigo']) # Saldo 0 mas com pendências internas
                ]
                escolhas_icone = ["🔵", "🔴", "🟡"]
                df_stats['Icone'] = np.select(condicoes_icone, escolhas_icone, default="✅")

                # Cores e Sinais
                df_stats['Cor'] = np.where(df_stats['Saldo'] < 0, 'red', np.where(df_stats['Saldo'] > 0, 'blue', 'green'))
                df_stats['Sinal'] = np.where(df_stats['Saldo'] > 0, '+', '')

                # -------------------------------------------------------------
                # FIM DA OTIMIZAÇÃO
                # -------------------------------------------------------------
                
                escolas_agrupadas = df_view.groupby('Escola')

                for nome_escola, df_escola_view in escolas_agrupadas:
                    
                    # Busca os dados pré-calculados usando Hash Map (Instantâneo)
                    stats = df_stats.loc[nome_escola]
                    
                    nome_supervisor = stats['Supervisor']
                    unidade_id = int(stats['UnidadeID'])
                    data_atual = stats['DataConferencia']
                    
                    # Valores já prontos, sem .sum() no loop
                    total_edital_esc = stats['Edital']
                    total_real_esc = stats['Real']
                    saldo_esc = stats['Saldo']
                    
                    # Estilos já prontos
                    cor_saldo = stats['Cor']
                    sinal_saldo = stats['Sinal']
                    icone = stats['Icone']
                    lista_status_cod = df_escola_view['Status_Codigo'].tolist() # Mantido para compatibilidade se necessário

                    with st.expander(f"{icone} {nome_escola}", expanded=False):
                        c_sup, c_btn = st.columns([3, 1.5])
                        with c_sup: st.markdown(f"**👨‍💼 Supervisor:** {nome_supervisor}")
                        with c_btn:
                            label_botao = "⚠️ Pendente" if pd.isnull(data_atual) else f"📅 Conferido: {data_atual.strftime('%d/%m/%Y')}"
                            with st.popover(label_botao, use_container_width=True):
                                st.markdown("Alterar data")
                                nova_data_input = st.date_input("Nova Data:", value=pd.Timestamp.today() if pd.isnull(data_atual) else data_atual, format="DD/MM/YYYY", key=f"dt_{unidade_id}")
                                if st.button("💾 Salvar", key=f"save_{unidade_id}"):
                                    acao_atualizar_data(unidade_id, nova_data_input, conn)

                        st.markdown(f"""
                        <div style='display: flex; justify-content: space-around; background-color: #262730; padding: 8px; border-radius: 5px; margin: 5px 0 15px 0; border: 1px solid #404040;'>
                            <span>📋 Edital: <b>{total_edital_esc}</b></span>
                            <span>👥 Real: <b>{total_real_esc}</b></span>
                            <span>⚖️ Saldo: <b style='color: {cor_saldo}'>{sinal_saldo}{saldo_esc}</b></span>
                        </div>
                        """, unsafe_allow_html=True)

                        st.markdown("#### 📊 Quadro de Vagas")
                        
                        df_tabela_final = df_escola_view[['Cargo','Edital','Real','Diferenca','Status']]
                        
                        def estilo_linha_escola(row):
                            styles = ['text-align: center;'] * 5
                            val = str(row['Diferenca'])
                            if '-' in val: styles[3] += 'color: #ff4b4b; font-weight: bold;'
                            elif '+' in val: styles[3] += 'color: #29b6f6; font-weight: bold;'
                            else: styles[3] += 'color: #00c853; font-weight: bold;'
                            stt = str(row['Status'])
                            if '🔴' in stt: styles[4] += 'color: #ff4b4b; font-weight: bold;'
                            elif '🔵' in stt: styles[4] += 'color: #29b6f6; font-weight: bold;'
                            else: styles[4] += 'color: #00c853; font-weight: bold;'
                            return styles
                        
                        st.dataframe(df_tabela_final.style.apply(estilo_linha_escola, axis=1), use_container_width=True, hide_index=True)

                        st.markdown("#### 📋 Colaboradores (Selecione para Editar)")
                        df_pessoas_escola = df_pessoas[df_pessoas['Escola'] == nome_escola]
                        
                        if termo_busca:
                            df_pessoas_escola = df_pessoas_escola[df_pessoas_escola['Funcionario'].str.contains(termo_busca, case=False, na=False) | df_pessoas_escola['ID'].astype(str).str.contains(termo_busca, na=False)]
                        
                        if not df_pessoas_escola.empty:
                            event = st.dataframe(df_pessoas_escola[['ID','Funcionario','Cargo']], use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row", key=f"grid_{unidade_id}")
                            
                            if len(event.selection.rows) > 0:
                                idx_sel = event.selection.rows[0]
                                dados_colaborador = df_pessoas_escola.iloc[idx_sel]
                                dialog_editar_colaborador(dados_colaborador, df_unidades, df_cargos, conn)
                        else:
                            st.warning("Nenhum colaborador encontrado.")

            else:
                st.warning("Nenhuma escola encontrada com os filtros atuais.")

        except Exception as e:
            st.error(f"Erro no sistema: {e}")

if __name__ == "__main__":
    main()