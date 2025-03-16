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

# --------------------------------------------------------------------
# Sidebar: Opciones y leyenda de colores
# --------------------------------------------------------------------
st.sidebar.header("Opciones del análisis")

# Checkboxes para activar/desactivar funcionalidades
st.session_state["show_adverbios"] = st.sidebar.checkbox("Mostrar adverbios", st.session_state.get("show_adverbios", True))
st.session_state["show_adjetivos"] = st.sidebar.checkbox("Mostrar adjetivos", st.session_state.get("show_adjetivos", True))
st.session_state["show_repeticiones_totales"] = st.sidebar.checkbox("Mostrar repeticiones totales", st.session_state.get("show_repeticiones_totales", True))
st.session_state["show_rimas_parciales"] = st.sidebar.checkbox("Mostrar rimas parciales", st.session_state.get("show_rimas_parciales", True))
st.session_state["show_dobles_verbos"] = st.sidebar.checkbox("Mostrar dobles verbos", st.session_state.get("show_dobles_verbos", True))
st.session_state["show_preterito_compuesto"] = st.sidebar.checkbox("Mostrar pretérito compuesto", st.session_state.get("show_preterito_compuesto", True))
st.session_state["show_orthography"] = st.sidebar.checkbox("Mostrar errores ortográficos", st.session_state.get("show_orthography", False))
st.session_state["show_grammar"] = st.sidebar.checkbox("Mostrar errores gramaticales", st.session_state.get("show_grammar", False))

# Agregamos una leyenda con los colores para que el usuario entienda qué representa cada estilo
legend_html = """
<div style="margin-top:20px;">
    <p><strong>Colores de las funcionalidades:</strong></p>
    <ul style="list-style-type: none; padding-left: 0;">
        <li><span style="color: green; text-decoration: underline;">Adverbios en -mente</span></li>
        <li><span style="background-color: pink; text-decoration: underline;">Adjetivos</span></li>
        <li><span style="background-color: orange; text-decoration: underline;">Repeticiones Totales</span></li>
        <li><span style="background-color: #ffcc80; text-decoration: underline;">Rimas Parciales</span></li>
        <li><span style="background-color: #dab4ff; text-decoration: underline;">Dobles Verbos</span></li>
        <li><span style="background-color: lightblue; text-decoration: underline;">Pretérito Perfecto Comp.</span></li>
        <li><span style="text-decoration: underline wavy red;">Errores ortográficos</span></li>
        <li><span style="text-decoration: underline wavy yellow;">Errores gramaticales</span></li>
    </ul>
</div>
"""
st.sidebar.markdown(legend_html, unsafe_allow_html=True)

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

# (Se mantienen las demás funciones para construir el HTML, exportar a PDF, limpiar texto, etc.)

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
        st.experimental_rerun()  # Actualiza la app

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
            st.experimental_rerun()
    with colB:
        if st.button("Exportar a PDF"):
            pdf_path = exportar_a_pdf(html_result)
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
        st.experimental_rerun()
    elif return_btn:
        st.session_state["edit_mode"] = False
        st.experimental_rerun()
    elif export_btn:
        pdf_path = exportar_a_pdf(st.session_state["resultado_html"])
        with open(pdf_path, "rb") as f:
            st.download_button("Descargar PDF", data=f, file_name="texto_analizado.pdf", mime="application/pdf")