import streamlit as st
import pandas as pd
import requests
import time
import io
from datetime import datetime

# ==============================================================================
# 1. CONFIGURAÇÃO DA PÁGINA
# ==============================================================================
st.set_page_config(page_title="Extrator Relatório Gerencial", layout="wide", page_icon="📊")

# ==============================================================================
# 2. SEGURANÇA E ESTADO (Herdado da página principal)
# ==============================================================================
# Verifica se o usuário fez login na página principal
if not st.session_state.get("authentication_status"):
    st.warning("🔒 Acesso restrito. Por favor, faça login na página inicial primeiro.")
    st.stop()

# Verifica se temos o token. Se não tiver, tenta pegar do secrets (caso tenha hardcoded para dev)
if 'api_token' not in st.session_state or not st.session_state['api_token']:
    st.error("Token de autenticação não encontrado. Recarregue a página inicial.")
    st.stop()

# ==============================================================================
# 3. CONFIGURAÇÃO API
# ==============================================================================
# Base URL muda ligeiramente para a raiz da API Web
BASE_URL = "https://limpeza.sme.prefeitura.sp.gov.br/api/web"

# Headers "Camuflados" (Crucial para passar pelo Firewall/WAF)
# Mudamos o Referer para a área de relatórios
HEADERS_TEMPLATE = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Origin": "https://limpeza.sme.prefeitura.sp.gov.br",
    "Referer": "https://limpeza.sme.prefeitura.sp.gov.br/relatorio/gerencial/", # <--- O Pulo do gato
    "sec-ch-ua": '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin"
}

def get_auth_headers():
    """Monta o header com o token da sessão atual."""
    h = HEADERS_TEMPLATE.copy()
    token = st.session_state['api_token']
    h["Authorization"] = f"Bearer {token}"
    return h

# ==============================================================================
# 4. FUNÇÕES DE EXTRAÇÃO
# ==============================================================================
def buscar_lista_escolas():
    """Busca todos os IDs e Nomes das escolas."""
    url = f"{BASE_URL}/unidade-escolar/combo-todos"
    headers = get_auth_headers()
    
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            return r.json() # Retorna lista de dicts [{'id': 1, 'descricao': 'Escola X'}, ...]
        else:
            st.error(f"Erro ao buscar lista: {r.status_code}")
            return []
    except Exception as e:
        st.error(f"Erro de conexão: {e}")
        return []

def buscar_detalhe_escola(id_escola):
    """Busca o JSON detalhado de uma escola específica."""
    url = f"{BASE_URL}/relatorio/relatorio-gerencial/{id_escola}"
    headers = get_auth_headers()
    
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            return r.json()
        return None
    except:
        return None

def processar_json_para_linha(dado, id_escola, nome_escola):
    """Achata o JSON complexo para uma linha simples de Excel."""
    # O JSON pode vir direto ou dentro de 'data'
    obj = dado.get('data', dado) if isinstance(dado, dict) else dado
    
    # Proteção para campos nulos
    ue = obj.get('unidadeEscolar', {}) or {}
    prest = obj.get('prestadorServico', {}) or {}
    
    # Cálculos da equipe
    total_faltas = 0
    total_desc_equipe = 0.0
    equipe = obj.get('equipeAlocada', [])
    if equipe and isinstance(equipe, list):
        for func in equipe:
            total_faltas += (func.get('quantidadeAusente') or 0)
            val_desc = func.get('valorDesconto') or 0
            try: total_desc_equipe += float(val_desc)
            except: pass

    # Monta a linha
    return {
        "ID Sistema": id_escola,
        "Escola": nome_escola,
        "Código EOL": ue.get('codigo', ''),
        "Tipo": ue.get('tipo', ''),
        "Mês Ref": obj.get('mes', ''),
        "Ano Ref": obj.get('ano', ''),
        "Nota Final": obj.get('pontuacaoFinal', 0),
        "Valor Bruto": float(obj.get('valorBruto', 0) or 0),
        "Valor Líquido": float(obj.get('valorLiquido', 0) or 0),
        "Glosa RH": float(obj.get('descontoGlosaRh', 0) or 0),
        "Total Faltas Equipe": total_faltas,
        "Desc. Equipe (R$)": total_desc_equipe,
        "Status Fiscal": "Aprovado" if obj.get('flagAprovadoFiscal') else "Pendente",
        "Data Fiscal": obj.get('dataHoraAprovacaoFiscal', ''),
        "Quem Fiscal": obj.get('nomeUsuarioAprovacaoFiscal', ''),
        "Status DRE": "Aprovado" if obj.get('flagAprovadoDre') else "Pendente",
        "Quem DRE": obj.get('nomeUsuarioAprovacaoDre', '')
    }

