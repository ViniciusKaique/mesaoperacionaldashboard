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
st.set_page_config(page_title="Extrator Blindado SME", layout="wide", page_icon="🛡️")

# ==============================================================================
# 2. SEGURANÇA
# ==============================================================================
if not st.session_state.get("authentication_status"):
    st.warning("🔒 Faça login na página inicial.")
    st.stop()

if not st.session_state.get('api_token'):
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
# 4. FUNÇÕES DE BUSCA (Core)
# ==============================================================================

def buscar_combo_escolas():
    """Busca a lista de escolas (Combo Todos) para ter os IDs de referência."""
    url = f"{BASE_URL}/unidade-escolar/combo-todos"
    try:
        r = requests.get(url, headers=get_headers(), timeout=20)
        if r.status_code == 200:
            return r.json()
    except:
        pass
    return []

def buscar_ids_relatorios(mes, ano, lista_escolas_combo):
    """
    Tenta buscar na tabela geral. Se falhar, busca escola por escola.
    """
    url_tabela = f"{BASE_URL}/relatorio/relatorio-gerencial/tabela"
    headers = get_headers()
    lista_final_ids = []
    
    # ---------------------------------------------------------
    # TENTATIVA 1: Busca Geral (Paginada)
    # ---------------------------------------------------------
    status_msg = st.empty()
    status_msg.text("Tentativa 1: Buscando tabela geral...")
    
    filtros_geral = json.dumps({"mes": int(mes), "ano": int(ano)})
    params = {"draw": "1", "filters": filtros_geral, "length": "100", "start": "0"}
    
    sucesso_geral = False
    try:
        r = requests.get(url_tabela, headers=headers, params=params, timeout=15)
        if r.status_code == 200:
            data = r.json()
            total = int(data.get('recordsTotal', 0) or data.get('recordsFiltered', 0))
            if total > 0:
                sucesso_geral = True
                # Se achou geral, faz a paginação normal aqui
                # (Simplificado: assumindo que pegou os primeiros 100, se precisar de mais, aumentaria o loop)
                for item in data.get('data', []):
                    if item.get('id'):
                        lista_final_ids.append({'id_relatorio': item.get('id'), 'nome': 'Via Geral'})
    except:
        pass

    if sucesso_geral:
        status_msg.success(f"✅ Tabela geral funcionou! {len(lista_final_ids)} relatórios encontrados.")
        return lista_final_ids

    # ---------------------------------------------------------
    # TENTATIVA 2: Busca Individual (Iterando o Combo)
    # ---------------------------------------------------------
    status_msg.warning("⚠️ Tabela geral vazia. Iniciando busca detalhada por escola (mais lento)...")
    
    if not lista_escolas_combo:
        status_msg.error("❌ Impossível prosseguir: Combo de escolas também falhou.")
        return []

    progress_bar = st.progress(0)
    total_escolas = len(lista_escolas_combo)
    
    for i, escola in enumerate(lista_escolas_combo):
        # Normaliza ID da escola
        id_escola = escola.get('id') or escola.get('value')
        nome_escola = escola.get('descricao') or escola.get('text') or "Escola"
        
        if id_escola:
            # Filtro Específico: Mes + Ano + ID da Escola
            filtros_ind = json.dumps({
                "mes": int(mes), 
                "ano": int(ano), 
                "unidadeEscolarId": int(id_escola)
            })
            
            params_ind = {"draw": "1", "filters": filtros_ind, "length": "10", "start": "0"}
            
            try:
                r_ind = requests.get(url_tabela, headers=headers, params=params_ind, timeout=10)
                if r_ind.status_code == 200:
                    d_ind = r_ind.json()
                    itens = d_ind.get('data', [])
                    if itens:
                        # Achou o relatório desta escola!
                        id_rel = itens[0].get('id') # Pega o ID do relatório
                        lista_final_ids.append({'id_relatorio': id_rel, 'nome': nome_escola})
            except:
                pass
        
        # Atualiza progresso visual
        if i % 5 == 0:
            perc = (i + 1) / total_escolas
            progress_bar.progress(perc)
            status_msg.text(f"Varrendo escola {i+1}/{total_escolas}: {nome_escola}")
            
        time.sleep(0.02) # Leve pause

    status_msg.empty()
    progress_bar.empty()
    return lista_final_ids

