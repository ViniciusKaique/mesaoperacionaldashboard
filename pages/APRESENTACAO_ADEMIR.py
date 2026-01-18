import streamlit as st
import time
import requests
from streamlit_lottie import st_lottie

# ==============================================================================
# CONFIGURAÇÃO DA PÁGINA
# ==============================================================================
st.set_page_config(
    page_title="Projeto Blindagem", 
    layout="wide", 
    initial_sidebar_state="collapsed",
    page_icon="🛡️"
)

# ==============================================================================
# FUNÇÕES DE LOTTIE (ANIMAÇÕES)
# ==============================================================================
@st.cache_data
def load_lottieurl(url: str):
    r = requests.get(url)
    if r.status_code != 200:
        return None
    return r.json()

# URLs de animações Lottie (Tema Executivo/Tech)
LOTTIE_SHIELD = "https://lottie.host/8b725026-621f-4422-9207-68b365022567/H8e8R5q5Q5.json" # Escudo/Segurança
LOTTIE_ROCKET = "https://lottie.host/5b273574-6725-4652-943e-329065963953/2z8sQY8QY8.json" # Foguete/Performance
LOTTIE_MONEY = "https://lottie.host/29598282-3213-4352-8255-853285328532/M9e9R5q5Q5.json" # Dinheiro/Investimento (Simulado)
LOTTIE_TECH = "https://assets9.lottiefiles.com/packages/lf20_m9zragmd.json" # Tecnologia/Rede
LOTTIE_DASHBOARD = "https://assets5.lottiefiles.com/packages/lf20_qp1q7mct.json" # Dashboard/Analytcs

# Fallback se a URL falhar (carrega vazio)
lottie_shield = load_lottieurl("https://assets10.lottiefiles.com/packages/lf20_sfgpb58h.json") or {}
lottie_rocket = load_lottieurl("https://assets5.lottiefiles.com/packages/lf20_j1adxtyb.json") or {}
lottie_graph = load_lottieurl("https://assets3.lottiefiles.com/packages/lf20_qp1q7mct.json") or {}
lottie_money = load_lottieurl("https://assets8.lottiefiles.com/packages/lf20_money.json") or {}
lottie_team = load_lottieurl("https://assets5.lottiefiles.com/packages/lf20_5w2awox8.json") or {}

