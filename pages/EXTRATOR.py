import streamlit as st
import pandas as pd
import requests
import time
import io
import json
from datetime import datetime

# ==============================================================================
# 1. CONFIGURAÇÃO DA PÁGINA
# ==============================================================================
st.set_page_config(page_title="Extrator Massivo SME", layout="wide", page_icon="🚜")

# ==============================================================================
# 2. SEGURANÇA E ESTADO
# ==============================================================================
if not st.session_state.get("authentication_status"):
    st.warning("🔒 Acesso restrito. Faça login na página inicial.")
    st.stop()

if 'api_token' not in st.session_state or not st.session_state['api_token']:
    st.error("Token de autenticação não encontrado. Por favor, recarregue a página inicial e faça login novamente.")
    st.stop()

# ==============================================================================
# 3. CONFIGURAÇÃO API
# ==============================================================================
BASE_URL = "https://limpeza.sme.prefeitura.sp.gov.br/api/web"

HEADERS_TEMPLATE = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Origin": "https://limpeza.sme.prefeitura.sp.gov.br",
    "Referer": "https://limpeza.sme.prefeitura.sp.gov.br/relatorio/gerencial/",
    "sec-ch-ua": '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin"
}

def get_headers():
    h = HEADERS_TEMPLATE.copy()
    h["Authorization"] = f"Bearer {st.session_state['api_token']}"
    return h

# ==============================================================================
# 4. MOTOR DE EXTRAÇÃO (PAGINAÇÃO)
# ==============================================================================
def buscar_todos_ids_paginados(mes, ano):
    """
    Varre a tabela página por página para coletar TODOS os IDs.
    """
    url = f"{BASE_URL}/relatorio/relatorio-gerencial/tabela"
    headers = get_headers()
    
    lista_ids = []
    
    # Parâmetros iniciais
    start = 0
    length = 100 
    total_records = 1 
    draw = 1
    
    status_text = st.empty()
    debug_area = st.expander("🕵️ Diagnóstico da Requisição (Clique aqui se der erro)", expanded=False)
    
    while start < total_records:
        # 🚨 CORREÇÃO: Força mes e ano como INTEIROS
        filtros_json = json.dumps({"mes": int(mes), "ano": int(ano)})
        
        params = {
            "draw": str(draw),
            "filters": filtros_json,
            "length": str(length),
            "start": str(start)
        }
        
        try:
            status_text.text(f"🔄 Varrendo página {draw} (Registro {start} em diante)...")
            
            r = requests.get(url, headers=headers, params=params, timeout=20)
            
            if r.status_code == 200:
                data = r.json()
                
                # Atualiza o total de registros com a verdade da API
                total_records = int(data.get('recordsTotal', 0) or data.get('recordsFiltered', 0))
                
                # Debug na primeira chamada para garantir que o filtro funcionou
                if start == 0:
                    with debug_area:
                        st.write("📤 **Filtros Enviados:**", filtros_json)
                        st.write(f"📥 **Total Encontrado na API:** {total_records}")
                        if total_records == 0:
                            st.warning("A API retornou 0 registros. Verifique se há fechamento para este Mês/Ano.")

                itens = data.get('data', [])
                if not itens:
                    break 
                
                for item in itens:
                    u_id = item.get('id')
                    
                    # Tenta pegar o nome da escola
                    u_nome = "Desconhecido"
                    if isinstance(item.get('unidadeEscolar'), dict):
                        u_nome = item['unidadeEscolar'].get('descricao', 'Sem Nome')
                    elif 'unidadeEscolar' in item:
                        u_nome = str(item['unidadeEscolar'])
                    
                    if u_id:
                        lista_ids.append({'id': u_id, 'nome': u_nome})
                
                start += length
                draw += 1
                time.sleep(0.1) 
            else:
                st.error(f"Erro na paginação: {r.status_code} - {r.text}")
                break
                
        except Exception as e:
            st.error(f"Erro de conexão na listagem: {e}")
            break
    
    status_text.empty()
    return lista_ids

def buscar_detalhe_relatorio(id_relatorio):
    """Busca o JSON completo de um relatório específico."""
    url = f"{BASE_URL}/relatorio/relatorio-gerencial/{id_relatorio}"
    try:
        r = requests.get(url, headers=get_headers(), timeout=15)
        if r.status_code == 200:
            return r.json()
    except:
        pass
    return None

