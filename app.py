import streamlit as st
import spacy
import difflib
import string
from xhtml2pdf import pisa
from streamlit_quill import st_quill
from bs4 import BeautifulSoup

# --------------------------------------------------------------------
# Configuración y Carga de Modelo
# --------------------------------------------------------------------
st.set_page_config(page_title="Edita Sobrio", layout="wide")

@st.cache_resource
def load_spacy_model():
    # Cargamos el modelo medio para mejor precisión sintáctica
    return spacy.load("es_core_news_md")

nlp = load_spacy_model()

# --------------------------------------------------------------------
# Inicialización de st.session_state
# --------------------------------------------------------------------
if "analysis_done" not in st.session_state:
    st.session_state["analysis_done"] = False
if "edit_mode" not in st.session_state:
    st.session_state["edit_mode"] = False

# Listas de control para las Reglas Contextuales
VOCATIVOS_FRECUENTES = {"puto", "puta", "cabrón", "cabrona", "pendejo", "pendeja", "estúpido", "estúpida", "wey", "loco", "morra", "vato"}
VERBOS_AMBIGUOS = {"corto", "bajo", "canto", "río", "fallo", "paso"}
AUXILIARES_PERIFRASIS = {"ir", "seguir", "venir", "andar", "estar", "poder", "deber", "tener", "empezar", "comenzar", "tratar"}

# --------------------------------------------------------------------
# Funciones Auxiliares (PDF y Limpieza)
# --------------------------------------------------------------------
def exportar_a_pdf(html_content):
    pdf_path = "texto_analizado.pdf"
    with open(pdf_path, "wb") as pdf_file:
        pisa.CreatePDF(html_content, dest=pdf_file)
    return pdf_path

def clean_text(html_text):
    soup = BeautifulSoup(html_text, "html.parser")
    return soup.get_text(separator="\n")

# --------------------------------------------------------------------
# Reglas de Inteligencia Contextual
# --------------------------------------------------------------------
def correct_pos_smart(token):
    text_lower = token.text.lower()
    pos = token.pos_
    dep = token.dep_
    
    # REGLA A: Detector de Vocativos (Insultos/Apelativos)
    if text_lower in VOCATIVOS_FRECUENTES:
        is_vocative = (dep == "vocative")
        if token.i > 0 and token.nbor(-1).text in [",", "!", "¡"]: is_vocative = True
        if token.i < len(token.doc)-1 and token.nbor(1).text in [",", "!", "¡"]: is_vocative = True
        
        if is_vocative:
            return "NOUN"

    # REGLA B: Verbos disfrazados (Ej: "corto tantito papel")
    if text_lower in VERBOS_AMBIGUOS:
        if token.i < len(token.doc)-1 and token.nbor(1).pos_ in ["NOUN", "DET"]:
            return "VERB"

    # REGLA C: La regla de la Sustantivación (Los determinantes)
    if pos == "ADJ":
        if token.i > 0 and token.nbor(-1).pos_ == "DET":
            return "NOUN"

    # REGLA D: Adverbios de modo terminados en "o"
    if text_lower == "tranquilo" and (dep == "advmod" or (token.i > 0 and token.nbor(-1).text == ",")):
        return "ADV"

    # Filtro de Participios
    if "VerbForm=Part" in str(token.morph):
        return "VERB"

    return pos

# --------------------------------------------------------------------
# Lógica de Análisis
# --------------------------------------------------------------------
def analizar_texto(texto):
    doc = nlp(texto)
    tokens_data = []
    for i, token in enumerate(doc):
        corrected_pos = correct_pos_smart(token)
        tokens_data.append({
            "i": i,
            "text": token.text,
            "lemma": token.lemma_.lower(),
            "pos": corrected_pos,
            "morph": str(token.morph),
            "start": token.idx,
            "end": token.idx + len(token.text),
            "ws": token.whitespace_,
        })
    return tokens_data, texto

