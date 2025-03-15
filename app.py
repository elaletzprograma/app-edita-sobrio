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
import requests

# --------------------------------------------------------------------
# Carga el modelo spaCy en español
# --------------------------------------------------------------------
nlp = spacy.load("es_core_news_md")

# --------------------------------------------------------------------
# Inicializa LanguageTool para español usando método POST
# --------------------------------------------------------------------
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

# --------------------------------------------------------------------
# Configuración de usuarios para login local usando archivo JSON
# --------------------------------------------------------------------
USERS_FILE = "users.json"
if os.path.exists(USERS_FILE):
    with open(USERS_FILE, "r") as f:
        users = json.load(f)
else:
    users = {}

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
# Sidebar (Corrección exacta y definitiva)
# --------------------------------------------------------------------
st.sidebar.header("Configuración del Análisis")
for key, label, default in [
    ("show_adverbios", "Mostrar adverbios", True),
    ("show_adjetivos", "Mostrar adjetivos", True),
    ("show_repeticiones_totales", "Mostrar repeticiones totales", True),
    ("show_rimas_parciales", "Mostrar rimas parciales", True),
    ("show_dobles_verbos", "Mostrar dobles verbos", True),
    ("show_preterito_compuesto", "Mostrar pretérito compuesto", True),
    ("show_orthography", "Mostrar errores ortográficos", False),
    ("show_grammar", "Mostrar errores gramaticales", False)
]:
    if key not in st.session_state:
        st.session_state[key] = default
    st.session_state[key] = st.sidebar.checkbox(label, value=default)

# --------------------------------------------------------------------
# Inicialización de st.session_state (Sin modificar nada)
# --------------------------------------------------------------------
session_defaults = {
    "authenticated": False,
    "user_email": "",
    "nombre": "",
    "is_admin": False,
    "show_admin_panel": False,
    "analysis_done": False,
    "edit_mode": False,
}
for key, val in session_state_defaults.items():
    if key not in st.session_state:
        st.session_state[key] = val

# --------------------------------------------------------------------
# (Aquí debes incluir TODAS tus funciones originales completas sin cambios:)
# correct_pos, is_similar, common_suffix, analizar_texto, contar_marcas, construir_html, exportar_a_pdf, clean_text
# --------------------------------------------------------------------
# COPIA Y PEGA AQUÍ TUS FUNCIONES ORIGINALES EXACTAMENTE COMO LAS TIENES AHORA (sin cambios).

# --------------------------------------------------------------------
# Lógica principal de la app
# --------------------------------------------------------------------
if not st.session_state["analysis_done"]:
    st.markdown("### Pega aquí tu obra maestra")
    texto_inicial = st.text_area("", height=300, label_visibility="hidden")
    if st.button("Analizar"):
        tokens_data, lt_data, original_text = analizar_texto(texto_inicial)
        final_html, marca_counts = construir_html(
            tokens_data, lt_data, original_text,
            st.session_state["show_adverbios"],
            st.session_state["show_adjetivos"],
            st.session_state["show_repeticiones_totales"],
            st.session_state["show_rimas_parciales"],
            st.session_state["show_dobles_verbos"],
            st.session_state["show_preterito_compuesto"],
            st.session_state["show_orthography"],
            st.session_state["show_grammar"]
        )
        st.session_state.update({
            "tokens_data": tokens_data,
            "lt_data": lt_data,
            "original_text": original_text,
            "resultado_html": final_html,
            "analysis_done": True,
            "edit_mode": False,
            "marca_counts": contar_marcas(tokens_data)
        })
        st.rerun()

elif not st.session_state["edit_mode"]:
    st.markdown("### Texto analizado (no editable)")
    st.markdown(st.session_state["resultado_html"], unsafe_allow_html=True)
    colA, colB = st.columns(2)
    with colA:
        if st.button("Editar"):
            st.session_state["edit_mode"] = True
            st.rerun()
    with colB:
        if st.button("Exportar a PDF"):
            pdf_html = f"<html><body>{st.session_state['resultado_html']}</body></html>"
            pdf_path = exportar_a_pdf(pdf_html)
            with open(pdf_path, "rb") as f:
                st.download_button("Descargar PDF", data=f, file_name="texto_analizado.pdf", mime="application/pdf")

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
            tokens_data, lt_data, original_text,
            st.session_state["show_adverbios"],
            st.session_state["show_adjetivos"],
            st.session_state["show_repeticiones_totales"],
            st.session_state["show_rimas_parciales"],
            st.session_state["show_dobles_verbos"],
            st.session_state["show_preterito_compuesto"],
            st.session_state["show_orthography"],
            st.session_state["show_grammar"]
        )
        st.session_state.update({
            "tokens_data": tokens_data,
            "lt_data": lt_data,
            "original_text": original_text,
            "resultado_html": final_html,
            "marca_counts": contar_marcas(tokens_data),
            "edit_mode": False
        })
        st.rerun()
    elif return_btn:
        st.session_state["edit_mode"] = False
        st.rerun()
    elif export_btn:
        pdf_html = f"<html><body>{st.session_state['resultado_html']}</body></html>"
        pdf_path = exportar_a_pdf(pdf_html)
        with open(pdf_path, "rb") as f:
            st.download_button("Descargar PDF", data=f, file_name="texto_analizado.pdf", mime="application/pdf")