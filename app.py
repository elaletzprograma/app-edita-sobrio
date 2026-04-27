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

# Listas de control para las Reglas Contextuales
VOCATIVOS_FRECUENTES = {"puto", "puta", "cabrón", "cabrona", "pendejo", "pendeja", "estúpido", "estúpida", "wey", "loco", "morra", "vato"}
VERBOS_AMBIGUOS = {"corto", "bajo", "canto", "río", "fallo", "paso"}
AUXILIARES_PERIFRASIS = {"ir", "seguir", "venir", "andar", "estar", "poder", "deber", "tener", "empezar", "comenzar", "tratar"}

# --------------------------------------------------------------------
# Reglas de Inteligencia Contextual
# --------------------------------------------------------------------
def correct_pos_smart(token):
    text_lower = token.text.lower()
    pos = token.pos_
    tag = token.tag_
    dep = token.dep_
    
    # REGLA A: Detector de Vocativos (Insultos/Apelativos)
    # Si es una palabra de nuestra lista y está aislada por puntuación o marcada como vocativo
    if text_lower in VOCATIVOS_FRECUENTES:
        if dep == "vocative" or token.nbor(-1).text in [",", "!", "¡"] or token.nbor(1).text in [",", "!", "¡"]:
            return "NOUN"

    # REGLA B: Verbos disfrazados (Ej: "corto tantito papel")
    if text_lower in VERBOS_AMBIGUOS:
        # Si el siguiente es un sustantivo y no hay un sustantivo antes que lo califique
        try:
            if token.nbor(1).pos_ in ["NOUN", "DET"]:
                return "VERB"
        except: pass

    # REGLA C: La regla de la Sustantivación (Los determinantes)
    # Si un "adjetivo" tiene un artículo o demostrativo antes, es sustantivo
    if pos == "ADJ":
        try:
            if token.nbor(-1).pos_ == "DET":
                return "NOUN"
        except: pass

    # REGLA D: Adverbios de modo terminados en "o" (Ej: "los seco, tranquilo,")
    if text_lower == "tranquilo" and (dep == "advmod" or token.nbor(-1).text == ","):
        return "ADV"

    # Filtro de Participios (Evitar que "hecho" o "ahogado" sean adjetivos)
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
    return difflib.SequenceMatcher(None, w1, w2).ratio() >= 0.85 # Un poco más estricto

def common_suffix(word1, word2, min_len=3):
    w1, w2 = word1.lower(), word2.lower()
    i = 0
    while i < len(w1) and i < len(w2) and w1[-1-i] == w2[-1-i]:
        i += 1
    return w1[len(w1)-i:] if i >= min_len else ""

def construir_html(tokens_data, original_text, options):
    tokens_copy = [t.copy() for t in tokens_data]
    for t in tokens_copy:
        t["styles"] = set()
        t["processed"] = False
        t["suffix_to_highlight"] = ""
    
    length = len(tokens_copy)

    # 1. Análisis de Repeticiones y Rimas (Ventana reducida a 20 palabras)
    for i, tk in enumerate(tokens_copy):
        if tk["pos"] in {"NOUN", "ADJ", "VERB"}:
            start_w = max(0, i - 20) # Ventana humana, no enciclopédica
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

    # 2. Motor de Estilo (Adverbios, Adjetivos, Perífrasis)
    i = 0
    while i < length:
        tk = tokens_copy[i]
        
        # Adverbios en -mente
        if options["adverbios"] and tk["pos"] == "ADV" and tk["text"].lower().endswith("mente"):
            tk["styles"].add("color: green; text-decoration: underline;")
            
        # Adjetivos (Puros)
        if options["adjetivos"] and tk["pos"] == "ADJ":
            tk["styles"].add("background-color: pink; text-decoration: underline; color: black;")
            
        # NUEVO: Dobles Verbos (Perífrasis Verbales)
        if options["dobles_verbos"] and tk["lemma"] in AUXILIARES_PERIFRASIS:
            # Detectar: auxiliar + (a/que/de) + infinitivo/gerundio
            found_periphrasis = False
            for lookahead in range(1, 4): # Buscamos en los próximos 3 tokens
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

        # NUEVO: Pretérito Compuesto
        if options["preterito"] and tk["lemma"] == "haber" and i + 1 < length:
            target = tokens_copy[i + 1]
            if "VerbForm=Part" in target["morph"]:
                tk["styles"].add("background-color: lightblue; text-decoration: underline; color: black;")
                target["styles"].add("background-color: lightblue; text-decoration: underline; color: black;")
                i += 2
                continue
        i += 1

    # Renderizado HTML (Preservando estructura original)
    html_result = ""
    paragraphs = original_text.split("\n\n")
    global_idx = 0
    
    for p in paragraphs:
        p_html = ""
        lines = p.split("\n")
        for line in lines:
            line_html = ""
            # Sincronizar tokens con la línea actual
            line_end_offset = original_text.find(line, original_text.find(p)) + len(line)
            
            while global_idx < length and tokens_copy[global_idx]["start"] < line_end_offset:
                tk = tokens_copy[global_idx]
                word_html = tk["text"]
                
                if tk["suffix_to_highlight"] and not any("background-color" in s for s in tk["styles"]):
                    suffix = tk["suffix_to_highlight"]
                    pos = word_html.lower().rfind(suffix)
                    if pos >= 0:
                        word_html = f"{word_html[:pos]}<span style='background-color: #ffcc80; text-decoration: underline;'>{word_html[pos:pos+len(suffix)]}</span>{word_html[pos+len(suffix):]}"
                
                if tk["styles"]:
                    style_str = " ".join(tk["styles"])
                    line_html += f'<span style="{style_str}">{word_html}</span>' + tk["ws"]
                else:
                    line_html += word_html + tk["ws"]
                global_idx += 1
            p_html += line_html + "<br>"
        html_result += f"<p>{p_html}</p>"

    return html_result, tokens_copy

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

if not st.session_state["analysis_done"]:
    st.markdown("### Pega aquí tu obra maestra")
    texto = st.text_area("", height=400, label_visibility="hidden")
    if st.button("Analizar"):
        with st.spinner("Analizando ritmo y estilo..."):
            tokens_data, original = analizar_texto(texto)
            st.session_state["tokens_data"] = tokens_data
            st.session_state["original_text"] = original
            st.session_state["analysis_done"] = True
            st.rerun()

else:
    html_res, final_tokens = construir_html(st.session_state["tokens_data"], st.session_state["original_text"], opts)
    
    st.markdown("### Análisis Estilístico")
    st.markdown(html_res, unsafe_allow_html=True)
    
    if st.button("Nuevo Análisis"):
        st.session_state["analysis_done"] = False
        st.rerun()

st.sidebar.markdown("---")
st.sidebar.info("Esta app no corrige ortografía. Se enfoca en el **ritmo**, los **vicios de estilo** y la **fuerza de la prosa**.")
