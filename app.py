import streamlit as st
import spacy
import language_tool_python
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

# --------------------------------------------------------------------
# Carga el modelo spaCy en español (se asume que se instalará vía requirements.txt)
# --------------------------------------------------------------------
nlp = spacy.load("es_core_news_md")

# --------------------------------------------------------------------
# Inicializa LanguageTool para español
# --------------------------------------------------------------------
import language_tool_python

class LanguageToolPost(language_tool_python.LanguageToolPublicAPI):
    def _query_server(self, url, params=None, **kwargs):
        import requests
        if params:
            response = requests.post(url, data=params)
        else:
            response = requests.get(url)
        if response.status_code != 200:
            raise language_tool_python.utils.LanguageToolError(response.content.decode())
        return response.json()

tool = LanguageToolPost('es')

# --------------------------------------------------------------------
# Configuración de usuarios para login local usando un archivo JSON
# --------------------------------------------------------------------
USERS_FILE = "users.json"
if os.path.exists(USERS_FILE):
    with open(USERS_FILE, "r") as f:
        users = json.load(f)
else:
    users = {}

# Forzar la existencia del usuario administrador
if "alesongs@gmail.com" not in users:
    hashed_admin = bcrypt.hashpw("#diimeEz@3ellaKit@#".encode(), bcrypt.gensalt()).decode()
    users["alesongs@gmail.com"] = {
        "nombre": "Administrador",
        "email": "alesongs@gmail.com",
        "password": hashed_admin
    }
    with open(USERS_FILE, "w") as f:
        json.dump(users, f)

# --------------------------------------------------------------------
# Inicialización de st.session_state
# --------------------------------------------------------------------
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False
if "user_email" not in st.session_state:
    st.session_state["user_email"] = ""
if "nombre" not in st.session_state:
    st.session_state["nombre"] = ""
if "is_admin" not in st.session_state:
    st.session_state["is_admin"] = False
if "show_admin_panel" not in st.session_state:
    st.session_state["show_admin_panel"] = False
if "show_repeticiones_totales" not in st.session_state:
    st.session_state["show_repeticiones_totales"] = True
if "show_rimas_parciales" not in st.session_state:
    st.session_state["show_rimas_parciales"] = True

# Sidebar con las casillas para activar/desactivar funcionalidades
st.sidebar.header("Opciones del análisis")

st.session_state["show_adverbios"] = st.sidebar.checkbox("Mostrar adverbios", st.session_state.get("show_adverbios", True))
st.session_state["show_adjetivos"] = st.sidebar.checkbox("Mostrar adjetivos", st.session_state.get("show_adjetivos", True))
st.session_state["show_repeticiones_totales"] = st.sidebar.checkbox("Mostrar repeticiones totales", st.session_state.get("show_repeticiones_totales", True))
st.session_state["show_rimas_parciales"] = st.sidebar.checkbox("Mostrar rimas parciales", st.session_state.get("show_rimas_parciales", True))
st.session_state["show_dobles_verbos"] = st.sidebar.checkbox("Mostrar dobles verbos", st.session_state.get("show_dobles_verbos", True))
st.session_state["show_preterito_compuesto"] = st.sidebar.checkbox("Mostrar pretérito compuesto", st.session_state.get("show_preterito_compuesto", True))
st.session_state["show_orthography"] = st.sidebar.checkbox("Mostrar errores ortográficos", st.session_state.get("show_orthography", False))
st.session_state["show_grammar"] = st.sidebar.checkbox("Mostrar errores gramaticales", st.session_state.get("show_grammar", False))

# --------------------------------------------------------------------
# Función para enviar email usando SendGrid (se utilizarán los secrets configurados en Streamlit Cloud)
# --------------------------------------------------------------------
def send_email(to_email, subject, body):
    try:
        sg = sendgrid.SendGridAPIClient(api_key=st.secrets["sendgrid"]["api_key"])
        from_email = st.secrets["sendgrid"].get("from_email", "noreply@tusitio.com")
        message = Mail(
            from_email=from_email,
            to_emails=to_email,
            subject=subject,
            plain_text_content=body
        )
        response = sg.send(message)
        if response.status_code in [200, 202]:
            st.success(f"Email enviado a {to_email}")
        else:
            st.error(f"Error al enviar email: {response.status_code}")
    except Exception as e:
        st.error(f"Error al enviar email: {e}")

