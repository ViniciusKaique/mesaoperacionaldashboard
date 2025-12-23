import streamlit as st 
import streamlit_authenticator as stauth
import pandas as pd
import plotly.express as px
import numpy as np 
from PIL import Image
from sqlalchemy import text

# ... (Mantenha as funções configurar_pagina, carregar_logo, realizar_login, 
#      buscar_dados_auxiliares, buscar_dados_operacionais, dialog_editar_colaborador, 
#      acao_atualizar_data, exibir_sidebar, exibir_metricas_topo, exibir_graficos_gerais 
#      EXATAMENTE IGUAIS AO CÓDIGO ANTERIOR) ...

# Vou repetir apenas a função MAIN com a nova lógica de paginação no rodapé

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

            # Filtros
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

            # Aplicação dos Filtros
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

            # --- LÓGICA DE PAGINAÇÃO (STATE) ---
            escolas_unicas = df_final['Escola'].unique()
            total_escolas = len(escolas_unicas)
            ITENS_POR_PAGINA = 10
            
            # Inicializa a variável de página na memória se não existir
            if 'pagina_atual' not in st.session_state:
                st.session_state.pagina_atual = 1

            st.info(f"**Encontradas {total_escolas} escolas.**")
            
            if total_escolas > 0:
                total_paginas = (total_escolas // ITENS_POR_PAGINA) + (1 if total_escolas % ITENS_POR_PAGINA > 0 else 0)
                
                # Garante que a página atual é válida (ex: se filtrou e a pagina 10 não existe mais, volta pra 1)
                if st.session_state.pagina_atual > total_paginas:
                    st.session_state.pagina_atual = 1
                
                # Define o slice (fatia) dos dados baseado na página atual da memória
                inicio = (st.session_state.pagina_atual - 1) * ITENS_POR_PAGINA
                fim = inicio + ITENS_POR_PAGINA
                escolas_pagina = escolas_unicas[inicio:fim]

                # Filtra e prepara visualização
                df_view = df_final[df_final['Escola'].isin(escolas_pagina)].copy()
                df_view = df_view.rename(columns={'Diferenca_Display': 'Diferenca', 'Status_Display': 'Status'})
                df_view[['Edital', 'Real']] = df_view[['Edital', 'Real']].astype(str)
                df_view['Escola'] = pd.Categorical(df_view['Escola'], categories=escolas_pagina, ordered=True)
                df_view = df_view.sort_values(['Escola', 'Cargo'])
                
                escolas_agrupadas = df_view.groupby('Escola', observed=True)

                # --- LOOP DE RENDERIZAÇÃO ---
                for nome_escola, df_escola_view in escolas_agrupadas:
                    # ... (MANTENHA O CONTEÚDO DO LOOP IGUAL AO ANTERIOR: Variáveis, Expander, Tabelas) ...
                    primeira_linha = df_escola_view.iloc[0]
                    nome_supervisor = primeira_linha['Supervisor']
                    unidade_id = int(primeira_linha['UnidadeID'])
                    data_atual = primeira_linha['DataConferencia']
                    lista_status_cod = df_escola_view['Status_Codigo'].tolist()
                    total_edital_esc = int(pd.to_numeric(df_escola_view['Edital']).sum())
                    total_real_esc = int(pd.to_numeric(df_escola_view['Real']).sum())
                    saldo_esc = total_real_esc - total_edital_esc
                    
                    cor_saldo = "red" if saldo_esc < 0 else "blue" if saldo_esc > 0 else "green"
                    sinal_saldo = "+" if saldo_esc > 0 else ""
                    icone = "✅"
                    if saldo_esc > 0: icone = "🔵"
                    elif saldo_esc < 0: icone = "🔴"
                    elif saldo_esc == 0 and any(s != 'OK' for s in lista_status_cod): icone = "🟡"

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
                        </div>""", unsafe_allow_html=True)
                        
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

                        st.markdown("#### 📋 Colaboradores")
                        df_pessoas_escola = df_pessoas[df_pessoas['Escola'] == nome_escola]
                        if termo_busca:
                            df_pessoas_escola = df_pessoas_escola[df_pessoas_escola['Funcionario'].str.contains(termo_busca, case=False, na=False) | df_pessoas_escola['ID'].astype(str).str.contains(termo_busca, na=False)]
                        if not df_pessoas_escola.empty:
                            event = st.dataframe(df_pessoas_escola[['ID','Funcionario','Cargo']], use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row", key=f"grid_{unidade_id}")
                            if len(event.selection.rows) > 0:
                                idx_sel = event.selection.rows[0]
                                dados_colaborador = df_pessoas_escola.iloc[idx_sel]
                                dialog_editar_colaborador(dados_colaborador, df_unidades, df_cargos, conn)
                        else: st.warning("Nenhum colaborador encontrado.")

                # --- CONTROLES DE PAGINAÇÃO NO RODAPÉ ---
                st.markdown("---")
                col_ant, col_info, col_prox = st.columns([1, 2, 1])
                
                with col_ant:
                    if st.button("◀ Anterior", disabled=(st.session_state.pagina_atual == 1), use_container_width=True):
                        st.session_state.pagina_atual -= 1
                        st.rerun()
                
                with col_info:
                    st.markdown(f"<div style='text-align: center; padding-top: 10px;'><b>Página {st.session_state.pagina_atual} de {total_paginas}</b></div>", unsafe_allow_html=True)
                
                with col_prox:
                    if st.button("Próxima ▶", disabled=(st.session_state.pagina_atual == total_paginas), use_container_width=True):
                        st.session_state.pagina_atual += 1
                        st.rerun()

            else:
                st.warning("Nenhuma escola encontrada com os filtros atuais.")

        except Exception as e:
            st.error(f"Erro no sistema: {e}")

if __name__ == "__main__":
    main()