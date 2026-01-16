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
    st.error("Token não encontrado. Recarregue a Home.")
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
def buscar_ids_via_tabela(mes, ano):
    """
    Varre a API de tabela paginada para pegar TODOS os IDs.
    """
    url = f"{BASE_URL}/relatorio/relatorio-gerencial/tabela"
    headers = get_headers()
    
    lista_final = []
    start = 0
    length = 100 # Tenta pegar 100 por vez para ser mais rápido
    total_registros = 1 # Valor dummy para iniciar o loop
    
    status_msg = st.empty()
    
    while start < total_registros:
        # Filtro obrigatório para a tabela funcionar
        filtros = json.dumps({"mes": str(mes), "ano": int(ano)})
        
        params = {
            "draw": "1",
            "filters": filtros,
            "length": length,
            "start": start
        }
        
        try:
            status_msg.text(f"🔄 Buscando página (Start: {start})...")
            r = requests.get(url, headers=headers, params=params, timeout=20)
            
            if r.status_code == 200:
                data = r.json()
                
                # O formato do DataTables geralmente retorna 'data' e 'recordsTotal'
                registros = data.get('data', [])
                total_registros = int(data.get('recordsTotal', 0) or data.get('recordsFiltered', 0))
                
                if not registros:
                    break
                    
                for item in registros:
                    # Precisamos extrair o ID para buscar o detalhe depois.
                    # O item geralmente vem com a estrutura da linha da tabela.
                    # Vamos tentar pegar 'id' ou 'unidadeEscolar.id'
                    u_id = item.get('id')
                    
                    # Nome da escola (pode estar aninhado)
                    nome_escola = "Desconhecido"
                    if 'unidadeEscolar' in item and isinstance(item['unidadeEscolar'], dict):
                        nome_escola = item['unidadeEscolar'].get('descricao', 'Sem Nome')
                    elif 'unidadeEscolar' in item:
                        nome_escola = str(item['unidadeEscolar'])
                    
                    if u_id:
                        lista_final.append({'id': u_id, 'nome': nome_escola})
                
                start += length
                time.sleep(0.1) # Evita block
            else:
                st.error(f"Erro {r.status_code} na paginação.")
                break
        except Exception as e:
            st.error(f"Erro na varredura: {e}")
            break
            
    status_msg.empty()
    return lista_final

def buscar_detalhe(id_relatorio):
    """Busca o JSON completo de detalhe (equipe, valores, etc)."""
    url = f"{BASE_URL}/relatorio/relatorio-gerencial/{id_relatorio}"
    try:
        r = requests.get(url, headers=get_headers(), timeout=15)
        if r.status_code == 200:
            return r.json()
    except:
        pass
    return None

def achatar_dados(json_detalhe, id_origem, nome_origem):
    """Transforma o JSON complexo em linha de Excel."""
    dado = json_detalhe.get('data', json_detalhe)
    if not dado: return None
    
    # Se retornar lista (histórico), pega o primeiro ou processa todos (aqui assume 1 por ID)
    if isinstance(dado, list): dado = dado[0]
    
    ue = dado.get('unidadeEscolar', {}) or {}
    prest = dado.get('prestadorServico', {}) or {}
    
    # Soma equipe
    faltas = 0
    desc_eq = 0.0
    equipe = dado.get('equipeAlocada', [])
    if equipe:
        for f in equipe:
            faltas += (f.get('quantidadeAusente') or 0)
            try: desc_eq += float(f.get('valorDesconto') or 0)
            except: pass

    # Tenta pegar notas
    nota_insumos = 0
    nota_equipe = 0
    detalhes_notas = dado.get('detalhe', [])
    if detalhes_notas:
        for d in detalhes_notas:
            desc = str(d.get('descricao', '')).lower()
            if 'insumo' in desc: nota_insumos = d.get('pontuacaoFinal', 0)
            if 'equipe' in desc: nota_equipe = d.get('pontuacaoFinal', 0)

    return {
        "ID Relatório": id_origem,
        "Escola": nome_origem,
        "Cod EOL": ue.get('codigo', ''),
        "Mês": dado.get('mes'),
        "Ano": dado.get('ano'),
        "Pontuação Final": dado.get('pontuacaoFinal'),
        "Nota Equipe": nota_equipe,
        "Nota Insumos": nota_insumos,
        "Valor Bruto": f"{float(dado.get('valorBruto') or 0):.2f}".replace('.',','),
        "Valor Líquido": f"{float(dado.get('valorLiquido') or 0):.2f}".replace('.',','),
        "Glosa RH": f"{float(dado.get('descontoGlosaRh') or 0):.2f}".replace('.',','),
        "Total Faltas": faltas,
        "Desc. Equipe R$": f"{desc_eq:.2f}".replace('.',','),
        "Status Fiscal": "Aprovado" if dado.get('flagAprovadoFiscal') else "Pendente",
        "Data Fiscal": dado.get('dataHoraAprovacaoFiscal'),
        "Fiscal": dado.get('nomeUsuarioAprovacaoFiscal'),
        "Status DRE": "Aprovado" if dado.get('flagAprovadoDre') else "Pendente",
        "Prestador": prest.get('razaoSocial')
    }