# --------------------------------------------------------------------
# Funciones para el análisis del texto
# --------------------------------------------------------------------
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

    i = 0
    while i < length:
        tk = tokens_copy[i]
        if not tk["processed"]:
            if show_adverbios and tk["pos"] == "ADV" and tk["text"].lower().endswith("mente"):
                tk["styles"].add("color: green; text-decoration: underline;")
            if show_adjetivos and tk["pos"] == "ADJ":
                tk["styles"].add("background-color: pink; text-decoration: underline;")
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

# --------------------------------------------------------------------
# Lógica principal de la app
# --------------------------------------------------------------------
analysis_done = st.session_state.get("analysis_done", False)
edit_mode = st.session_state.get("edit_mode", False)

# --- MODO INICIAL: Área para pegar el texto a analizar ---
if not analysis_done:
    st.markdown("### Pega aquí tu obra maestra")
    texto_inicial = st.text_area("", height=300, label_visibility="hidden")
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
        st.session_state["analysis_done"] = True
        st.session_state["edit_mode"] = False
        st.session_state["marca_counts"] = marca_counts
        st.rerun()

# --- MODO LECTURA: Mostrar el texto analizado (no editable) ---
elif not edit_mode:
    st.markdown("### Texto analizado (no editable)")
    html_result, marca_counts = construir_html(
        st.session_state["tokens_data"],
        st.session_state["lt_data"],
        st.session_state["original_text"],
        st.session_state["show_adverbios"],
        st.session_state["show_adjetivos"],
        st.session_state["show_repeticiones_totales"],
        st.session_state["show_rimas_parciales"],
        st.session_state["show_dobles_verbos"],
        st.session_state["show_preterito_compuesto"],
        st.session_state["show_orthography"],
        st.session_state["show_grammar"]
    )
    st.session_state["resultado_html"] = html_result
    st.session_state["marca_counts"] = marca_counts
    st.markdown(html_result, unsafe_allow_html=True)
    colA, colB = st.columns(2)
    with colA:
        if st.button("Editar"):
            st.session_state["edit_mode"] = True
            st.rerun()
    with colB:
        if st.button("Exportar a PDF"):
            marca = st.session_state.get("marca_counts", {})
            adverbios_count = marca.get("adverbios", 0)
            adjetivos_count = marca.get("adjetivos", 0)
            rep_totales_count = marca.get("repeticiones_totales", 0)
            rimas_count = marca.get("rimas_parciales", 0)
            dobles_count = marca.get("dobles_verbos", 0)
            preterito_count = marca.get("pretérito_compuesto", 0)
            ortografia_count = marca.get("ortografía", 0)
            gramatica_count = marca.get("gramática", 0)
            legend_html = f"""
            <div style="margin-bottom:20px;">
                <strong>Funcionalidades y Colores:</strong>
                <ul style="list-style-type: none; padding: 0;">
                    <li><span style='color: green; text-decoration: underline;'>Adverbios en -mente ({adverbios_count})</span></li>
                    <li><span style='background-color: pink; text-decoration: underline;'>Adjetivos ({adjetivos_count})</span></li>
                    <li><span style='background-color: orange; text-decoration: underline;'>Repeticiones Totales ({rep_totales_count})</span></li>
                    <li><span style='background-color: #ffcc80; text-decoration: underline;'>Rimas Parciales ({rimas_count})</span></li>
                    <li><span style='background-color: #dab4ff; text-decoration: underline;'>Dobles Verbos ({dobles_count})</span></li>
                    <li><span style='background-color: lightblue; text-decoration: underline;'>Pretérito Perfecto Comp. ({preterito_count})</span></li>
                    <li><span style='text-decoration: underline wavy red;'>Ortografía ({ortografia_count})</span></li>
                    <li><span style='text-decoration: underline wavy yellow;'>Gramática ({gramatica_count})</span></li>
                </ul>
            </div>
            """
            pdf_html = f"<html><body style='font-family: Arial;'>{legend_html}{html_result}</body></html>"
            pdf_path = exportar_a_pdf(pdf_html)
            with open(pdf_path, "rb") as f:
                st.download_button("Descargar PDF", data=f, file_name="texto_analizado.pdf", mime="application/pdf")