def is_similar(word1, word2):
    def clean(word):
        return word.translate(str.maketrans('', '', string.punctuation)).strip().lower()
    w1, w2 = clean(word1), clean(word2)
    if w1 == w2: return True
    if min(len(w1), len(w2)) < 4: return False
    return difflib.SequenceMatcher(None, w1, w2).ratio() >= 0.85

def common_suffix(word1, word2, min_len=3):
    w1, w2 = word1.lower(), word2.lower()
    i = 0
    while i < len(w1) and i < len(w2) and w1[-1-i] == w2[-1-i]:
        i += 1
    return w1[len(w1)-i:] if i >= min_len else ""

def contar_marcas(tokens_copy):
    counts = {
        "adverbios": 0, "adjetivos": 0, "repeticiones_totales": 0,
        "rimas_parciales": 0, "dobles_verbos": 0, "pretérito_compuesto": 0
    }
    for token in tokens_copy:
        styles_str = " ".join(token.get("styles", []))
        if "color: green" in styles_str: counts["adverbios"] += 1
        if "background-color: pink" in styles_str: counts["adjetivos"] += 1
        if "background-color: orange" in styles_str: counts["repeticiones_totales"] += 1
        if token.get("suffix_to_highlight", ""): counts["rimas_parciales"] += 1
        if "background-color: #dab4ff" in styles_str: counts["dobles_verbos"] += 1
        if "background-color: lightblue" in styles_str: counts["pretérito_compuesto"] += 1
    return counts

def construir_html(tokens_data, original_text, options):
    tokens_copy = [t.copy() for t in tokens_data]
    for t in tokens_copy:
        t["styles"] = set()
        t["processed"] = False
        t["suffix_to_highlight"] = ""
    
    length = len(tokens_copy)

    # 1. Análisis de Repeticiones y Rimas
    for i, tk in enumerate(tokens_copy):
        if tk["pos"] in {"NOUN", "ADJ", "VERB"}:
            start_w = max(0, i - 20)
            end_w = min(length, i + 21)
            
            for j in range(start_w, end_w):
                if j == i: continue
                other = tokens_copy[j]
                if other["pos"] not in {"NOUN", "ADJ", "VERB"}: continue
                
                if options["repeticiones"] and is_similar(tk["text"], other["text"]):
                    tk["styles"].add("background-color: orange; text-decoration: underline; color: black;")
                elif options["rimas"]:
                    suffix = common_suffix(tk["text"], other["text"], 3)
                    if suffix: tk["suffix_to_highlight"] = suffix

    # 2. Motor de Estilo
    i = 0
    while i < length:
        tk = tokens_copy[i]
        
        if options["adverbios"] and tk["pos"] == "ADV" and tk["text"].lower().endswith("mente"):
            tk["styles"].add("color: green; text-decoration: underline;")
            
        if options["adjetivos"] and tk["pos"] == "ADJ":
            tk["styles"].add("background-color: pink; text-decoration: underline; color: black;")
            
        if options["dobles_verbos"] and tk["lemma"] in AUXILIARES_PERIFRASIS:
            found_periphrasis = False
            for lookahead in range(1, 4):
                if i + lookahead < length:
                    target = tokens_copy[i + lookahead]
                    if "VerbForm=Inf" in target["morph"] or "VerbForm=Ger" in target["morph"]:
                        for x in range(i, i + lookahead + 1):
                            tokens_copy[x]["styles"].add("background-color: #dab4ff; text-decoration: underline; color: black;")
                            tokens_copy[x]["processed"] = True
                        found_periphrasis = True
                        break
            if found_periphrasis:
                i += 1
                continue

        if options["preterito"] and tk["lemma"] == "haber" and i + 1 < length:
            target = tokens_copy[i + 1]
            if "VerbForm=Part" in target["morph"]:
                tk["styles"].add("background-color: lightblue; text-decoration: underline; color: black;")
                target["styles"].add("background-color: lightblue; text-decoration: underline; color: black;")
                i += 2
                continue
        i += 1

    # Renderizado HTML
    html_result = ""
    paragraphs = original_text.split("\n\n")
    global_idx = 0
    
    for p in paragraphs:
        p_html = ""
        lines = p.split("\n")
        for line in lines:
            line_html = ""
            line_end_offset = original_text.find(line, original_text.find(p)) + len(line)
            
            while global_idx < length and tokens_copy[global_idx]["start"] < line_end_offset:
                tk = tokens_copy[global_idx]
                word_html = tk["text"]
                
                if tk["suffix_to_highlight"] and not any("background-color" in s for s in tk["styles"]):
                    suffix = tk["suffix_to_highlight"]
                    pos = word_html.lower().rfind(suffix)
                    if pos >= 0:
                        word_html = f"{word_html[:pos]}<span style='background-color: #ffcc80; text-decoration: underline; color: black;'>{word_html[pos:pos+len(suffix)]}</span>{word_html[pos+len(suffix):]}"
                
                if tk["styles"]:
                    style_str = " ".join(tk["styles"])
                    line_html += f'<span style="{style_str}">{word_html}</span>' + tk["ws"]
                else:
                    line_html += word_html + tk["ws"]
                global_idx += 1
            p_html += line_html + "<br>"
        html_result += f"<p>{p_html}</p>"

    marca_counts = contar_marcas(tokens_copy)
    return html_result, marca_counts

