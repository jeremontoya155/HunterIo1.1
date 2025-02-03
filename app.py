from flask import Flask, render_template, request, redirect, url_for, session
from instagrapi import Client
import schedule
import time
import threading
import openai
import os
import random
from collections import deque

app = Flask(__name__)
app.secret_key = "una_clave_secreta_muy_segura"  # Necesaria para manejar sesiones

# Configuración del proxy SOCKS5
PROXY = os.getenv("PROXY")

# Variables globales
cliente = None
seguidores_queue = deque()
MENSAJES_POR_HORA = 10
TOTAL_MENSAJES = 40
DURACION_HORAS = 6

# Archivos de mensajes y base de conocimiento
MENSAJES_FILE = "mensajes.txt"
BASE_CONOCIMIENTO_FILE = "base_conocimiento.txt"

# Configuración de OpenAI
openai.api_key = os.getenv("OPENAI_API_KEY")  # Clave desde .env

# Ruta principal: formulario para ingresar credenciales
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        session["username"] = request.form["username"]
        session["password"] = request.form["password"]
        session["competencias"] = request.form["competencias"]

        global cliente
        cliente = iniciar_sesion(session["username"], session["password"])

        if cliente:
            return redirect(url_for("inicio_exitoso"))
        else:
            return redirect(url_for("verificacion_2fa"))

    return render_template("index.html")

# Ruta para verificación de 2FA
@app.route("/verificacion_2fa", methods=["GET", "POST"])
def verificacion_2fa():
    if request.method == "POST":
        codigo_2fa = request.form["codigo_2fa"]
        global cliente
        cliente = iniciar_sesion(session["username"], session["password"], codigo_2fa)

        if cliente:
            return redirect(url_for("inicio_exitoso"))
        else:
            return "Error al verificar el código de 2FA. Intenta nuevamente."

    return render_template("verificacion_2fa.html")

# Ruta para inicio de sesión exitoso
@app.route("/inicio_exitoso")
def inicio_exitoso():
    global cliente, seguidores_queue

    if not cliente:
        return "Error: No hay sesión activa en Instagram."

    competencias = [cuenta.strip() for cuenta in session["competencias"].split(",")]
    
    nuevos_seguidores = []
    for competencia in competencias:
        nuevos_seguidores += obtener_seguidores(cliente, competencia)

    if not nuevos_seguidores:
        return "No se pudieron obtener seguidores."

    # Agregar nuevos seguidores a la cola sin repetir
    for seguidor in nuevos_seguidores:
        if seguidor not in seguidores_queue:
            seguidores_queue.append(seguidor)

    print(f"Se agregaron {len(nuevos_seguidores)} seguidores a la cola.")

    # Iniciar el programador de tareas en un hilo separado
    threading.Thread(target=programar_tareas, daemon=True).start()

    return "Inicio de sesión exitoso. El script está en ejecución y enviando mensajes."

# Función para iniciar sesión en Instagram
def iniciar_sesion(username, password, codigo_2fa=None):
    cl = Client()
    cl.set_proxy(PROXY)

    try:
        if codigo_2fa:
            cl.login(username, password, verification_code=codigo_2fa)
        else:
            cl.login(username, password)
        return cl
    except Exception as e:
        if "Two-factor authentication required" in str(e):
            return None  # Indicar que se requiere 2FA
        else:
            print(f"Error al iniciar sesión: {e}")
            return None

# Función para obtener seguidores de una cuenta
def obtener_seguidores(cl, username):
    try:
        print(f"🔍 Obteniendo seguidores de: {username}")
        user_id = cl.user_id_from_username(username)
        seguidores = cl.user_followers(user_id, amount=40)  # Carga 40 seguidores por cuenta
        return list(seguidores.keys())
    except Exception as e:
        print(f"⚠️ Error al obtener seguidores de {username}: {e}")
        return []

# Función para obtener la descripción del perfil
def obtener_info_usuario(cl, user_id):
    try:
        user_info = cl.user_info(user_id)
        nombre_real = user_info.full_name if user_info.full_name else user_info.username
        biografia = user_info.biography
        return nombre_real, biografia
    except Exception as e:
        print(f"⚠️ Error al obtener info de {user_id}: {e}")
        return None, None

# Función para cargar mensajes desde archivo
def cargar_mensajes():
    try:
        with open(MENSAJES_FILE, "r", encoding="utf-8") as f:
            mensajes = [line.strip() for line in f if line.strip()]
        return mensajes
    except Exception as e:
        print(f"⚠️ Error al cargar mensajes: {e}")
        return []

# Función para cargar base de conocimiento
def cargar_base_conocimiento():
    try:
        with open(BASE_CONOCIMIENTO_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception as e:
        print(f"⚠️ Error al cargar base de conocimiento: {e}")
        return ""

# Función para generar mensaje con OpenAI
def generar_mensaje_personalizado(nombre, descripcion):
    mensajes = cargar_mensajes()
    base_conocimiento = cargar_base_conocimiento()

    mensaje_aleatorio = random.choice(mensajes) if mensajes else "Hola, ¿cómo estás?"

    prompt = f"""
    Contexto:
    {base_conocimiento}

    Perfil de usuario:
    Nombre: {nombre}
    Descripción: {descripcion}

    Mensaje sugerido:
    '{mensaje_aleatorio}'

    Basado en la base de conocimiento y el mensaje sugerido, genera un mensaje personalizado y natural para esta persona.
    """

    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "Eres un asistente que genera mensajes personalizados para redes sociales."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=100
        )
        return response["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"⚠️ Error al generar mensaje: {e}")
        return mensaje_aleatorio

# Función para enviar mensajes
def enviar_mensajes():
    global cliente, seguidores_queue

    if not cliente or not seguidores_queue:
        print("⚠️ No hay seguidores pendientes.")
        return

    mensajes_enviados = 0
    while seguidores_queue and mensajes_enviados < MENSAJES_POR_HORA:
        user_id = seguidores_queue.popleft()
        nombre, descripcion = obtener_info_usuario(cliente, user_id)

        if not descripcion:
            continue  # Si el usuario no tiene biografía, lo omite

        mensaje = generar_mensaje_personalizado(nombre, descripcion)

        try:
            cliente.direct_send(mensaje, user_ids=[user_id])
            print(f"✅ Mensaje enviado a {nombre}: {mensaje}")
            mensajes_enviados += 1
        except Exception as e:
            print(f"⚠️ Error al enviar mensaje a {nombre}: {e}")

    print(f"📩 Se enviaron {mensajes_enviados} mensajes.")

# Programador de tareas
def programar_tareas():
    schedule.clear()
    enviar_mensajes()  # Ejecutar el primer envío inmediatamente

    for hora in range(DURACION_HORAS):
        schedule.every(hora + 1).hours.do(enviar_mensajes)

    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
