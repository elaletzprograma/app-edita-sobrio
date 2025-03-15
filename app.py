import streamlit as st
import spacy
import difflib
import string
import bcrypt
import json
import os
import sendgrid
from sendgrid.helpers.mail import Mail
from xhtml2pdf import pisa
from streamlit_quill import st_quill
from bs4 import BeautifulSoup

# -----------------------------------------
# Parche para st.experimental_rerun en Streamlit 1.x (o entornos donde no exista).
# -----------------------------------------
try:
    from streamlit.runtime.scriptrunner.script_runner import RerunException, RerunData
    def do_rerun():
        """Reemplazo para st.experimental_rerun() en versiones que no lo tengan."""
        raise RerunException(RerunData())
    if not hasattr(st, "experimental_rerun"):
        st.experimental_rerun = do_rerun
except:
    pass

# -----------------------------------------
# Carga spaCy en español
# -----------------------------------------
nlp = spacy.load("es_core_news_md")

# -----------------------------------------
# LanguageTool para español
# -----------------------------------------
import requests
import language_tool_python

class LanguageToolPost(language_tool_python.LanguageToolPublicAPI):
    def _query_server(self, url, params=None, **kwargs):
        if params:
            response = requests.post(url, data=params)
        else:
            response = requests.get(url)
        if response.status_code != 200:
            raise language_tool_python.utils.LanguageToolError(response.content.decode())
        return response.json()

tool = LanguageToolPost('es')

# -----------------------------------------
# Configuración de usuarios (ejemplo local, con JSON)
# -----------------------------------------
USERS_FILE = "users.json"
if os.path.exists(USERS_FILE):
    with open(USERS_FILE, "r") as f:
        users = json.load(f)
else:
    users = {}

# Asegura un usuario admin de ejemplo
if "admin@example.com" not in users:
    hashed_admin = bcrypt.hashpw("clave_admin".encode(), bcrypt.gensalt()).decode()
    users["admin@example.com"] = {
        "nombre": "Administrador",
        "email": "admin@example.com",
        "password": hashed_admin
    }
    with open(USERS_FILE, "w") as f:
        json.dump(users, f)

# -----------------------------------------
# Inicializa st.session_state
# -----------------------------------------
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False
if "analysis_done" not in st.session_state:
    st.session_state["analysis_done"] = False
if "edit_mode" not in st.session_state:
    st.session_state["edit_mode"] = False
if "marca_counts" not in st.session_state:
    st.session_state["marca_counts"] = {}

