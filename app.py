import streamlit as st
import spacy
import language_tool_python
import difflib
import string
import bcrypt
import sqlite3
import sendgrid
from sendgrid.helpers.mail import Mail
from xhtml2pdf import pisa
from streamlit_quill import st_quill
from bs4 import BeautifulSoup
import secrets

# --------------------------------------------------------------------
# Carga el modelo spaCy en español
# --------------------------------------------------------------------
nlp = spacy.load("es_core_news_md")

# --------------------------------------------------------------------
# Inicializa LanguageTool para español usando un servidor remoto
# --------------------------------------------------------------------
try:
    tool = language_tool_python.LanguageTool('es', remote_server='https://languagetool.org/api/')
except language_tool_python.utils.LanguageToolError as e:
    st.error(f"Error al inicializar LanguageTool: {e}")
    tool = None

# --------------------------------------------------------------------
# Configuración de la base de datos SQLite
# --------------------------------------------------------------------
conn = sqlite3.connect('users.db', check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS users
             (email TEXT PRIMARY KEY, nombre TEXT, password TEXT, is_admin INTEGER)''')
conn.commit()

# Forzar la existencia del usuario administrador
admin_email = "alesongs@gmail.com"
c.execute("SELECT * FROM users WHERE email=?", (admin_email,))
if not c.fetchone():
    hashed_admin = bcrypt.hashpw("#diimeEz@3ellaKit@#".encode(), bcrypt.gensalt()).decode()
    c.execute("INSERT INTO users (email, nombre, password, is_admin) VALUES (?, ?, ?, 1)", 
              (admin_email, "Administrador", hashed_admin))
    conn.commit()

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
if "analysis_done" not in st.session_state:
    st.session_state["analysis_done"] = False
if "edit_mode" not in st.session_state:
    st.session_state["edit_mode"] = False
if "editing_user" not in st.session_state:
    st.session_state["editing_user"] = None
if "changing_password" not in st.session_state:
    st.session_state["changing_password"] = None

# --------------------------------------------------------------------
# Funciones de base de datos
# --------------------------------------------------------------------
def get_all_users():
    c.execute("SELECT * FROM users")
    return c.fetchall()

def get_user_by_email(email):
    c.execute("SELECT * FROM users WHERE email=?", (email,))
    return c.fetchone()

def register_user(nombre, email, password):
    hashed_password = hash_password(password)
    c.execute("INSERT INTO users (email, nombre, password, is_admin) VALUES (?, ?, ?, 0)", (email, nombre, hashed_password))
    conn.commit()

def update_user(old_email, new_email, nombre):
    c.execute("UPDATE users SET email=?, nombre=? WHERE email=?", (new_email, nombre, old_email))
    conn.commit()

def delete_user(email):
    c.execute("DELETE FROM users WHERE email=?", (email,))
    conn.commit()

def reset_password(email, new_password):
    hashed_password = hash_password(new_password)
    c.execute("UPDATE users SET password=? WHERE email=?", (hashed_password, email))
    conn.commit()

# --------------------------------------------------------------------
# Función para enviar email usando SendGrid
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
# Función para hashear contraseñas
# --------------------------------------------------------------------
def hash_password(password):
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

# --------------------------------------------------------------------
# Función para verificar contraseñas
# --------------------------------------------------------------------
def check_password(stored_password, provided_password):
    return bcrypt.checkpw(provided_password.encode(), stored_password.encode())

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
    if tool is not None:
        try:
            max_length = 1000
            text_blocks = [texto[i:i+max_length] for i in range(0, len(texto), max_length)]
            offset = 0
            for block in text_blocks:
                lt_matches = tool.check(block)
                for match in lt_matches:
                    lt_data.append({
                        "start": match.offset + offset,
                        "end": match.offset + match.errorLength + offset,
                        "category": match.category
                    })
                offset += len(block)
        except language_tool_python.utils.LanguageToolError as e:
            st.warning(f"No se pudo realizar la corrección gramatical: {e}")
    else:
        st.warning("LanguageTool no está disponible. No se pueden analizar errores gramaticales/ortográficos.")
    
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
                tk["styles"].add("background-color: orange; text-decoration: underline; color: black;")
            if show_rimas_parciales and not entire_similar and best_suffix:
                tk["suffix_to_highlight"] = best_suffix

    i = 0
    while i < length:
        tk = tokens_copy[i]
        if not tk["processed"]:
            if show_adverbios and tk["pos"] == "ADV" and tk["text"].lower().endswith("mente"):
                tk["styles"].add("color: green; text-decoration: underline;")
            if show_adjetivos and tk["pos"] == "ADJ":
                tk["styles"].add("background-color: pink; text-decoration: underline; color: black;")
            if show_dobles_verbos:
                if tk["lemma"] in ["empezar", "comenzar", "tratar"] and (i + 2) < length:
                    t1 = tokens_copy[i + 1]
                    t2 = tokens_copy[i + 2]
                    if t1["text"].lower() == "a" and "VerbForm=Inf" in t2["morph"]:
                        for x in [tk, t1, t2]:
                            x["styles"].add("background-color: #dab4ff; text-decoration: underline; color: black;")
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
                                x["styles"].add("background-color: #dab4ff; text-decoration: underline; color: black;")
                            tk["processed"] = True
                            t1["processed"] = True
                            i += 2
                            continue
            if show_preterito_compuesto:
                if tk["lemma"] == "haber" and "Pres" in tk["morph"] and (i + 1) < length:
                    t1 = tokens_copy[i + 1]
                    if "VerbForm=Part" in t1["morph"]:
                        for x in [tk, t1]:
                            x["styles"].add("background-color: lightblue; text-decoration: underline; color: black;")
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
                                    f"<span style='background-color: #ffcc80; text-decoration: underline; color: black;'>"
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
# Función para generar la leyenda de colores con mejor visibilidad
# --------------------------------------------------------------------
def generar_leyenda(marca_counts, show_adverbios, show_adjetivos, show_repeticiones_totales, show_rimas_parciales,
                    show_dobles_verbos, show_preterito_compuesto, show_orthography, show_grammar):
    legend_items = []
    if show_adverbios:
        legend_items.append(f"<li><span style='color: green; text-decoration: underline; background-color: #f0f0f0; padding: 2px;'>Adverbios en -mente ({marca_counts.get('adverbios', 0)})</span></li>")
    if show_adjetivos:
        legend_items.append(f"<li><span style='background-color: pink; text-decoration: underline; color: black; padding: 2px;'>Adjetivos ({marca_counts.get('adjetivos', 0)})</span></li>")
    if show_repeticiones_totales:
        legend_items.append(f"<li><span style='background-color: orange; text-decoration: underline; color: black; padding: 2px;'>Repeticiones Totales ({marca_counts.get('repeticiones_totales', 0)})</span></li>")
    if show_rimas_parciales:
        legend_items.append(f"<li><span style='background-color: #ffcc80; text-decoration: underline; color: black; padding: 2px;'>Rimas Parciales ({marca_counts.get('rimas_parciales', 0)})</span></li>")
    if show_dobles_verbos:
        legend_items.append(f"<li><span style='background-color: #dab4ff; text-decoration: underline; color: black; padding: 2px;'>Dobles Verbos ({marca_counts.get('dobles_verbos', 0)})</span></li>")
    if show_preterito_compuesto:
        legend_items.append(f"<li><span style='background-color: lightblue; text-decoration: underline; color: black; padding: 2px;'>Pretérito Perfecto Comp. ({marca_counts.get('pretérito_compuesto', 0)})</span></li>")
    if show_orthography:
        legend_items.append(f"<li><span style='text-decoration: underline wavy red; background-color: #f0f0f0; padding: 2px; color: black;'>Ortografía ({marca_counts.get('ortografía', 0)})</span></li>")
    if show_grammar:
        legend_items.append(f"<li><span style='text-decoration: underline wavy yellow; background-color: #f0f0f0; padding: 2px; color: black;'>Gramática ({marca_counts.get('gramática', 0)})</span></li>")
    
    legend_html = f"""
    <div style="margin-top: 20px; padding: 10px; background-color: #e0e0e0; border-radius: 5px; border: 1px solid #ccc;">
        <strong style="color: black;">Leyenda de Análisis:</strong>
        <ul style="list-style-type: none; padding: 0; margin: 0;">
            {''.join(legend_items)}
        </ul>
    </div>
    """
    return legend_html

# --------------------------------------------------------------------
# Lógica principal de la app
# --------------------------------------------------------------------
st.title("Edita sobrio")

if not st.session_state["authenticated"]:
    st.markdown("### Iniciar Sesión")
    email = st.text_input("Email")
    password = st.text_input("Contraseña", type="password")
    if st.button("Iniciar Sesión"):
        user = get_user_by_email(email)
        if user and check_password(user[2], password):  # user[2] es la contraseña hasheada
            st.session_state["authenticated"] = True
            st.session_state["user_email"] = email
            st.session_state["nombre"] = user[1]  # user[1] es el nombre
            st.session_state["is_admin"] = bool(user[3])  # user[3] es is_admin
            if st.session_state["is_admin"]:
                st.session_state["show_admin_panel"] = True
            st.success(f"Bienvenido, {st.session_state['nombre']}")
            st.rerun()
        else:
            st.error("Email o contraseña incorrectos")
else:
    if st.session_state["is_admin"]:
        st.sidebar.markdown(f"Bienvenido, {st.session_state['nombre']} (Admin)")
        if st.sidebar.button("Panel de Administración"):
            st.session_state["show_admin_panel"] = True
        if st.sidebar.button("Análisis de Texto"):
            st.session_state["show_admin_panel"] = False
    else:
        st.sidebar.markdown(f"Bienvenido, {st.session_state['nombre']}")

    if st.session_state["is_admin"] and st.session_state["show_admin_panel"]:
        st.markdown("### Panel de Administración")
        
        st.subheader("Registrar Nuevo Usuario")
        new_nombre = st.text_input("Nombre del nuevo usuario")
        new_email = st.text_input("Email del nuevo usuario")
        new_password = st.text_input("Contraseña del nuevo usuario", type="password")
        if st.button("Registrar Usuario"):
            if not get_user_by_email(new_email):
                register_user(new_nombre, new_email, new_password)
                st.success(f"Usuario {new_email} registrado exitosamente")
                send_email(new_email, "Bienvenido a Edita sobrio",
                           f"Hola {new_nombre}: ya estás. Ya tienes cuenta en la app de Tinta chida Edita sobrio. "
                           f"El email con el que iniciarás sesión es {new_email} y tu contraseña es {new_password}. "
                           "Métele duro a la corrección, compa. "
                           "Puedes acceder a la aplicación aquí: https://editasobrio.streamlit.app/")
            else:
                st.error("El email ya está registrado")
        
        st.subheader("Gestionar Usuarios Existentes")
        if st.session_state["editing_user"] is not None:
            user_to_edit = get_user_by_email(st.session_state["editing_user"])
            st.subheader(f"Editando a {user_to_edit[1]}")
            edit_nombre = st.text_input("Nombre", value=user_to_edit[1])
            edit_email = st.text_input("Email", value=user_to_edit[0])
            if st.button("Guardar Cambios"):
                if edit_email != st.session_state["editing_user"] and get_user_by_email(edit_email):
                    st.error("El nuevo email ya está registrado")
                else:
                    update_user(st.session_state["editing_user"], edit_email, edit_nombre)
                    st.success("Usuario actualizado")
                    st.session_state["editing_user"] = None
                    st.rerun()
        elif st.session_state["changing_password"] is not None:
            new_password = st.text_input("Nueva Contraseña", type="password")
            if st.button("Cambiar Contraseña"):
                reset_password(st.session_state["changing_password"], new_password)
                st.success("Contraseña cambiada")
                st.session_state["changing_password"] = None
                st.rerun()
        else:
            users = get_all_users()
            for user in users:
                if user[0] == "alesongs@gmail.com":  # No mostrar al admin en la lista editable
                    continue
                with st.expander(f"{user[1]} ({user[0]})"):
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        if st.button("Editar", key=f"edit_{user[0]}"):
                            st.session_state["editing_user"] = user[0]
                    with col2:
                        if st.button("Eliminar", key=f"delete_{user[0]}"):
                            delete_user(user[0])
                            st.success("Usuario eliminado")
                            st.rerun()
                    with col3:
                        if st.button("Cambiar Contraseña", key=f"change_{user[0]}"):
                            st.session_state["changing_password"] = user[0]
                    with col4:
                        if st.button("Reenviar Correo", key=f"resend_{user[0]}"):
                            temp_password = secrets.token_urlsafe(12)
                            reset_password(user[0], temp_password)
                            send_email(user[0], "Restablecimiento de Contraseña",
                                       f"Hola {user[1]}: Tu nueva contraseña temporal es {temp_password}. "
                                       "Por favor, cámbiala después de iniciar sesión. "
                                       "Puedes acceder a la aplicación aquí: https://editasobrio.streamlit.app/")
                            st.success("Correo reenviado con nueva contraseña temporal")
    else:
        st.sidebar.header("Opciones del análisis")
        st.session_state["show_adverbios"] = st.sidebar.checkbox("Ver adverbios en -mente", st.session_state.get("show_adverbios", True))
        st.session_state["show_adjetivos"] = st.sidebar.checkbox("Ver adjetivos", st.session_state.get("show_adjetivos", True))
        st.session_state["show_repeticiones_totales"] = st.sidebar.checkbox("Ver repeticiones totales", st.session_state.get("show_repeticiones_totales", True))
        st.session_state["show_rimas_parciales"] = st.sidebar.checkbox("Ver rimas parciales", st.session_state.get("show_rimas_parciales", True))
        st.session_state["show_dobles_verbos"] = st.sidebar.checkbox("Ver dobles verbos", st.session_state.get("show_dobles_verbos", True))
        st.session_state["show_preterito_compuesto"] = st.sidebar.checkbox("Ver pretérito compuesto", st.session_state.get("show_preterito_compuesto", True))
        st.session_state["show_orthography"] = st.sidebar.checkbox("Ver errores ortográficos", st.session_state.get("show_orthography", False))
        st.session_state["show_grammar"] = st.sidebar.checkbox("Ver errores gramaticales", st.session_state.get("show_grammar", False))

        if st.session_state.get("analysis_done", False):
            leyenda_html = generar_leyenda(
                st.session_state.get("marca_counts", {}),
                st.session_state["show_adverbios"],
                st.session_state["show_adjetivos"],
                st.session_state["show_repeticiones_totales"],
                st.session_state["show_rimas_parciales"],
                st.session_state["show_dobles_verbos"],
                st.session_state["show_preterito_compuesto"],
                st.session_state["show_orthography"],
                st.session_state["show_grammar"]
            )
            st.sidebar.markdown(leyenda_html, unsafe_allow_html=True)

        if not st.session_state["analysis_done"]:
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
        elif not st.session_state["edit_mode"]:
            st.markdown("### Texto analizado")
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
                        <strong style="color: black;">Funcionalidades y Colores:</strong>
                        <ul style="list-style-type: none; padding: 0;">
                            <li><span style='color: green; text-decoration: underline; background-color: #f0f0f0; padding: 2px;'>Adverbios en -mente ({adverbios_count})</span></li>
                            <li><span style='background-color: pink; text-decoration: underline; color: black; padding: 2px;'>Adjetivos ({adjetivos_count})</span></li>
                            <li><span style='background-color: orange; text-decoration: underline; color: black; padding: 2px;'>Repeticiones Totales ({rep_totales_count})</span></li>
                            <li><span style='background-color: #ffcc80; text-decoration: underline; color: black; padding: 2px;'>Rimas Parciales ({rimas_count})</span></li>
                            <li><span style='background-color: #dab4ff; text-decoration: underline; color: black; padding: 2px;'>Dobles Verbos ({dobles_count})</span></li>
                            <li><span style='background-color: lightblue; text-decoration: underline; color: black; padding: 2px;'>Pretérito Perfecto Comp. ({preterito_count})</span></li>
                            <li><span style='text-decoration: underline wavy red; background-color: #f0f0f0; padding: 2px; color: black;'>Ortografía ({ortografia_count})</span></li>
                            <li><span style='text-decoration: underline wavy yellow; background-color: #f0f0f0; padding: 2px; color: black;'>Gramática ({gramatica_count})</span></li>
                        </ul>
                    </div>
                    """
                    pdf_html = f"<html><body style='font-family: Arial;'>{legend_html}{html_result}</body></html>"
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
                    <strong style="color: black;">Funcionalidades y Colores:</strong>
                    <ul style="list-style-type: none; padding: 0;">
                        <li><span style='color: green; text-decoration: underline; background-color: #f0f0f0; padding: 2px;'>Adverbios en -mente ({adverbios_count})</span></li>
                        <li><span style='background-color: pink; text-decoration: underline; color: black; padding: 2px;'>Adjetivos ({adjetivos_count})</span></li>
                        <li><span style='background-color: orange; text-decoration: underline; color: black; padding: 2px;'>Repeticiones Totales ({rep_totales_count})</span></li>
                        <li><span style='background-color: #ffcc80; text-decoration: underline; color: black; padding: 2px;'>Rimas Parciales ({rimas_count})</span></li>
                        <li><span style='background-color: #dab4ff; text-decoration: underline; color: black; padding: 2px;'>Dobles Verbos ({dobles_count})</span></li>
                        <li><span style='background-color: lightblue; text-decoration: underline; color: black; padding: 2px;'>Pretérito Perfecto Comp. ({preterito_count})</span></li>
                        <li><span style='text-decoration: underline wavy red; background-color: #f0f0f0; padding: 2px; color: black;'>Ortografía ({ortografia_count})</span></li>
                        <li><span style='text-decoration: underline wavy yellow; background-color: #f0f0f0; padding: 2px; color: black;'>Gramática ({gramatica_count})</span></li>
                    </ul>
                </div>
                """
                pdf_html = f"<html><body style='font-family: Arial;'>{legend_html}{html_result}</body></html>"
                pdf_path = exportar_a_pdf(pdf_html)
                with open(pdf_path, "rb") as f:
                    st.download_button("Descargar PDF", data=f, file_name="texto_analizado.pdf", mime="application/pdf")

    if st.sidebar.button("Cerrar Sesión"):
        st.session_state["authenticated"] = False
        st.session_state["user_email"] = ""
        st.session_state["nombre"] = ""
        st.session_state["is_admin"] = False
        st.session_state["show_admin_panel"] = False
        st.rerun()