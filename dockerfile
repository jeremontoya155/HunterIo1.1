# Usa la imagen base oficial de Python
FROM python:3.11-slim

# Establece el directorio de trabajo en el contenedor
WORKDIR /app

# Copia el archivo de dependencias
COPY requirements.txt .

# Actualiza pip a la última versión
RUN pip install --upgrade pip

# Instala las dependencias especificadas en requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copia el resto de los archivos de la aplicación
COPY . .

# Establece la variable de entorno FLASK_APP
ENV FLASK_APP=app.py

# Expone el puerto 5000
EXPOSE 5000

# Comando para ejecutar la aplicación Flask
CMD ["flask", "run", "--host=0.0.0.0"]