# Variables booleanas de las casillas
defaults = {
    "show_adverbios": True,
    "show_adjetivos": True,
    "show_repeticiones_totales": True,
    "show_rimas_parciales": True,
    "show_dobles_verbos": True,
    "show_preterito_compuesto": True,
    "show_orthography": False,
    "show_grammar": False
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# -----------------------------------------
# Función de envío de email con SendGrid (opcional)
# -----------------------------------------
def send_email(to_email, subject, body):
    try:
        sg = sendgrid.SendGridAPIClient(api_key=st.secrets["sendgrid"]["api_key"])
        from_email = st.secrets["sendgrid"].get("from_email", "noreply@tusitio.com")
        message = Mail(from_email=from_email, to_emails=to_email, subject=subject, plain_text_content=body)
        response = sg.send(message)
        if response.status_code in [200, 202]:
            st.success(f"Email enviado a {to_email}")
        else:
            st.error(f"Error al enviar email: {response.status_code}")
    except Exception as e:
        st.error(f"Error al enviar email: {e}")

# -----------------------------------------
# Funciones para análisis
# -----------------------------------------
def correct_pos(token_text, spaCy_pos):
    lowered = token_text.lower()
    if spaCy_pos == "ADJ":
        if lowered.endswith(("ita", "ito", "itas", "itos", "ote", "otes")):
            return "NOUN"
    return spaCy_pos

def is_similar(word1, word2):
    def clean(word):
        return word.translate(str.maketrans('', '', string.punctuation)).strip().lower()
    w1 = clean(word1)
    w2 = clean(word2)
    if w1 == w2:
        return True
    if min(len(w1), len(w2)) < 4:
        return False
    ratio = difflib.SequenceMatcher(None, w1, w2).ratio()
    return ratio >= 0.8

def common_suffix(word1, word2, min_len=3):
    w1, w2 = word1.lower(), word2.lower()
    i = 0
    while i < len(w1) and i < len(w2) and w1[-1-i] == w2[-1-i]:
        i += 1
    if i >= min_len:
        return w1[len(w1)-i:]
    return ""

def analizar_texto(texto):
    doc = nlp(texto)
    lt_matches = tool.check(texto)
    tokens_data = []
    for i, token in enumerate(doc):
        corrected = correct_pos(token.text, str(token.pos_))
        tokens_data.append({
            "i": i,
            "text": token.text,
            "lemma": token.lemma_,
            "pos": corrected,
            "morph": str(token.morph),
            "start": token.idx,
            "end": token.idx + len(token.text),
            "ws": token.whitespace_,
        })
    lt_data = []
    for match in lt_matches:
        lt_data.append({
            "start": match.offset,
            "end": match.offset + match.errorLength,
            "category": match.category
        })
    return tokens_data, lt_data, texto

def contar_marcas(tokens_copy):
    counts = {
        "adverbios": 0,
        "adjetivos": 0,
        "repeticiones_totales": 0,
        "rimas_parciales": 0,
        "dobles_verbos": 0,
        "pretérito_compuesto": 0,
        "ortografía": 0,
        "gramática": 0
    }
    for token in tokens_copy:
        styles_str = " ".join(token.get("styles", []))
        if "color: green" in styles_str:
            counts["adverbios"] += 1
        if "background-color: pink" in styles_str:
            counts["adjetivos"] += 1
        if "background-color: orange" in styles_str:
            counts["repeticiones_totales"] += 1
        if token.get("suffix_to_highlight", ""):
            counts["rimas_parciales"] += 1
        if "background-color: #dab4ff" in styles_str:
            counts["dobles_verbos"] += 1
        if "background-color: lightblue" in styles_str:
            counts["pretérito_compuesto"] += 1
        if "underline wavy red" in styles_str:
            counts["ortografía"] += 1
        if "underline wavy yellow" in styles_str:
            counts["gramática"] += 1
    return counts

def construir_html(tokens_data, lt_data, original_text,
                   show_adverbios, show_adjetivos, show_repeticiones_totales, show_rimas_parciales,
                   show_dobles_verbos, show_preterito_compuesto,
                   show_orthography, show_grammar):
    tokens_copy = []
    for t in tokens_data:
        tcopy = t.copy()
        tcopy["styles"] = set()
        tcopy["processed"] = False
        tcopy["suffix_to_highlight"] = ""
        tokens_copy.append(tcopy)
    length = len(tokens_copy)

    # Ortografía/Gramática (LanguageTool)
    if show_orthography or show_grammar:
        for ltmatch in lt_data:
            start_m = ltmatch["start"]
            end_m = ltmatch["end"]
            cat = ltmatch["category"]
            for tk in tokens_copy:
                if tk["start"] >= start_m and tk["end"] <= end_m:
                    if show_orthography and cat in ("TYPOS", "MISSPELLING", "SPELLING"):
                        tk["styles"].add("text-decoration: underline wavy red;")
                    if show_grammar and cat == "GRAMMAR":
                        tk["styles"].add("text-decoration: underline wavy yellow;")

    # Repeticiones / Rimas
    for i, tk in enumerate(tokens_copy):
        if tk["pos"] in {"NOUN", "ADJ", "VERB"}:
            start_w = max(0, i - 45)
            end_w = min(length, i + 46)
            entire_similar = False
            best_suffix = ""
            for j in range(start_w, end_w):
                if j == i:
                    continue
                other = tokens_copy[j]
                if other["pos"] not in {"NOUN", "ADJ", "VERB"}:
                    continue
                if is_similar(tk["text"], other["text"]):
                    entire_similar = True
                else:
                    suffix = common_suffix(tk["text"], other["text"], 3)
                    if suffix and len(suffix) > len(best_suffix):
                        best_suffix = suffix
            if show_repeticiones_totales and entire_similar:
                tk["styles"].add("background-color: orange; text-decoration: underline;")
            if show_rimas_parciales and not entire_similar and best_suffix:
                tk["suffix_to_highlight"] = best_suffix

    # Detección de adverbios, adjetivos, dobles verbos, pretérito compuesto
    i = 0
    while i < length:
        tk = tokens_copy[i]
        if not tk["processed"]:
            # Adverbios en -mente
            if show_adverbios and tk["pos"] == "ADV" and tk["text"].lower().endswith("mente"):
                tk["styles"].add("color: green; text-decoration: underline;")
            # Adjetivos
            if show_adjetivos and tk["pos"] == "ADJ":
                tk["styles"].add("background-color: pink; text-decoration: underline;")
            # Dobles verbos
            if show_dobles_verbos:
                if tk["lemma"] in ["empezar", "comenzar", "tratar"] and (i + 2) < length:
                    t1 = tokens_copy[i + 1]
                    t2 = tokens_copy[i + 2]
                    if t1["text"].lower() == "a" and "VerbForm=Inf" in t2["morph"]:
                        for x in [tk, t1, t2]:
                            x["styles"].add("background-color: #dab4ff; text-decoration: underline;")
                        tk["processed"] = True
                        t1["processed"] = True
                        t2["processed"] = True
                        i += 3
                        continue
                if tk["lemma"] == "ir" and ("Tense=Imp" in tk["morph"]):
                    if (i + 1) < length:
                        t1 = tokens_copy[i + 1]
                        if "VerbForm=Ger" in t1["morph"]:
                            for x in [tk, t1]:
                                x["styles"].add("background-color: #dab4ff; text-decoration: underline;")
                            tk["processed"] = True
                            t1["processed"] = True
                            i += 2
                            continue
            # Pretérito perfecto compuesto
            if show_preterito_compuesto:
                if tk["lemma"] == "haber" and "Pres" in tk["morph"] and (i + 1) < length:
                    t1 = tokens_copy[i + 1]
                    if "VerbForm=Part" in t1["morph"]:
                        for x in [tk, t1]:
                            x["styles"].add("background-color: lightblue; text-decoration: underline;")
                        tk["processed"] = True
                        t1["processed"] = True
                        i += 2
                        continue
        i += 1

    # Reconstrucción en HTML
    paragraphs = original_text.split("\n\n")
    total_tokens = len(tokens_copy)
    global_index = 0
    current_offset = 0
    html_result = ""

    for paragraph in paragraphs:
        lines = paragraph.split("\n")
        paragraph_html = ""
        for line in lines:
            line_html = ""
            line_length = len(line)
            line_start_offset = current_offset
            line_end_offset = current_offset + line_length

            while global_index < total_tokens and tokens_copy[global_index]["start"] < line_end_offset:
                tk = tokens_copy[global_index]
                if tk["end"] <= line_start_offset:
                    global_index += 1
                    continue
                if tk["start"] >= line_start_offset and tk["end"] <= line_end_offset:
                    # Rimas parciales
                    if tk["suffix_to_highlight"]:
                        any_background = any("background-color" in s for s in tk["styles"])
                        if not any_background:
                            word = tk["text"]
                            suffix = tk["suffix_to_highlight"]
                            pos = word.lower().rfind(suffix)
                            if pos >= 0:
                                prefix = word[:pos]
                                matched = word[pos:pos+len(suffix)]
                                postfix = word[pos+len(suffix):]
                                partial_html = (
                                    f"{prefix}"
                                    f"<span style='background-color: #ffcc80; text-decoration: underline;'>"
                                    f"{matched}</span>"
                                    f"{postfix}{tk['ws']}"
                                )
                                line_html += partial_html
                                global_index += 1
                                continue
                    if tk["styles"]:
                        style_str = " ".join(tk["styles"])
                        line_html += f'<span style="{style_str}">{tk["text"]}</span>' + tk["ws"]
                    else:
                        line_html += tk["text"] + tk["ws"]
                    global_index += 1
                else:
                    if tk["start"] >= line_end_offset:
                        break
                    if tk["styles"]:
                        style_str = " ".join(tk["styles"])
                        line_html += f'<span style="{style_str}">{tk["text"]}</span>' + tk["ws"]
                    else:
                        line_html += tk["text"] + tk["ws"]
                    global_index += 1

            paragraph_html += line_html
            if line != lines[-1]:
                paragraph_html += "<br>"
            current_offset += line_length
            if line != lines[-1]:
                current_offset += 1

        html_result += f"<p>{paragraph_html}</p>"
        current_offset += 2

    marca_counts = contar_marcas(tokens_copy)
    return html_result, marca_counts

def exportar_a_pdf(html_content):
    pdf_path = "texto_analizado.pdf"
    with open(pdf_path, "wb") as pdf_file:
        pisa.CreatePDF(html_content, dest=pdf_file)
    return pdf_path

def clean_text(html_text):
    soup = BeautifulSoup(html_text, "html.parser")
    return soup.get_text(separator="\n")

# -----------------------------------------
# Sidebar con casillas y recuento de cada marca
# -----------------------------------------
st.sidebar.header("Opciones del análisis")

# Diccionario para manejar la info de cada checkbox: label, estilo y key de conteo
checkbox_config = {
    "show_adverbios": {
        "label": "Mostrar adverbios",
        "style": "color: green; text-decoration: underline;",
        "count_key": "adverbios"
    },
    "show_adjetivos": {
        "label": "Mostrar adjetivos",
        "style": "background-color: pink; text-decoration: underline;",
        "count_key": "adjetivos"
    },
    "show_repeticiones_totales": {
        "label": "Mostrar repeticiones totales",
        "style": "background-color: orange; text-decoration: underline;",
        "count_key": "repeticiones_totales"
    },
    "show_rimas_parciales": {
        "label": "Mostrar rimas parciales",
        "style": "background-color: #ffcc80; text-decoration: underline;",
        "count_key": "rimas_parciales"
    },
    "show_dobles_verbos": {
        "label": "Mostrar dobles verbos",
        "style": "background-color: #dab4ff; text-decoration: underline;",
        "count_key": "dobles_verbos"
    },
    "show_preterito_compuesto": {
        "label": "Mostrar pretérito compuesto",
        "style": "background-color: lightblue; text-decoration: underline;",
        "count_key": "pretérito_compuesto"
    },
    "show_orthography": {
        "label": "Mostrar errores ortográficos",
        "style": "text-decoration: underline wavy red;",
        "count_key": "ortografía"
    },
    "show_grammar": {
        "label": "Mostrar errores gramaticales",
        "style": "text-decoration: underline wavy yellow;",
        "count_key": "gramática"
    }
}

for key, data in checkbox_config.items():
    # Lee el conteo actual si ya se hizo un análisis
    current_count = 0
    if "marca_counts" in st.session_state and data["count_key"] in st.session_state["marca_counts"]:
        current_count = st.session_state["marca_counts"][data["count_key"]]

    # Dos columnas: una para la casilla, otra para el label con color y recuento
    colA, colB = st.sidebar.columns([1,4])
    default_val = bool(st.session_state.get(key, defaults.get(key, True)))
    current_val = colA.checkbox(
        "",  # label vacío, se pone a la derecha
        value=default_val,
        key=f"ck_{key}"  # Usa una key distinta si quieres
    )
    # Actualiza en session_state
    st.session_state[key] = current_val

    # Muestra el label con color y (conteo)
    colB.markdown(
        f"<span style='{data['style']}'>{data['label']} ({current_count})</span>",
        unsafe_allow_html=True
    )

# -----------------------------------------
# Lógica principal de la app
# -----------------------------------------
analysis_done = st.session_state["analysis_done"]
edit_mode = st.session_state["edit_mode"]

st.title("Texto analizado (con casillas y conteos)")

# --- MODO INICIAL: Pegar texto ---
if not analysis_done:
    st.markdown("### Pega aquí tu texto:")
    texto_inicial = st.text_area("", height=250, label_visibility="hidden")
    if st.button("Analizar"):
        tokens_data, lt_data, original_text = analizar_texto(texto_inicial)
        final_html, marca_counts = construir_html(
            tokens_data,
            lt_data,
            original_text,
            st.session_state["show_adverbios"],
            st.session_state["show_adjetivos"],
            st.session_state["show_repeticiones_totales"],
            st.session_state["show_rimas_parciales"],
            st.session_state["show_dobles_verbos"],
            st.session_state["show_preterito_compuesto"],
            st.session_state["show_orthography"],
            st.session_state["show_grammar"]
        )
        st.session_state["tokens_data"] = tokens_data
        st.session_state["lt_data"] = lt_data
        st.session_state["original_text"] = original_text
        st.session_state["resultado_html"] = final_html
        st.session_state["marca_counts"] = marca_counts
        st.session_state["analysis_done"] = True
        st.session_state["edit_mode"] = False

        # Forzar un rerun (si tu versión lo requiere)
        if hasattr(st, "experimental_rerun"):
            st.session_state["rerun_flag"] = True
            st.experimental_rerun()

# --- MODO LECTURA ---
elif not edit_mode:
    st.markdown("### Texto analizado (no editable)")
    # Reconstruye HTML con los valores de las casillas
    tokens_data = st.session_state["tokens_data"]
    lt_data = st.session_state["lt_data"]
    original_text = st.session_state["original_text"]
    final_html, marca_counts = construir_html(
        tokens_data,
        lt_data,
        original_text,
        st.session_state["show_adverbios"],
        st.session_state["show_adjetivos"],
        st.session_state["show_repeticiones_totales"],
        st.session_state["show_rimas_parciales"],
        st.session_state["show_dobles_verbos"],
        st.session_state["show_preterito_compuesto"],
        st.session_state["show_orthography"],
        st.session_state["show_grammar"]
    )
    st.session_state["resultado_html"] = final_html
    st.session_state["marca_counts"] = marca_counts

    st.markdown(final_html, unsafe_allow_html=True)

    colA, colB = st.columns(2)
    if colA.button("Editar"):
        st.session_state["edit_mode"] = True
        if hasattr(st, "experimental_rerun"):
            st.session_state["rerun_flag"] = True
            st.experimental_rerun()
    if colB.button("Exportar a PDF"):
        # Muestra la leyenda con conteos
        c = st.session_state["marca_counts"]
        adverbios_count = c.get("adverbios", 0)
        adjetivos_count = c.get("adjetivos", 0)
        rep_totales_count = c.get("repeticiones_totales", 0)
        rimas_count = c.get("rimas_parciales", 0)
        dobles_count = c.get("dobles_verbos", 0)
        preterito_count = c.get("pretérito_compuesto", 0)
        ortografia_count = c.get("ortografía", 0)
        gramatica_count = c.get("gramática", 0)
        legend_html = f"""
        <div style="margin-bottom:20px;">
            <strong>Funcionalidades y Colores:</strong>
            <ul style="list-style-type: none; padding: 0;">
                <li><span style='color: green; text-decoration: underline;'>Adverbios en -mente ({adverbios_count})</span></li>
                <li><span style='background-color: pink; text-decoration: underline;'>Adjetivos ({adjetivos_count})</span></li>
                <li><span style='background-color: orange; text-decoration: underline;'>Repeticiones Totales ({rep_totales_count})</span></li>
                <li><span style='background-color: #ffcc80; text-decoration: underline;'>Rimas Parciales ({rimas_count})</span></li>
                <li><span style='background-color: #dab4ff; text-decoration: underline;'>Dobles Verbos ({dobles_count})</span></li>
                <li><span style='background-color: lightblue; text-decoration: underline;'>Pretérito Perf. Comp. ({preterito_count})</span></li>
                <li><span style='text-decoration: underline wavy red;'>Ortografía ({ortografia_count})</span></li>
                <li><span style='text-decoration: underline wavy yellow;'>Gramática ({gramatica_count})</span></li>
            </ul>
        </div>
        """
        pdf_html = f"<html><body style='font-family: Arial;'>{legend_html}{final_html}</body></html>"
        pdf_path = exportar_a_pdf(pdf_html)
        with open(pdf_path, "rb") as f:
            st.download_button("Descargar PDF", data=f, file_name="texto_analizado.pdf", mime="application/pdf")

# --- MODO EDICIÓN ---
else:
    st.markdown("### Texto analizado (editable)")
    with st.form("editor_form"):
        edited_html = st_quill(st.session_state["resultado_html"], key="editor_quill")
        reanalyze_btn = st.form_submit_button("Re-Analizar texto editado")
        return_btn = st.form_submit_button("Volver a lectura")
        export_btn = st.form_submit_button("Exportar a PDF")

    if reanalyze_btn:
        plain_text = clean_text(edited_html)
        # Limpia lo anterior
        st.session_state["tokens_data"] = []
        st.session_state["lt_data"] = []
        st.session_state["original_text"] = ""
        st.session_state["resultado_html"] = ""
        # Vuelve a analizar
        tokens_data, lt_data, original_text = analizar_texto(plain_text)
        final_html, marca_counts = construir_html(
            tokens_data,
            lt_data,
            original_text,
            st.session_state["show_adverbios"],
            st.session_state["show_adjetivos"],
            st.session_state["show_repeticiones_totales"],
            st.session_state["show_rimas_parciales"],
            st.session_state["show_dobles_verbos"],
            st.session_state["show_preterito_compuesto"],
            st.session_state["show_orthography"],
            st.session_state["show_grammar"]
        )
        st.session_state["tokens_data"] = tokens_data
        st.session_state["lt_data"] = lt_data
        st.session_state["original_text"] = original_text
        st.session_state["resultado_html"] = final_html
        st.session_state["marca_counts"] = marca_counts
        st.session_state["edit_mode"] = False

        if hasattr(st, "experimental_rerun"):
            st.session_state["rerun_flag"] = True
            st.experimental_rerun()

    elif return_btn:
        st.session_state["edit_mode"] = False
        if hasattr(st, "experimental_rerun"):
            st.session_state["rerun_flag"] = True
            st.experimental_rerun()

    elif export_btn:
        # Muestra la leyenda con conteos
        c = st.session_state["marca_counts"]
        adverbios_count = c.get("adverbios", 0)
        adjetivos_count = c.get("adjetivos", 0)
        rep_totales_count = c.get("repeticiones_totales", 0)
        rimas_count = c.get("rimas_parciales", 0)
        dobles_count = c.get("dobles_verbos", 0)
        preterito_count = c.get("pretérito_compuesto", 0)
        ortografia_count = c.get("ortografía", 0)
        gramatica_count = c.get("gramática", 0)
        legend_html = f"""
        <div style="margin-bottom:20px;">
            <strong>Funcionalidades y Colores:</strong>
            <ul style="list-style-type: none; padding: 0;">
                <li><span style='color: green; text-decoration: underline;'>Adverbios en -mente ({adverbios_count})</span></li>
                <li><span style='background-color: pink; text-decoration: underline;'>Adjetivos ({adjetivos_count})</span></li>
                <li><span style='background-color: orange; text-decoration: underline;'>Repeticiones Totales ({rep_totales_count})</span></li>
                <li><span style='background-color: #ffcc80; text-decoration: underline;'>Rimas Parciales ({rimas_count})</span></li>
                <li><span style='background-color: #dab4ff; text-decoration: underline;'>Dobles Verbos ({dobles_count})</span></li>
                <li><span style='background-color: lightblue; text-decoration: underline;'>Pretérito Perf. Comp. ({preterito_count})</span></li>
                <li><span style='text-decoration: underline wavy red;'>Ortografía ({ortografia_count})</span></li>
                <li><span style='text-decoration: underline wavy yellow;'>Gramática ({gramatica_count})</span></li>
            </ul>
        </div>
        """
        pdf_html = f"<html><body style='font-family: Arial;'>{legend_html}{st.session_state['resultado_html']}</body></html>"
        pdf_path = exportar_a_pdf(pdf_html)
        with open(pdf_path, "rb") as f:
            st.download_button("Descargar PDF", data=f, file_name="texto_analizado.pdf", mime="application/pdf")