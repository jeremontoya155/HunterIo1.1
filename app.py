from flask import Flask, render_template, request, redirect, url_for, session, flash
from instagrapi import Client
import schedule
import time
import threading
import openai
import os
import random

app = Flask(__name__)
app.secret_key = os.getenv("API_KEY")  # Necesaria para manejar sesiones y mensajes flash

# Configuración del proxy SOCKS5
PROXY = os.getenv("PROXY")

# Variables globales
cliente = None
seguidores = []
MENSAJES_POR_HORA = 25  # Ajustado para enviar 150 mensajes en 6 horas
TOTAL_MENSAJES = 150    # Total de mensajes a enviar
DURACION_HORAS = 6      # Duración en horas para enviar los mensajes

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

        if cliente == "challenge_required":
            flash("Se requiere resolver un challenge de seguridad. Por favor, revisa tu correo o teléfono.")
            return redirect(url_for("challenge"))
        elif cliente:
            return redirect(url_for("inicio_exitoso"))
        else:
            flash("Error al iniciar sesión. Verifica tus credenciales.")
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
            flash("Error al verificar el código de 2FA. Intenta nuevamente.")
            return redirect(url_for("verificacion_2fa"))

    return render_template("verificacion_2fa.html")

# Ruta para manejar el challenge de Instagram
@app.route("/challenge", methods=["GET", "POST"])
def challenge():
    if request.method == "POST":
        codigo_challenge = request.form["codigo_challenge"]
        global cliente

        try:
            # Resolver el challenge con el código proporcionado
            cliente.challenge_resolve(codigo_challenge)
            return redirect(url_for("inicio_exitoso"))
        except Exception as e:
            flash(f"Error al resolver el challenge: {e}")
            return redirect(url_for("challenge"))

    return render_template("challenge.html")

# Ruta para inicio de sesión exitoso
@app.route("/inicio_exitoso")
def inicio_exitoso():
    global cliente, seguidores

    if not cliente:
        flash("Error: No hay sesión activa en Instagram.")
        return redirect(url_for("index"))

    competencias = [cuenta.strip() for cuenta in session["competencias"].split(",")]
    
    seguidores_temp = []
    for competencia in competencias:
        seguidores_temp += obtener_seguidores(cliente, competencia)

    if not seguidores_temp:
        flash("No se pudieron obtener seguidores. Verifica las cuentas de competencia o revisa tu conexión.")
        return redirect(url_for("index"))

    seguidores = seguidores_temp  # Asigna la lista solo si tiene datos
    print(f"Se encontraron {len(seguidores)} seguidores en total.")

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
        elif "challenge_required" in str(e):
            return "challenge_required"  # Indicar que se requiere un challenge
        else:
            print(f"Error al iniciar sesión: {e}")
            return None

# Función para obtener seguidores de una cuenta
def obtener_seguidores(cl, username):
    try:
        print(f"🔍 Obteniendo seguidores de: {username}")
        user_id = cl.user_id_from_username(username)
        seguidores = cl.user_followers(user_id, amount=10)
        return list(seguidores.keys())
    except Exception as e:
        print(f"⚠️ Error al obtener seguidores de {username}: {e}")
        return []

# Función para obtener la descripción del perfil y nombre real
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
    Evita repetir frases idénticas y asegúrate de que el mensaje sea único.
    """

    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "Eres un asistente que genera mensajes personalizados para redes sociales."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.9,  # Aumenta la temperatura para mayor variación
            max_tokens=100
        )
        return response["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"⚠️ Error al generar mensaje: {e}")
        return mensaje_aleatorio

# Función para enviar mensajes
def enviar_mensajes():
    global cliente, seguidores

    if not cliente or not seguidores:
        print("⚠️ No hay seguidores para enviar mensajes.")
        return

    mensajes_enviados = 0
    for user_id in seguidores:
        if mensajes_enviados >= MENSAJES_POR_HORA:
            break

        nombre, descripcion = obtener_info_usuario(cliente, user_id)
        if not descripcion:
            continue  # Si el usuario no tiene biografía, lo salta

        mensaje = generar_mensaje_personalizado(nombre, descripcion)

        try:
            cliente.direct_send(mensaje, user_ids=[user_id])
            print(f"✅ Mensaje enviado a {nombre}: {mensaje}")
            mensajes_enviados += 1

            # Añadir un retraso aleatorio entre 2 y 5 minutos
            tiempo_espera = random.randint(120, 300)  # 2 a 5 minutos en segundos
            print(f"⏳ Esperando {tiempo_espera // 60} minutos antes del próximo mensaje...")
            time.sleep(tiempo_espera)

        except Exception as e:
            print(f"⚠️ Error al enviar mensaje a {nombre}: {e}")
            if "rate limit" in str(e).lower():
                print("⏳ Límite de tasa alcanzado. Esperando 1 hora antes de reintentar...")
                time.sleep(3600)  # Esperar 1 hora antes de reintentar
            continue

    print(f"📩 Se enviaron {mensajes_enviados} mensajes.")

# Función para simular actividad adicional
def simular_actividad(cliente):
    try:
        # Dar like a algunas publicaciones
        publicaciones = cliente.user_medias(cliente.user_id, amount=5)
        for media in publicaciones:
            cliente.media_like(media.id)
            print(f"👍 Like dado a la publicación {media.id}")

        # Comentar una publicación
        if publicaciones:
            comentario = "¡Muy buen contenido! 😊"
            cliente.media_comment(publicaciones[0].id, comentario)
            print(f"💬 Comentario publicado: {comentario}")

    except Exception as e:
        print(f"⚠️ Error al simular actividad: {e}")

# Función para programar tareas
def programar_tareas():
    schedule.clear()
    enviar_mensajes()  # Ejecutar el primer envío inmediatamente
    simular_actividad(cliente)  # Simular actividad adicional

    for hora in range(DURACION_HORAS):
        schedule.every(hora + 1).hours.do(enviar_mensajes)
        schedule.every(hora + 1).hours.do(simular_actividad, cliente)

    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)