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

# Carga modelo spaCy
nlp = spacy.load("es_core_news_md")

# LanguageTool corregido
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

# Usuarios
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

# Session State
default_states = {
    "authenticated": False, "user_email": "", "nombre": "",
    "is_admin": False, "analysis_done": False, "edit_mode": False
}

for key, value in default_states.items():
    if key not in st.session_state:
        st.session_state[key] = value

# Sidebar (SIEMPRE visible)
st.sidebar.header("Configuración del Análisis")
st.session_state["show_adverbios"] = st.sidebar.checkbox("Mostrar adverbios en -mente", True)
st.session_state["show_adjetivos"] = st.sidebar.checkbox("Mostrar adjetivos", True)
st.session_state["show_repeticiones_totales"] = st.sidebar.checkbox("Mostrar repeticiones totales", True)
st.session_state["show_rimas_parciales"] = st.sidebar.checkbox("Mostrar rimas parciales", True)
st.session_state["show_dobles_verbos"] = st.sidebar.checkbox("Mostrar dobles verbos", True)
st.session_state["show_preterito_compuesto"] = st.sidebar.checkbox("Mostrar pretérito compuesto", True)
st.session_state["show_orthography"] = st.sidebar.checkbox("Mostrar errores ortográficos", False)
st.session_state["show_grammar"] = st.sidebar.checkbox("Mostrar errores gramaticales", False)

# AQUÍ PEGAS TODAS TUS FUNCIONES existentes tal cual están:
# correct_pos, is_similar, common_suffix, analizar_texto, construir_html,
# contar_marcas, exportar_a_pdf, clean_text
# NO LAS MODIFIQUES, SOLO PEGA AQUÍ EL BLOQUE EXACTO COMO LO TIENES AHORA.

# Lógica principal Streamlit
analysis_done = st.session_state.get("analysis_done", False)
edit_mode = st.session_state.get("edit_mode", False)

if not analysis_done:
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
            "marca_counts": marca_counts
        })
        st.rerun()

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
    st.markdown(html_result, unsafe_allow_html=True)

    colA, colB = st.columns(2)
    with colA:
        if st.button("Editar"):
            st.session_state["edit_mode"] = True
            st.rerun()
    with colB:
        if st.button("Exportar a PDF"):
            pdf_html = f"<html><body>{html_result}</body></html>"
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
            "marca_counts": marca_counts,
            "edit_mode": False
        })
        st.rerun()

    if return_btn:
        st.session_state["edit_mode"] = False
        st.rerun()

    if export_btn:
        html_result = st.session_state["resultado_html"]
        pdf_html = f"<html><body>{html_result}</body></html>"
        pdf_path = exportar_a_pdf(pdf_html)
        with open(pdf_path, "rb") as f:
            st.download_button("Descargar PDF", data=f, file_name="texto_analizado.pdf", mime="application/pdf")