def processar_para_excel(dado_json, id_origem, nome_origem):
    """Transforma o JSON hierárquico em uma linha plana."""
    # O JSON detalhado pode vir dentro de uma chave 'data' ou direto
    dado = dado_json.get('data', dado_json)
    
    # Se for lista (histórico), pega o primeiro item
    if isinstance(dado, list):
        if not dado: return None
        dado = dado[0]
        
    if not isinstance(dado, dict): return None

    # Extrai sub-objetos com segurança
    ue = dado.get('unidadeEscolar', {}) or {}
    prestador = dado.get('prestadorServico', {}) or {}
    
    # Processa Equipe
    soma_faltas = 0
    soma_desc_equipe = 0.0
    lista_equipe = dado.get('equipeAlocada', [])
    
    if lista_equipe and isinstance(lista_equipe, list):
        for func in lista_equipe:
            soma_faltas += (func.get('quantidadeAusente') or 0)
            try: soma_desc_equipe += float(func.get('valorDesconto') or 0)
            except: pass

    # Notas específicas
    nota_insumos = 0
    nota_equipe = 0
    detalhes = dado.get('detalhe', [])
    if detalhes:
        for d in detalhes:
            desc = str(d.get('descricao', '')).lower()
            if 'insumo' in desc: nota_insumos = d.get('pontuacaoFinal', 0)
            if 'equipe' in desc or 'atividade' in desc: nota_equipe = d.get('pontuacaoFinal', 0)

    # Formatação Moeda
    def fmt_moeda(valor):
        try: return f"{float(valor):.2f}".replace('.', ',')
        except: return "0,00"

    return {
        "ID Relatório": id_origem,
        "Escola": nome_origem,
        "Código EOL": ue.get('codigo', ''),
        "Tipo Escola": ue.get('tipo', ''),
        "Mês": dado.get('mes', ''),
        "Ano": dado.get('ano', ''),
        "Nota Final": dado.get('pontuacaoFinal', 0),
        "Nota Equipe": nota_equipe,
        "Nota Insumos": nota_insumos,
        "Valor Bruto": fmt_moeda(dado.get('valorBruto', 0)),
        "Valor Líquido": fmt_moeda(dado.get('valorLiquido', 0)),
        "Glosa RH": fmt_moeda(dado.get('descontoGlosaRh', 0)),
        "Total Faltas": soma_faltas,
        "Desc. Equipe (R$)": fmt_moeda(soma_desc_equipe),
        "Status Fiscal": "Aprovado" if dado.get('flagAprovadoFiscal') else "Pendente",
        "Data Fiscal": dado.get('dataHoraAprovacaoFiscal', ''),
        "Nome Fiscal": dado.get('nomeUsuarioAprovacaoFiscal', ''),
        "Status DRE": "Aprovado" if dado.get('flagAprovadoDre') else "Pendente",
        "Prestador": prestador.get('razaoSocial', '')
    }

# ==============================================================================
# 5. INTERFACE DO USUÁRIO
# ==============================================================================
st.title("🚜 Extrator Massivo SME (Paginação)")
st.info("Este módulo percorre todas as páginas da tabela para garantir a extração completa.")

# Filtros
c1, c2, c3 = st.columns(3)
mes_sel = c1.number_input("Mês de Referência", min_value=1, max_value=12, value=12)
ano_sel = c2.number_input("Ano de Referência", min_value=2024, max_value=2030, value=2025)

if c3.button("🚀 Iniciar Extração Completa", type="primary", use_container_width=True):
    
    # 1. VARREDURA DE LISTA
    st.divider()
    with st.spinner(f"🔍 Varrendo todas as páginas para {mes_sel}/{ano_sel}..."):
        lista_final = buscar_todos_ids_paginados(mes_sel, ano_sel)
        
    total_encontrado = len(lista_final)
    
    if total_encontrado == 0:
        st.error("⚠️ Nenhum relatório encontrado. Verifique o 'Diagnóstico' acima para ver o erro.")
        st.stop()
        
    st.success(f"✅ Lista carregada! Encontrados **{total_encontrado}** relatórios para processar.")
    
    # 2. LOOP DE DETALHES
    progress_bar = st.progress(0)
    status_text = st.empty()
    dados_consolidados = []
    
    start_time = time.time()
    
    # Container para erros
    err_container = st.container()
    
    for i, item in enumerate(lista_final):
        # Atualiza barra
        perc = (i + 1) / total_encontrado
        progress_bar.progress(perc)
        status_text.text(f"Baixando detalhes ({i+1}/{total_encontrado}): {item['nome']}")
        
        # Request do detalhe
        json_detalhe = buscar_detalhe_relatorio(item['id'])
        
        if json_detalhe:
            linha = processar_para_excel(json_detalhe, item['id'], item['nome'])
            if linha:
                dados_consolidados.append(linha)
        else:
            err_container.error(f"Falha ao baixar ID: {item['id']}")
            
        # Pausa
        time.sleep(0.05)
        
    tempo_total = time.time() - start_time
    status_text.text("Concluído!")
    
    # 3. GERAÇÃO DO EXCEL
    if dados_consolidados:
        df = pd.DataFrame(dados_consolidados)
        
        st.balloons()
        st.success(f"🎉 Processamento finalizado em {tempo_total:.1f}s. {len(df)} registros gerados.")
        
        st.dataframe(df.head(), use_container_width=True)
        
        # Buffer Excel
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='Consolidado')
            worksheet = writer.sheets['Consolidado']
            worksheet.set_column(0, 20, 20) 
            
        st.download_button(
            label=f"📥 Baixar Planilha Consolidada ({mes_sel}_{ano_sel})",
            data=buffer,
            file_name=f"Relatorio_SME_{mes_sel}-{ano_sel}.xlsx",
            mime="application/vnd.ms-excel",
            type="primary",
            use_container_width=True
        )
    else:
        st.error("Erro grave: Lista de IDs foi carregada, mas nenhum detalhe pôde ser extraído.")