# ==============================================================================
# 5. UI - INTERFACE
# ==============================================================================
st.title("📊 Extrator de Relatório Gerencial (Consolidado)")
st.markdown("Esta ferramenta varre todas as escolas cadastradas, extrai os detalhes financeiros e de equipe, e gera um Excel único.")

col1, col2 = st.columns([1, 4])

with col1:
    btn_iniciar = st.button("🚀 Iniciar Extração", type="primary", use_container_width=True)

if btn_iniciar:
    st.divider()
    
    # 1. Pega a lista
    with st.spinner("Conectando ao servidor e buscando lista de escolas..."):
        lista_escolas = buscar_lista_escolas()
    
    if not lista_escolas:
        st.error("Não foi possível obter a lista de escolas. Verifique se o token ainda é válido.")
        st.stop()
        
    total_escolas = len(lista_escolas)
    st.info(f"Lista obtida com sucesso! Encontradas **{total_escolas}** unidades.")
    
    # 2. Prepara barras de progresso
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    dados_consolidados = []
    
    # 3. Loop de Extração
    start_time = time.time()
    
    # Container para mostrar logs em tempo real (opcional, para não poluir)
    with st.expander("Ver logs de extração", expanded=True):
        log_area = st.empty()
        
    for i, item in enumerate(lista_escolas):
        # Normaliza ID e Nome
        u_id = item.get('id') or item.get('value')
        u_nome = item.get('descricao') or item.get('text') or "Sem Nome"
        
        if u_id:
            # Atualiza UI
            perc = (i + 1) / total_escolas
            progress_bar.progress(perc)
            status_text.text(f"Processando {i+1}/{total_escolas}: {u_nome}...")
            
            # Busca Detalhe
            detalhe = buscar_detalhe_escola(u_id)
            
            if detalhe:
                # O endpoint pode retornar lista (histórico) ou objeto único
                dados_raw = detalhe.get('data', detalhe)
                lista_processar = dados_raw if isinstance(dados_raw, list) else [dados_raw]
                
                for d in lista_processar:
                    linha = processar_json_para_linha(d, u_id, u_nome)
                    dados_consolidados.append(linha)
            else:
                log_area.warning(f"Falha ao baixar dados da unidade ID: {u_id}")
            
            # Sleep para não derrubar a API (Rate Limiting)
            time.sleep(0.1)
            
    # 4. Finalização
    tempo_total = time.time() - start_time
    progress_bar.progress(100)
    status_text.text("Concluído!")
    
    if dados_consolidados:
        df = pd.DataFrame(dados_consolidados)
        
        st.success(f"✅ Extração finalizada em {tempo_total:.1f}s! Total de registros: {len(df)}")
        
        # Preview
        st.dataframe(df.head(), use_container_width=True)
        
        # Download Excel
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='Consolidado')
            
            # Ajuste automático de colunas (opcional, visual)
            worksheet = writer.sheets['Consolidado']
            for idx, col in enumerate(df.columns):
                series = df[col]
                max_len = max((series.astype(str).map(len).max(), len(str(col)))) + 1
                worksheet.set_column(idx, idx, max_len)
                
        buffer.seek(0)
        
        st.download_button(
            label="📥 Baixar Excel Consolidado (.xlsx)",
            data=buffer,
            file_name=f"SME_Consolidado_{datetime.now().strftime('%Y-%m-%d_%H%M')}.xlsx",
            mime="application/vnd.ms-excel",
            type="primary"
        )
    else:
        st.warning("Nenhum dado foi extraído.")