def buscar_detalhe(id_relatorio):
    url = f"{BASE_URL}/relatorio/relatorio-gerencial/{id_relatorio}"
    try:
        r = requests.get(url, headers=get_headers(), timeout=20)
        if r.status_code == 200: return r.json()
    except: pass
    return None

def processar_linha(dado_json, id_rel):
    dado = dado_json.get('data', dado_json)
    if isinstance(dado, list): dado = dado[0] if dado else {}
    if not isinstance(dado, dict): return None

    ue = dado.get('unidadeEscolar', {}) or {}
    
    # Cálculos
    faltas, desc_eq = 0, 0.0
    for f in dado.get('equipeAlocada', []) or []:
        faltas += (f.get('quantidadeAusente') or 0)
        try: desc_eq += float(f.get('valorDesconto') or 0)
        except: pass

    nota_insumos, nota_equipe = 0, 0
    for d in dado.get('detalhe', []) or []:
        desc = str(d.get('descricao', '')).lower()
        if 'insumo' in desc: nota_insumos = d.get('pontuacaoFinal', 0)
        if 'equipe' in desc: nota_equipe = d.get('pontuacaoFinal', 0)

    def fmt(v): 
        try: return f"{float(v):.2f}".replace('.', ',')
        except: return "0,00"

    return {
        "ID Relatório": id_rel,
        "Escola": ue.get('descricao'),
        "Código": ue.get('codigo'),
        "Mês": dado.get('mes'),
        "Nota Final": dado.get('pontuacaoFinal'),
        "Nota Equipe": nota_equipe,
        "Nota Insumos": nota_insumos,
        "Valor Líquido": fmt(dado.get('valorLiquido')),
        "Glosa RH": fmt(dado.get('descontoGlosaRh')),
        "Faltas": faltas,
        "Desc. Equipe": fmt(desc_eq),
        "Fiscal": dado.get('nomeUsuarioAprovacaoFiscal'),
        "Status": "Aprovado" if dado.get('flagAprovadoFiscal') else "Pendente"
    }

# ==============================================================================
# 5. UI
# ==============================================================================
st.title("🛡️ Extrator Blindado SME")
st.info("Estratégia: Busca Combo de Escolas -> Tenta Tabela Geral -> Se falhar, busca Escola por Escola.")

c1, c2, c3 = st.columns(3)
mes = c1.number_input("Mês", 1, 12, 12)
ano = c2.number_input("Ano", 2024, 2030, 2025)

if c3.button("🚀 Executar", type="primary", use_container_width=True):
    
    st.divider()
    
    # 1. Busca Combo (Lista Mestre)
    with st.spinner("Obtendo lista mestre de escolas (Combo)..."):
        combo_escolas = buscar_combo_escolas()
    
    st.write(f"🏫 Escolas na base (Combo): **{len(combo_escolas)}**")
    
    # 2. Busca IDs dos Relatórios (Híbrido)
    ids_relatorios = buscar_ids_relatorios(mes, ano, combo_escolas)
    
    if not ids_relatorios:
        st.error("❌ Não foi possível encontrar nenhum relatório, nem pela busca geral, nem por escola.")
        st.stop()
        
    st.success(f"📑 IDs de Relatórios encontrados: **{len(ids_relatorios)}**")
    
    # 3. Baixa Detalhes
    prog = st.progress(0)
    txt = st.empty()
    dados = []
    
    for i, item in enumerate(ids_relatorios):
        prog.progress((i+1)/len(ids_relatorios))
        txt.text(f"Extraindo detalhes: {item.get('nome', 'ID ' + str(item['id_relatorio']))}")
        
        raw = buscar_detalhe(item['id_relatorio'])
        if raw:
            l = processar_linha(raw, item['id_relatorio'])
            if l: dados.append(l)
        time.sleep(0.05)
        
    # 4. Excel
    if dados:
        df = pd.DataFrame(dados)
        st.dataframe(df.head(), use_container_width=True)
        
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False)
        
        st.download_button("📥 Baixar Excel", buffer, f"SME_{mes}_{ano}.xlsx", "application/vnd.ms-excel", type="primary")