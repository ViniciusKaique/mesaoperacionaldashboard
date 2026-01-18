import streamlit as st
from PIL import Image
import time

# ==============================================================================
# CONFIGURAÇÃO DA PÁGINA (MODO APRESENTAÇÃO)
# ==============================================================================
st.set_page_config(
    page_title="Projeto Blindagem", 
    layout="wide", 
    initial_sidebar_state="collapsed", # Esconde a barra lateral para focar
    page_icon="🛡️"
)

# ==============================================================================
# ESTILOS CSS (DARK MODE PREMIUM - FERRARI)
# ==============================================================================
st.markdown("""
<style>
    /* Remove padding padrão para tela cheia */
    .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
        padding-left: 3rem;
        padding-right: 3rem;
        max-width: 100%;
    }
    
    /* Fundo Escuro Global */
    .stApp {
        background-color: #0e1117;
        color: white;
    }

    /* Títulos Grandes */
    .big-title {
        font-size: 4rem;
        font-weight: 800;
        text-transform: uppercase;
        background: -webkit-linear-gradient(45deg, #ffffff, #a0a0a0);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.5rem;
    }
    
    .subtitle {
        font-size: 1.8rem;
        color: #64748b;
        font-weight: 300;
        letter-spacing: 2px;
        text-transform: uppercase;
    }

    /* Cards Estilizados */
    .card-box {
        background-color: #1e293b;
        border: 1px solid #334155;
        border-radius: 15px;
        padding: 25px;
        transition: transform 0.3s ease;
    }
    .card-box:hover {
        transform: translateY(-5px);
        border-color: #3b82f6;
        box-shadow: 0 10px 15px -3px rgba(59, 130, 246, 0.2);
    }

    /* Destaques de Texto */
    .highlight-blue { color: #3b82f6; font-weight: bold; }
    .highlight-red { color: #ef4444; font-weight: bold; }
    .highlight-green { color: #10b981; font-weight: bold; }
    
    /* Botões Customizados */
    div.stButton > button {
        background: linear-gradient(90deg, #1e40af 0%, #3b82f6 100%);
        color: white;
        border: none;
        padding: 10px 24px;
        border-radius: 8px;
        font-weight: bold;
        font-size: 16px;
        transition: all 0.3s;
        width: 100%;
    }
    div.stButton > button:hover {
        box-shadow: 0 0 15px rgba(59, 130, 246, 0.6);
        transform: scale(1.02);
    }
    
    /* Esconder elementos padrões do Streamlit */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# ESTADO DA APRESENTAÇÃO
# ==============================================================================
if 'slide_index' not in st.session_state:
    st.session_state.slide_index = 0

def next_slide():
    st.session_state.slide_index += 1

def prev_slide():
    if st.session_state.slide_index > 0:
        st.session_state.slide_index -= 1

def reset_slide():
    st.session_state.slide_index = 0

# ==============================================================================
# CONTEÚDO DOS SLIDES
# ==============================================================================

# --- SLIDE 0: CAPA ---
def render_capa():
    st.markdown("<br><br>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 6, 1])
    with c2:
        st.markdown("<div style='text-align: center;'>", unsafe_allow_html=True)
        st.image("https://img.icons8.com/ios-filled/100/3b82f6/shield.png", width=100) # Ícone escudo placeholder
        st.markdown("<h1 class='big-title'>BLINDAGEM DE CONTRATO</h1>", unsafe_allow_html=True)
        st.markdown("<p class='subtitle'>MESA OPERACIONAL | INTELIGÊNCIA ESTRATÉGICA</p>", unsafe_allow_html=True)
        st.markdown("<br><hr style='border-color: #334155'><br>", unsafe_allow_html=True)
        st.markdown("<h3 style='color: #94a3b8'>De: <span class='highlight-red'>Reativo</span> (Apaga Incêndio) ➔ Para: <span class='highlight-green'>Preditivo</span> (Evita o Fogo)</h3>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

# --- SLIDE 1: O PILOTO ---
def render_piloto():
    st.markdown("<h2 style='color: white; border-left: 5px solid #3b82f6; padding-left: 15px;'>QUEM É O PILOTO?</h2>", unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)
    
    c1, c2 = st.columns([1, 2])
    
    with c1:
        st.markdown("""
        <div class='card-box' style='text-align: center;'>
            <h2 style='color: white; margin: 0;'>VINICIUS</h2>
            <p style='color: #3b82f6; font-size: 0.9rem; letter-spacing: 1px; margin-top: 5px;'>ESPECIALISTA EM INTELIGÊNCIA OPERACIONAL</p>
            <hr style='border-color: #334155; margin: 20px 0;'>
            <div style='text-align: left; color: #cbd5e1; font-size: 1rem; line-height: 2;'>
                ✔️ Tecnologia & Dados<br>
                ✔️ Otimização de Processos<br>
                ✔️ Visão de Lucro
            </div>
        </div>
        """, unsafe_allow_html=True)
        
    with c2:
        st.info("📢 **O Convite Estratégico**")
        st.markdown("""
        <div style='font-size: 1.2rem; line-height: 1.6; color: #e2e8f0;'>
        Fui convocado pelo <b>Sr. Aparício</b> para resolver a falta de controle. Ele confiou na minha capacidade de unir <span class='highlight-blue'>Operação e Tecnologia</span>.
        <br><br>
        <b>O Meu Papel:</b><br>
        Organizar os contratos com sistemas proprietários, robôs e inteligência.
        <br><br>
        <i>"Encontrei uma operação sem painel de controle. Hoje, estamos construindo o cockpit."</i>
        </div>
        """, unsafe_allow_html=True)

# --- SLIDE 2: SKIN IN THE GAME ---
def render_skin():
    st.markdown("<h2 style='color: white; border-left: 5px solid #ef4444; padding-left: 15px;'>SKIN IN THE GAME (MEU RISCO)</h2>", unsafe_allow_html=True)
    st.markdown("<p style='font-size: 1.2rem; color: #94a3b8;'>Eu apostei meu próprio dinheiro neste projeto.</p>", unsafe_allow_html=True)
    
    c1, c2 = st.columns(2)
    
    with c1:
        st.markdown("""
        <div class='card-box'>
            <h3 style='color: #94a3b8; font-size: 1rem;'>VALOR DE MERCADO (IDEAL)</h3>
            <div style='background-color: #334155; width: 100%; height: 20px; border-radius: 5px; margin-bottom: 5px;'></div>
            <h1 style='color: white; margin: 0;'>R$ 8.000,00</h1>
            <br>
            <h3 style='color: #3b82f6; font-size: 1rem;'>ATUAL (SOLUÇÕES)</h3>
            <div style='background-color: #1e40af; width: 45%; height: 20px; border-radius: 5px; margin-bottom: 5px;'></div>
            <h1 style='color: #60a5fa; margin: 0;'>R$ 3.700,00</h1>
        </div>
        """, unsafe_allow_html=True)
        
    with c2:
        st.markdown("<br>", unsafe_allow_html=True)
        st.error("📉 **GAP DE INVESTIMENTO: R$ 4.300,00 / Mês**")
        st.markdown("""
        <div style='font-size: 1.1rem; color: #e2e8f0; margin-top: 20px;'>
        Aceitei receber menos da metade para provar o valor.
        <br><br>
        <b>Eu comprei o risco do projeto.</b> Agora que a "Máquina" está ligada, preciso de combustível para acelerar e entregar o lucro que a empresa merece.
        </div>
        """, unsafe_allow_html=True)

# --- SLIDE 3: TECNOLOGIA PRÓPRIA ---
def render_tech():
    st.markdown("<h2 style='color: white; border-left: 5px solid #8b5cf6; padding-left: 15px;'>TECNOLOGIA PRÓPRIA (ATIVO)</h2>", unsafe_allow_html=True)
    
    c1, c2 = st.columns([2, 1])
    with c1:
        st.markdown("""
        <div style='font-size: 1.3rem; color: #e2e8f0;'>
        Não contratei software de prateleira caro. <b>Eu desenvolvi o código.</b>
        <br>Isso significa que estamos criando um <span style='color: #a78bfa; font-weight: bold;'>Patrimônio Intelectual</span> para a empresa.
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("""
        <div class='card-box'>
            <h3 style='color: #a78bfa;'>🚀 Escalável</h3>
            <p style='color: #cbd5e1; font-size: 0.9rem;'>Hoje no CONAE. Amanhã em 100 contratos sem custo extra de licença.</p>
        </div>""", unsafe_allow_html=True)
    with col2:
        st.markdown("""
        <div class='card-box'>
            <h3 style='color: #a78bfa;'>🔧 Personalizável</h3>
            <p style='color: #cbd5e1; font-size: 0.9rem;'>Cada contrato tem sua regra. Meu sistema se adapta, não o contrário.</p>
        </div>""", unsafe_allow_html=True)
    with col3:
        st.markdown("""
        <div class='card-box'>
            <h3 style='color: #a78bfa;'>📦 Produto</h3>
            <p style='color: #cbd5e1; font-size: 0.9rem;'>Nível profissional. Pode virar um produto de mercado futuramente.</p>
        </div>""", unsafe_allow_html=True)

# --- SLIDE 4: ECOSSISTEMA ---
def render_ecossistema():
    st.markdown("<h2 style='color: white; border-left: 5px solid #10b981; padding-left: 15px;'>O ECOSSISTEMA (MÓDULOS)</h2>", unsafe_allow_html=True)
    st.caption("Piloto Rodando no CONAE")
    
    modulos = [
        ("📍 1. Visão de Vagas", "Sabemos exatamente a situação de cada posto. Ajustes de contratação, demissão e cargos em tempo real.", "#3b82f6"),
        ("💰 2. Garantia de Receita", "Monitoramos Glosas e SME. Foco na qualidade de resposta e recurso de glosas.", "#10b981"),
        ("📱 3. Monitor Ponto", "Disparos automáticos de WhatsApp para supervisores. Cobrança ativa de batidas.", "#f59e0b"),
        ("⚡ 4. Diagnóstico Apuração", "Correção preventiva de erros de pagamento. Fim do passivo trabalhista surpresa.", "#ef4444"),
        ("🚙 5. Gestão Volantes", "Envio imediato de cobertura para faltas detectadas pelo sistema.", "#8b5cf6")
    ]
    
    for titulo, desc, cor in modulos:
        st.markdown(f"""
        <div class='card-box' style='border-left: 5px solid {cor}; margin-bottom: 10px;'>
            <h3 style='margin:0; color: white;'>{titulo}</h3>
            <p style='margin:5px 0 0 0; color: #cbd5e1;'>{desc}</p>
        </div>
        """, unsafe_allow_html=True)

# --- SLIDE 5: OBJETIVOS ---
def render_objetivos():
    st.markdown("<h2 style='color: white; border-left: 5px solid #f59e0b; padding-left: 15px;'>OBJETIVOS CLAROS</h2>", unsafe_allow_html=True)
    
    c1, c2, c3 = st.columns(3)
    
    with c1:
        st.metric(label="Cobertura Contrato", value="100%", delta="Visão Total")
        st.markdown("<p style='font-size: 0.9rem; color: #94a3b8'>Cargos corretos, sem postos vagos.</p>", unsafe_allow_html=True)
        
    with c2:
        st.metric(label="Redução Glosas (RH)", value="-70%", delta="Economia", delta_color="inverse")
        st.markdown("<p style='font-size: 0.9rem; color: #94a3b8'>Dinheiro que para de sair do caixa.</p>", unsafe_allow_html=True)
        
    with c3:
        st.metric(label="Precisão Ponto", value="90%+", delta="Confiabilidade")
        st.markdown("<p style='font-size: 0.9rem; color: #94a3b8'>Fim dos processos trabalhistas por erro de pagamento.</p>", unsafe_allow_html=True)

# --- SLIDE 6: ROADMAP & EQUIPE ---
def render_roadmap():
    c1, c2 = st.columns(2)
    
    with c1:
        st.markdown("<h3 style='color: #3b82f6;'>📅 Roadmap (Cronograma)</h3>", unsafe_allow_html=True)
        st.markdown("""
        <div style='border-left: 2px solid #334155; padding-left: 20px; margin-left: 10px;'>
            <p style='color: white; font-weight: bold;'>🔹 Meses 1-2 (AGORA)</p>
            <p style='color: #94a3b8; font-size: 0.9rem;'>Implementação total no CONAE. Resultados concretos e auditáveis.</p>
            <br>
            <p style='color: white; font-weight: bold;'>🔹 Meses 3+</p>
            <p style='color: #94a3b8; font-size: 0.9rem;'>Adaptação para cada contrato da empresa. <i>"Cada contrato tem sua peculiaridade, cada um terá sua blindagem."</i></p>
        </div>
        """, unsafe_allow_html=True)
        
    with c2:
        st.markdown("<h3 style='color: #10b981;'>👥 A Equipe</h3>", unsafe_allow_html=True)
        st.markdown("""
        <div class='card-box'>
            <p style='color: #e2e8f0; font-size: 1.1rem;'>
            Não fazemos nada sozinhos. A liderança do <b>Sr. Aparício</b> e o engajamento da equipe operacional são vitais.
            <br><br>
            <i>"Eles não tinham ferramentas. Agora eles têm um arsenal."</i>
            </p>
        </div>
        """, unsafe_allow_html=True)

# --- SLIDE 7: PROPOSTA ---
def render_proposta():
    st.markdown("<h2 style='color: white; border-left: 5px solid #10b981; padding-left: 15px;'>A PROPOSTA</h2>", unsafe_allow_html=True)
    st.markdown("<p style='font-size: 1.2rem; color: #94a3b8;'>Vou entregar indicadores reais. Chega de obstáculos, vim para solucionar.</p>", unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    st.markdown("""
    <div style='background: linear-gradient(180deg, #0f172a 0%, #1e293b 100%); border: 1px solid #334155; border-radius: 20px; padding: 40px;'>
        <div style='display: flex; justify-content: space-around; align-items: center; flex-wrap: wrap;'>
            <div style='text-align: center;'>
                <p style='color: #94a3b8; font-weight: bold; letter-spacing: 1px;'>SALÁRIO FIXO</p>
                <h1 style='font-size: 3.5rem; margin: 0; color: white;'>R$ 8.000</h1>
                <p style='color: #64748b;'>Pela Gestão e Tecnologia</p>
            </div>
            <div style='font-size: 3rem; color: #475569;'>+</div>
            <div style='text-align: center;'>
                <p style='color: #10b981; font-weight: bold; letter-spacing: 1px;'>BÔNUS TRIMESTRAL</p>
                <h1 style='font-size: 2.5rem; margin: 0; color: white;'>VARIÁVEL</h1>
                <p style='color: #64748b;'>Por "Contrato Blindado"</p>
            </div>
        </div>
        <hr style='border-color: #334155; margin: 30px 0;'>
        <p style='text-align: center; font-size: 1.1rem; color: #e2e8f0; font-style: italic;'>
        "Se eu não gerar economia, não recebo o bônus. Se não der resultado, pode me cobrar. <br>
        <span style='color: #10b981; font-weight: bold;'>O risco é meu.</span>"
        </p>
    </div>
    """, unsafe_allow_html=True)

# ==============================================================================
# NAVEGAÇÃO E RENDERIZAÇÃO
# ==============================================================================

# Barra de Progresso
progress = (st.session_state.slide_index + 1) / 8
st.progress(progress)

# Renderiza o slide atual
if st.session_state.slide_index == 0: render_capa()
elif st.session_state.slide_index == 1: render_piloto()
elif st.session_state.slide_index == 2: render_skin()
elif st.session_state.slide_index == 3: render_tech()
elif st.session_state.slide_index == 4: render_ecossistema()
elif st.session_state.slide_index == 5: render_objetivos()
elif st.session_state.slide_index == 6: render_roadmap()
elif st.session_state.slide_index == 7: render_proposta()

# Botões de Navegação (Fixo na parte inferior)
st.markdown("<br><br>", unsafe_allow_html=True)
c1, c2, c3 = st.columns([1, 4, 1])

with c1:
    if st.session_state.slide_index > 0:
        if st.button("⬅️ Anterior"):
            prev_slide()
            st.rerun()

with c3:
    if st.session_state.slide_index < 7:
        label = "Iniciar 🚀" if st.session_state.slide_index == 0 else "Próximo ➡️"
        if st.button(label):
            next_slide()
            st.rerun()
    else:
        if st.button("🔄 Reiniciar"):
            reset_slide()
            st.rerun()