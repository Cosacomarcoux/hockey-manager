# 🏑 Hockey Manager

App web para entrenadores de hockey sobre césped. Gestión de plantel, asistencias y porcentajes.

## ✨ Qué hace

- **Cuentas de entrenador**: cada entrenador tiene su propio plantel privado
- **Plantel**: nombre, apellido, apodo, fecha de nacimiento, posición preferida y alternativa, calificación 1-5
- **Asistencia**: por fecha, marca Presente / Ausente / Justificada (cuenta solo desde la fecha de inscripción)
- **% Asistencia automático**: por jugadora y promedio del plantel
- **Ranking**: jugadoras ordenadas por % de asistencia
- **Historial**: todas las planillas de entrenamiento

---

## 🚀 Instrucciones paso a paso para correr la app en tu compu

### Paso 1: Instalar Python

Si no tenés Python instalado:

- **Windows**: Andá a [python.org/downloads](https://www.python.org/downloads/), descargá Python 3.11 o más nuevo. **MUY IMPORTANTE**: durante la instalación, marcá la casilla **"Add Python to PATH"**.
- **Mac**: Abrí la app **Terminal** y escribí `python3 --version`. Si aparece un número (ej: 3.11.5), ya lo tenés. Si no, instalalo desde [python.org](https://www.python.org/downloads/).

### Paso 2: Descargar el proyecto

Descomprimí el archivo `hockey_app.zip` que te paso. Vas a tener una carpeta llamada `hockey_app` con todos los archivos adentro.

Guardala en un lugar fácil de encontrar, por ejemplo en el Escritorio.

### Paso 3: Abrir la terminal en la carpeta del proyecto

- **Windows**: Abrí la carpeta `hockey_app` en el explorador, hacé clic en la barra de direcciones (donde dice la ruta), borrá lo que esté y escribí `cmd`, después apretá Enter. Se va a abrir una ventana negra (la terminal).
- **Mac**: Abrí la app **Terminal**, escribí `cd ` (con espacio al final) y arrastrá la carpeta `hockey_app` adentro de la terminal. Apretá Enter.

### Paso 4: Crear un entorno virtual (esto aísla las dependencias del proyecto)

Copiá y pegá este comando en la terminal:

**Windows:**
```
python -m venv venv
venv\Scripts\activate
```

**Mac:**
```
python3 -m venv venv
source venv/bin/activate
```

Si todo salió bien, vas a ver `(venv)` al principio de la línea de la terminal.

### Paso 5: Instalar las dependencias

```
pip install -r requirements.txt
```

Esto descarga Flask y todo lo necesario. Tarda 30 segundos.

### Paso 6: Correr la app

```
python app.py
```

Vas a ver algo así:
```
 * Running on http://127.0.0.1:5000
 * Debug mode: on
```

### Paso 7: Abrir en el navegador

Abrí Chrome (o tu navegador favorito) y andá a:

**http://127.0.0.1:5000**

¡Listo! Te aparece la pantalla de login. Hacé clic en **"Registrate acá"**, creá tu cuenta y empezá a cargar jugadoras.

---

## 🔁 Próximas veces que quieras usar la app

Cuando cierres la terminal o reinicies la compu, para volver a abrir la app:

1. Abrí la terminal en la carpeta `hockey_app` (ver Paso 3).
2. Activá el entorno virtual:
   - Windows: `venv\Scripts\activate`
   - Mac: `source venv/bin/activate`
3. Corré: `python app.py`
4. Abrí http://127.0.0.1:5000

---

## 🛑 Para cerrar la app

En la terminal donde está corriendo, apretá `Ctrl + C`.

---

## ❓ Problemas comunes

**"python no se reconoce como comando"** (Windows): No marcaste "Add Python to PATH" al instalar. Reinstalá Python y marcá esa casilla.

**"pip no se reconoce"**: Lo mismo, reinstalá Python con la opción correcta.

**Olvidé la contraseña**: Por ahora la app no tiene recuperación de contraseña. Como vos sos el dueño de la base de datos (archivo `hockey.db`), podemos resetearla manualmente (preguntale a Claude).

**No se me abre la página**: Asegurate de que la terminal sigue corriendo y dice "Running on...". Si se cerró, repetí el Paso 6.

---

## 📁 Estructura del proyecto

```
hockey_app/
├── app.py                # Lógica principal (Python/Flask)
├── requirements.txt      # Dependencias
├── hockey.db             # Base de datos (se crea sola al primer uso)
├── templates/            # Páginas HTML
│   ├── base.html
│   ├── login.html
│   ├── registro.html
│   ├── plantel.html
│   ├── jugadora_form.html
│   ├── asistencia.html
│   └── historial.html
└── static/
    └── style.css         # Estilos visuales
```

---

## 🌐 Próximo paso: subirlo a internet

Cuando lo tengas funcionando local, le decimos a Claude que lo subimos a Render (gratis) y te queda con una URL pública para usar desde cualquier celular o compartir con otros entrenadores.