def generar_leyenda(marca_counts, options):
    legend_items = []
    if options["adverbios"]: legend_items.append(f"<li><span style='color: green; text-decoration: underline; background-color: #f0f0f0; padding: 2px;'>Adverbios en -mente ({marca_counts.get('adverbios', 0)})</span></li>")
    if options["adjetivos"]: legend_items.append(f"<li><span style='background-color: pink; text-decoration: underline; color: black; padding: 2px;'>Adjetivos ({marca_counts.get('adjetivos', 0)})</span></li>")
    if options["repeticiones"]: legend_items.append(f"<li><span style='background-color: orange; text-decoration: underline; color: black; padding: 2px;'>Repeticiones Totales ({marca_counts.get('repeticiones_totales', 0)})</span></li>")
    if options["rimas"]: legend_items.append(f"<li><span style='background-color: #ffcc80; text-decoration: underline; color: black; padding: 2px;'>Rimas Parciales ({marca_counts.get('rimas_parciales', 0)})</span></li>")
    if options["dobles_verbos"]: legend_items.append(f"<li><span style='background-color: #dab4ff; text-decoration: underline; color: black; padding: 2px;'>Dobles Verbos ({marca_counts.get('dobles_verbos', 0)})</span></li>")
    if options["preterito"]: legend_items.append(f"<li><span style='background-color: lightblue; text-decoration: underline; color: black; padding: 2px;'>Pretérito Perfecto Comp. ({marca_counts.get('pretérito_compuesto', 0)})</span></li>")
    
    return f"""
    <div style="margin-top: 20px; margin-bottom: 20px; padding: 10px; background-color: #e0e0e0; border-radius: 5px; border: 1px solid #ccc;">
        <strong style="color: black;">Leyenda de Análisis:</strong>
        <ul style="list-style-type: none; padding: 0; margin: 0;">
            {''.join(legend_items)}
        </ul>
    </div>
    """

# --------------------------------------------------------------------
# Interfaz de Usuario (Streamlit)
# --------------------------------------------------------------------
st.title("Edita sobrio")
st.sidebar.header("Opciones de Estilo")

opts = {
    "adverbios": st.sidebar.checkbox("Adverbios en -mente", True),
    "adjetivos": st.sidebar.checkbox("Adjetivos", True),
    "repeticiones": st.sidebar.checkbox("Repeticiones (Ventana 20)", True),
    "rimas": st.sidebar.checkbox("Rimas Parciales", True),
    "dobles_verbos": st.sidebar.checkbox("Perífrasis (Gerundios/Dobles)", True),
    "preterito": st.sidebar.checkbox("Pretérito Compuesto", False)
}

