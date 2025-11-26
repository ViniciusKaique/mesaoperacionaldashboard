import streamlit as st
import streamlit_authenticator as stauth
import pandas as pd
from sqlalchemy import text

# --- CONFIGURAÇÃO ---
st.set_page_config(page_title="Gerenciamento", layout="wide", page_icon="⚙️")

# --- CSS (Mesmo visual do principal) ---
st.markdown("""
<style>
    .block-container { padding-top: 1rem; }
    .stButton button { background-color: #ff4b4b; color: white; border-radius: 8px; width: 100%; }
</style>
""", unsafe_allow_html=True)

# --- AUTENTICAÇÃO (Necessário repetir para proteger a página) ---
try:
    auth_secrets = st.secrets["auth"]
    config = {
        'credentials': {'usernames': {auth_secrets["username"]: {'name': auth_secrets["name"], 'password': auth_secrets["password_hash"], 'email': auth_secrets["email"]}}},
        'cookie': {'name': auth_secrets["cookie_name"], 'key': auth_secrets["cookie_key"], 'expiry_days': auth_secrets["cookie_expiry_days"]}
    }
except: st.stop()

authenticator = stauth.Authenticate(config['credentials'], config['cookie']['name'], config['cookie']['key'], config['cookie']['expiry_days'])

# Se não estiver logado, para tudo.
if not st.session_state.get("authentication_status"):
    st.warning("Por favor, faça login na página inicial.")
    st.stop()

# --- SISTEMA DE EDIÇÃO ---
st.title("⚙️ Gerenciamento de Banco de Dados")
st.info("Edite os dados como se fosse uma planilha. As alterações são salvas ao clicar no botão abaixo da tabela.")

# 1. Seleção da Tabela
tabela = st.selectbox("Selecione a Tabela para Editar:", ["Colaboradores", "Unidades", "QuadroEdital"])

# Mapeamento de IDs (Necessário para o sistema saber qual linha atualizar)
pk_map = {
    "Colaboradores": "ColaboradorID",
    "Unidades": "UnidadeID",
    "QuadroEdital": "QuadroID" # Supondo que exista um ID único aqui
}
pk_column = pk_map.get(tabela)

try:
    conn = st.connection("postgres", type="sql")
    
    # Carrega dados atuais (Aspas duplas para garantir leitura correta no Postgres)
    df = conn.query(f'SELECT * FROM "{tabela}"', ttl=0)
    
    # --- EDITOR DE DADOS ---
    # num_rows="dynamic" permite adicionar/remover linhas
    edicao = st.data_editor(
        df, 
        key=f"editor_{tabela}", 
        num_rows="dynamic", 
        use_container_width=True,
        height=600
    )

    # --- BOTÃO DE SALVAR ---
    if st.button("💾 Salvar Alterações no Banco de Dados"):
        with conn.session as session:
            has_changes = False
            
            # 1. PROCESSAR ADIÇÕES (INSERT)
            for new_row in st.session_state[f"editor_{tabela}"]["added_rows"]:
                if new_row: # Se a linha não estiver vazia
                    cols = ", ".join([f'"{k}"' for k in new_row.keys()])
                    vals = ", ".join([f"'{v}'" for v in new_row.values()])
                    sql = f'INSERT INTO "{tabela}" ({cols}) VALUES ({vals});'
                    session.execute(text(sql))
                    has_changes = True

            # 2. PROCESSAR EDIÇÕES (UPDATE)
            # edited_rows retorna {index: {coluna: valor_novo}}
            for idx, updates in st.session_state[f"editor_{tabela}"]["edited_rows"].items():
                # Pega o ID da linha original usando o índice do Pandas
                row_id = df.iloc[idx][pk_column]
                
                set_clause = ", ".join([f'"{k}" = \'{v}\'' for k, v in updates.items()])
                sql = f'UPDATE "{tabela}" SET {set_clause} WHERE "{pk_column}" = {row_id};'
                session.execute(text(sql))
                has_changes = True

            # 3. PROCESSAR EXCLUSÕES (DELETE)
            for idx in st.session_state[f"editor_{tabela}"]["deleted_rows"]:
                row_id = df.iloc[idx][pk_column]
                sql = f'DELETE FROM "{tabela}" WHERE "{pk_column}" = {row_id};'
                session.execute(text(sql))
                has_changes = True

            if has_changes:
                session.commit()
                st.success("✅ Banco de dados atualizado com sucesso!")
                st.rerun() # Recarrega a página para mostrar dados novos
            else:
                st.info("Nenhuma alteração detectada para salvar.")

except Exception as e:
    st.error(f"Erro: {e}")
    st.warning("Dica: Verifique se a tabela tem uma coluna de ID único e se os nomes das colunas estão corretos.")