# --- MODO EDICIÓN: Mostrar el texto analizado en un editor ---
else:
    st.markdown("### Texto analizado (editable)")
    with st.form("editor_form"):
        edited_html = st_quill(st.session_state["resultado_html"], key="editor_quill")
        reanalyze_btn = st.form_submit_button("Re-Analizar texto editado")
        return_btn = st.form_submit_button("Volver a lectura")
        export_btn = st.form_submit_button("Exportar a PDF")
    if reanalyze_btn:
        plain_text = clean_text(edited_html)
        st.session_state["tokens_data"] = None
        st.session_state["lt_data"] = []
        st.session_state["original_text"] = ""
        st.session_state["resultado_html"] = ""
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
        st.rerun()
    elif return_btn:
        st.session_state["edit_mode"] = False
        st.rerun()
    elif export_btn:
        html_result, marca_counts = construir_html(
            st.session_state["tokens_data"],
            st.session_state["lt_data"],
            st.session_state["original_text"],
            st.session_state["show_adverbios"],
            st.session_state["show_adjetivos"],
            st.session_state["show_repeticiones_totales"],
            st.session_state["show_rimas_parciales"],
            st.session_state["show_dobles_verbos"],
            st.session_state["show_preterito_compuesto"],
            st.session_state["show_orthography"],
            st.session_state["show_grammar"]
        )
        adverbios_count = marca_counts.get("adverbios", 0)
        adjetivos_count = marca_counts.get("adjetivos", 0)
        rep_totales_count = marca_counts.get("repeticiones_totales", 0)
        rimas_count = marca_counts.get("rimas_parciales", 0)
        dobles_count = marca_counts.get("dobles_verbos", 0)
        preterito_count = marca_counts.get("pretérito_compuesto", 0)
        ortografia_count = marca_counts.get("ortografía", 0)
        gramatica_count = marca_counts.get("gramática", 0)
        legend_html = f"""
        <div style="margin-bottom:20px;">
            <strong>Funcionalidades y Colores:</strong>
            <ul style="list-style-type: none; padding: 0;">
                <li><span style='color: green; text-decoration: underline;'>Adverbios en -mente ({adverbios_count})</span></li>
                <li><span style='background-color: pink; text-decoration: underline;'>Adjetivos ({adjetivos_count})</span></li>
                <li><span style='background-color: orange; text-decoration: underline;'>Repeticiones Totales ({rep_totales_count})</span></li>
                <li><span style='background-color: #ffcc80; text-decoration: underline;'>Rimas Parciales ({rimas_count})</span></li>
                <li><span style='background-color: #dab4ff; text-decoration: underline;'>Dobles Verbos ({dobles_count})</span></li>
                <li><span style='background-color: lightblue; text-decoration: underline;'>Pretérito Perfecto Comp. ({preterito_count})</span></li>
                <li><span style='text-decoration: underline wavy red;'>Ortografía ({ortografia_count})</span></li>
                <li><span style='text-decoration: underline wavy yellow;'>Gramática ({gramatica_count})</span></li>
            </ul>
        </div>
        """
        pdf_html = f"<html><body style='font-family: Arial;'>{legend_html}{html_result}</body></html>"
        pdf_path = exportar_a_pdf(pdf_html)
        with open(pdf_path, "rb") as f:
            st.download_button("Descargar PDF", data=f, file_name="texto_analizado.pdf", mime="application/pdf")