if st.session_state.get("analysis_done", False):
    leyenda_html = generar_leyenda(st.session_state.get("marca_counts", {}), opts)
    st.sidebar.markdown(leyenda_html, unsafe_allow_html=True)

if not st.session_state["analysis_done"]:
    st.markdown("### Pega aquí tu obra maestra")
    texto = st.text_area("", height=400, label_visibility="hidden")
    if st.button("Analizar"):
        with st.spinner("Analizando ritmo y estilo..."):
            tokens_data, original = analizar_texto(texto)
            html_res, marca_counts = construir_html(tokens_data, original, opts)
            st.session_state["tokens_data"] = tokens_data
            st.session_state["original_text"] = original
            st.session_state["resultado_html"] = html_res
            st.session_state["marca_counts"] = marca_counts
            st.session_state["analysis_done"] = True
            st.session_state["edit_mode"] = False
            st.rerun()

elif not st.session_state["edit_mode"]:
    st.markdown("### Análisis Estilístico")
    # Reconstruir HTML si cambian las opciones en el sidebar
    html_res, marca_counts = construir_html(st.session_state["tokens_data"], st.session_state["original_text"], opts)
    st.session_state["resultado_html"] = html_res
    st.session_state["marca_counts"] = marca_counts
    
    st.markdown(html_res, unsafe_allow_html=True)
    
    colA, colB = st.columns(2)
    with colA:
        if st.button("Editar en vivo"):
            st.session_state["edit_mode"] = True
            st.rerun()
        if st.button("Limpiar y hacer Nuevo Análisis"):
            st.session_state["analysis_done"] = False
            st.rerun()
    with colB:
        leyenda_pdf = generar_leyenda(marca_counts, opts)
        pdf_html = f"<html><body style='font-family: Arial;'>{leyenda_pdf}{html_res}</body></html>"
        pdf_path = exportar_a_pdf(pdf_html)
        with open(pdf_path, "rb") as f:
            st.download_button("Descargar PDF", data=f, file_name="texto_analizado.pdf", mime="application/pdf")

else:
    st.markdown("### Texto analizado (editable)")
    with st.form("editor_form"):
        edited_html = st_quill(st.session_state["resultado_html"], key="editor_quill")
        reanalyze_btn = st.form_submit_button("Re-Analizar texto editado")
        return_btn = st.form_submit_button("Volver a lectura")
        
    if reanalyze_btn:
        plain_text = clean_text(edited_html)
        with st.spinner("Re-analizando el texto..."):
            tokens_data, original = analizar_texto(plain_text)
            html_res, marca_counts = construir_html(tokens_data, original, opts)
            st.session_state["tokens_data"] = tokens_data
            st.session_state["original_text"] = original
            st.session_state["resultado_html"] = html_res
            st.session_state["marca_counts"] = marca_counts
            st.session_state["edit_mode"] = False
            st.rerun()
    elif return_btn:
        st.session_state["edit_mode"] = False
        st.rerun()

st.sidebar.markdown("---")
st.sidebar.info("Esta app no corrige ortografía. Se enfoca en el **ritmo**, los **vicios de estilo** y la **fuerza de la prosa**.")
st.markdown("""
<p style='font-size: small; color: #666; text-align: center; margin-top: 50px;'>
    App creada por <a href="http://www.elaletz.com" target="_blank">El Aletz</a>, Escritor. Aprendiz de boxeador. Bellako onírico. Punk imaginal.<br>
    Prueba la app y dime cómo mejorarla o qué características agregarle: <a href="mailto:escribele@elaletz.com">escribele@elaletz.com</a>
</p>
""", unsafe_allow_html=True)