# ==============================================================================
# ESTILOS CSS (DARK MODE PREMIUM)
# ==============================================================================
st.markdown("""
<style>
    /* Fundo Global */
    .stApp {
        background-color: #0e1117;
        color: white;
    }
    
    /* Remover padding excessivo */
    .block-container {
        padding-top: 1rem;
        padding-bottom: 2rem;
    }

    /* Títulos Impactantes */
    .big-title {
        font-size: 3.5rem;
        font-weight: 800;
        text-transform: uppercase;
        background: linear-gradient(90deg, #ffffff, #94a3b8);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin: 0;
    }
    
    .section-header {
        font-size: 2.2rem;
        font-weight: 700;
        color: white;
        border-left: 6px solid #3b82f6;
        padding-left: 15px;
        margin-bottom: 30px;
    }

    /* Cards Estilizados */
    .card {
        background-color: #1e293b;
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 20px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
        transition: transform 0.2s;
    }
    .card:hover {
        transform: translateY(-3px);
        border-color: #3b82f6;
    }

    /* Botões de Navegação */
    .nav-btn {
        width: 100%;
        padding: 10px;
        font-weight: bold;
    }
    
    /* Métricas Customizadas */
    .metric-box {
        text-align: center;
        padding: 15px;
        background: #0f172a;
        border-radius: 10px;
        border: 1px solid #1e293b;
    }
    .metric-val { font-size: 2rem; font-weight: bold; color: #fff; }
    .metric-lbl { font-size: 0.9rem; color: #94a3b8; text-transform: uppercase; }
    
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# CONTROLE DE ESTADO (SLIDES)
# ==============================================================================
if 'slide' not in st.session_state:
    st.session_state.slide = 0

def next_slide(): 
    if st.session_state.slide < 7: st.session_state.slide += 1
def prev_slide(): 
    if st.session_state.slide > 0: st.session_state.slide -= 1
def reset_slide(): 
    st.session_state.slide = 0

# ==============================================================================
# SLIDES
# ==============================================================================

def slide_0_capa():
    c1, c2 = st.columns([1, 1])
    with c1:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.markdown("<h1 class='big-title'>MESA<br>OPERACIONAL</h1>", unsafe_allow_html=True)
        st.markdown("<h2 style='color: #3b82f6;'>BLINDAGEM DE CONTRATO</h2>", unsafe_allow_html=True)
        st.markdown("---")
        st.markdown("### 🛡️ De Reativo (Apaga Incêndio) ➔ **Preditivo (Evita o Fogo)**")
        st.markdown("<br>", unsafe_allow_html=True)
        st.info("Uma nova era de **Inteligência Estratégica** na Soluções.")
    
    with c2:
        st_lottie(lottie_shield, height=400, key="shield")

def slide_1_piloto():
    st.markdown("<div class='section-header'>QUEM É O PILOTO?</div>", unsafe_allow_html=True)
    
    c1, c2 = st.columns([1, 2])
    with c1:
        st.markdown("""
        <div class='card' style='text-align: center;'>
            <h1 style='margin:0;'>👨‍💻</h1>
            <h2 style='color:white;'>VINICIUS</h2>
            <p style='color:#3b82f6; font-weight:bold;'>ESPECIALISTA EM INTELIGÊNCIA</p>
            <hr style='border-color: #334155;'>
            <div style='text-align: left; color: #cbd5e1; line-height: 1.8;'>
                ✅ Tecnologia & Dados<br>
                ✅ Otimização de Processos<br>
                ✅ Visão de Lucro
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    with c2:
        st.markdown("### 🤝 O Convite Estratégico")
        st.markdown("""
        Fui convocado pelo **Sr. Aparício** com uma missão clara: **Resolver a falta de controle.**
        
        Ele confiou na minha capacidade de unir **Operação e Tecnologia** para mudar o modelo mental da empresa.
        """)
        
        st.warning("Diagnóstico Inicial: 'Uma operação forte, mas sem painel de controle.'")
        st_lottie(lottie_graph, height=250, key="graph")

def slide_2_skin():
    st.markdown("<div class='section-header' style='border-color: #ef4444;'>SKIN IN THE GAME (MEU RISCO)</div>", unsafe_allow_html=True)
    
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("### 📉 O Investimento Mensal")
        st.markdown("""
        Eu apostei meu próprio dinheiro neste projeto. Aceitei entrar ganhando **menos da metade** para provar o valor.
        
        * **Valor Ideal:** R$ 8.000,00
        * **Atual:** <span style='color: #ef4444; font-weight:bold;'>R$ 3.700,00</span>
        """, unsafe_allow_html=True)
        
        st.markdown("""
        <div class='metric-box' style='border-color: #ef4444;'>
            <div class='metric-val' style='color: #ef4444;'>- R$ 4.300/mês</div>
            <div class='metric-lbl'>Meu 'Gap' de Aposta</div>
        </div>
        """, unsafe_allow_html=True)

    with c2:
        st.markdown("### 🎯 Por que fiz isso?")
        st.write("Porque eu não vim buscar um emprego. Vim construir um **Case de Sucesso**.")
        st_lottie(lottie_rocket, height=300, key="rocket_skin")

def slide_3_tech():
    st.markdown("<div class='section-header' style='border-color: #8b5cf6;'>TECNOLOGIA PRÓPRIA (ATIVO)</div>", unsafe_allow_html=True)
    
    c1, c2 = st.columns([2, 1])
    with c1:
        st.markdown("### 💻 Código Proprietário")
        st.write("Não contratei software caro. **Eu desenvolvi a ferramenta.** Isso é patrimônio da empresa.")
        
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            st.markdown("<div class='card'>🚀 <b>Escalável</b><br><small>Roda em 1 ou 100 contratos sem custo extra.</small></div>", unsafe_allow_html=True)
        with col_b:
            st.markdown("<div class='card'>🔧 <b>Personalizável</b><br><small>Adapta-se à regra de cada cliente.</small></div>", unsafe_allow_html=True)
        with col_c:
            st.markdown("<div class='card'>📦 <b>Produto</b><br><small>Pode ser vendido no mercado futuro.</small></div>", unsafe_allow_html=True)

    with c2:
        st_lottie(lottie_team, height=250, key="tech_anim")

def slide_4_ecosystem():
    st.markdown("<div class='section-header' style='border-color: #10b981;'>O ECOSSISTEMA (MÓDULOS)</div>", unsafe_allow_html=True)
    st.caption("Piloto Rodando no CONAE")
    
    c1, c2, c3, c4, c5 = st.columns(5)
    
    modulos = [
        ("📍 Visão Vagas", "Monitoramento real-time de onde está cada um."),
        ("💰 Receita", "Blindagem contra Glosas e SME."),
        ("📱 Ponto", "Cobrança automática via WhatsApp."),
        ("⚡ Apuração", "Correção preventiva de erros de pagto."),
        ("🚙 Volantes", "Envio imediato de cobertura.")
    ]
    
    cols = [c1, c2, c3, c4, c5]
    for i, (tit, desc) in enumerate(modulos):
        with cols[i]:
            st.markdown(f"""
            <div class='card' style='height: 200px;'>
                <h4 style='color: #3b82f6;'>{tit}</h4>
                <p style='font-size: 0.85rem; color: #94a3b8;'>{desc}</p>
            </div>
            """, unsafe_allow_html=True)

def slide_5_objetivos():
    st.markdown("<div class='section-header' style='border-color: #f59e0b;'>OBJETIVOS CLAROS</div>", unsafe_allow_html=True)
    
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("<div class='metric-box'><div class='metric-val'>100%</div><div class='metric-lbl'>Cobertura Contrato</div></div>", unsafe_allow_html=True)
        st.caption("Cargos corretos, sem postos vagos.")
    with c2:
        st.markdown("<div class='metric-box'><div class='metric-val' style='color:#10b981'>-70%</div><div class='metric-lbl'>Redução Glosas</div></div>", unsafe_allow_html=True)
        st.caption("Dinheiro que para de sair do caixa.")
    with c3:
        st.markdown("<div class='metric-box'><div class='metric-val'>90%+</div><div class='metric-lbl'>Precisão Ponto</div></div>", unsafe_allow_html=True)
        st.caption("Fim dos processos trabalhistas e rotatividade.")

def slide_6_roadmap():
    st.markdown("<div class='section-header'>ROADMAP & EQUIPE</div>", unsafe_allow_html=True)
    
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("### 📅 Cronograma")
        st.success("**Meses 1-2 (AGORA):** Implementação total no CONAE.")
        st.info("**Meses 3-6:** Expansão para todos os contratos de Facilities.")
        st.secondary("**Meses 12+:** Ferramentas para todos os setores.")
        
    with c2:
        st.markdown("### 👥 A Equipe")
        st.markdown("""
        <div class='card'>
            <p style='font-size: 1.1rem;'>
            Não fazemos nada sozinhos. A liderança do <b>Sr. Aparício</b> e o engajamento da equipe são vitais.
            <br><br>
            <i>"Eles não tinham ferramentas. Agora eles têm um arsenal."</i>
            </p>
        </div>
        """, unsafe_allow_html=True)

def slide_7_proposta():
    st.markdown("<div class='section-header' style='border-color: #10b981;'>A PROPOSTA</div>", unsafe_allow_html=True)
    
    c1, c2 = st.columns([1.5, 1])
    
    with c1:
        st.markdown("""
        <div class='card' style='background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%); border: 2px solid #10b981;'>
            <div style='display: flex; justify-content: space-around; text-align: center; align-items: center;'>
                <div>
                    <p style='color: #94a3b8; font-size: 0.9rem; font-weight: bold;'>SALÁRIO FIXO</p>
                    <h1 style='color: white; font-size: 3rem; margin: 0;'>R$ 8.000</h1>
                    <p style='color: #64748b; font-size: 0.8rem;'>Gestão & Tecnologia</p>
                </div>
                <div style='font-size: 2rem; color: #475569;'>+</div>
                <div>
                    <p style='color: #10b981; font-size: 0.9rem; font-weight: bold;'>BÔNUS TRIMESTRAL</p>
                    <h1 style='color: white; font-size: 2.5rem; margin: 0;'>VARIÁVEL</h1>
                    <p style='color: #64748b; font-size: 0.8rem;'>Por "Contrato Blindado"</p>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown("<br>", unsafe_allow_html=True)
        st.info("💡 **Conceito:** É um investimento, não um custo. O dinheiro 'novo' (economia de glosa) paga o bônus.")

    with c2:
        st_lottie(lottie_money, height=250, key="money")
        st.markdown("<div style='text-align: center; font-style: italic; color: #94a3b8;'>'Vim para solucionar. Se não tiver solução, eu crio.'</div>", unsafe_allow_html=True)

# ==============================================================================
# RENDERIZAÇÃO
# ==============================================================================

# Barra de Progresso
progress = (st.session_state.slide + 1) / 8
st.progress(progress)

# Renderiza Slide Atual
if st.session_state.slide == 0: slide_0_capa()
elif st.session_state.slide == 1: slide_1_piloto()
elif st.session_state.slide == 2: slide_2_skin()
elif st.session_state.slide == 3: slide_3_tech()
elif st.session_state.slide == 4: slide_4_ecosystem()
elif st.session_state.slide == 5: slide_5_objetivos()
elif st.session_state.slide == 6: slide_6_roadmap()
elif st.session_state.slide == 7: slide_7_proposta()

# Rodapé de Navegação
st.markdown("---")
c_prev, c_stat, c_next = st.columns([1, 4, 1])

with c_prev:
    if st.session_state.slide > 0:
        if st.button("⬅️ Anterior", use_container_width=True):
            prev_slide()
            st.rerun()

with c_next:
    if st.session_state.slide < 7:
        if st.button("Próximo ➡️", type="primary", use_container_width=True):
            next_slide()
            st.rerun()
    else:
        if st.button("🔄 Reiniciar", use_container_width=True):
            reset_slide()
            st.rerun()