# ==============================================================================
# 5. INTERFACE
# ==============================================================================
st.title("🚜 Extrator Massivo SME (Paginação Automática)")
st.info("Este extrator percorre todas as páginas da tabela para garantir que as 146 escolas sejam encontradas.")

c1, c2, c3 = st.columns(3)
mes_sel = c1.number_input("Mês de Referência", min_value=1, max_value=12, value=12)
ano_sel = c2.number_input("Ano de Referência", min_value=2024, max_value=2030, value=2025)

if c3.button("🚀 Iniciar Varredura Completa", type="primary", use_container_width=True):
    
    # 1. VARREDURA (Paginação)
    with st.status("🔍 Varrendo tabela paginada...", expanded=True) as status:
        st.write("Conectando à API de Tabela...")
        lista_escolas = buscar_ids_via_tabela(mes_sel, ano_sel)
        
        total = len(lista_escolas)
        if total == 0:
            status.update(label="❌ Nenhuma escola encontrada!", state="error")
            st.stop()
        
        status.update(label=f"✅ Sucesso! {total} relatórios encontrados para {mes_sel}/{ano_sel}.", state="complete")
    
    st.divider()
    
    # 2. EXTRAÇÃO DETALHADA
    st.write(f"📥 Baixando detalhes de **{total}** unidades...")
    progress = st.progress(0)
    bar_text = st.empty()
    
    dados_consolidados = []
    
    start_time = time.time()
    
    for i, item in enumerate(lista_escolas):
        perc = (i + 1) / total
        progress.progress(perc)
        bar_text.text(f"({i+1}/{total}) Extraindo: {item['nome']}")
        
        detalhe = buscar_detalhe(item['id'])
        
        if detalhe:
            linha = achatar_dados(detalhe, item['id'], item['nome'])
            if linha: dados_consolidados.append(linha)
        
        # Pausa mínima para não travar
        time.sleep(0.05)
    
    tempo = time.time() - start_time
    bar_text.text("Processamento finalizado!")
    
    # 3. EXCEL
    if dados_consolidados:
        df = pd.DataFrame(dados_consolidados)
        st.success(f"🎉 Extração concluída em {tempo:.1f}s. Registros processados: {len(df)}")
        st.dataframe(df.head(), use_container_width=True)
        
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='Base_SME')
            worksheet = writer.sheets['Base_SME']
            worksheet.set_column(0, 20, 18) # Ajuste largura colunas
            
        st.download_button(
            label=f"💾 Baixar Relatório Completo ({mes_sel}_{ano_sel}).xlsx",
            data=buffer,
            file_name=f"SME_Geral_{mes_sel}-{ano_sel}.xlsx",
            mime="application/vnd.ms-excel",
            type="primary",
            use_container_width=True
        )
    else:
        st.error("Houve erros na extração dos detalhes. Tente novamente.")