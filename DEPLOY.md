# 🚀 Guía: Subir Hockey Manager a internet con Render

Esta guía te lleva desde tu compu hasta tener una URL pública funcionando, en ~20 minutos.

---

## 📋 Resumen del proceso

1. Subir el código a GitHub (~5 min)
2. Crear cuenta en Render (~2 min)
3. Crear base de datos PostgreSQL en Render (~3 min)
4. Conectar GitHub con Render y desplegar (~5 min)
5. Probar la URL pública (~2 min)

---

## 📦 PASO 1: Subir el código a GitHub

### 1.1 — Reemplazá los archivos con la nueva versión

Bajá el ZIP nuevo (`hockey_app_v2.zip`) y descomprimilo. Esta versión tiene 2 archivos extra (`Procfile` y un cambio mínimo en `app.py` y `requirements.txt`) que necesita Render.

**Importante**: si ya tenías una carpeta `hockey_app` con datos cargados (`hockey.db`), **copiala primero a otro lado** así no la perdés. La versión nueva la podés poner en una carpeta nueva.

### 1.2 — Crear un repositorio en GitHub

1. Andá a https://github.com y entrá a tu cuenta.
2. Arriba a la derecha, hacé clic en el **+** y elegí **"New repository"**.
3. **Repository name**: poné `hockey-manager` (o lo que quieras, sin espacios).
4. Dejalo en **"Public"** (Render gratis solo deploya desde repos públicos sin configuración extra). Si querés privado avisame.
5. **NO** marques "Add a README file", "Add .gitignore" ni "license" — el proyecto ya los trae.
6. Clic en **"Create repository"**.

Te va a aparecer una página con instrucciones. Ignorala, vamos por la opción más fácil.

### 1.3 — Subir los archivos al repo (sin usar terminal)

GitHub tiene un upload web que es la forma más simple si no usaste git nunca:

1. En la página del repo recién creado, hacé clic en **"uploading an existing file"** (es un link en el medio de la página, debajo de "Quick setup").
2. Arrastrá **TODOS los archivos y carpetas** de `hockey_app/` adentro del recuadro:
   - `app.py`
   - `Procfile`
   - `requirements.txt`
   - `README.md`
   - `.gitignore`
   - La carpeta `templates/` completa
   - La carpeta `static/` completa
3. Esperá que termine de subir todo (vas a ver una lista con los archivos).
4. Abajo, en "Commit changes", dejalo como está y hacé clic en **"Commit changes"**.

✅ Listo, tu código está en GitHub.

---

## 🌐 PASO 2: Crear cuenta en Render

1. Andá a https://render.com
2. Clic en **"Get Started"** (arriba a la derecha).
3. Elegí **"GitHub"** para registrarte (es lo más práctico, queda conectado).
4. Autorizá a Render a acceder a tu cuenta de GitHub (te va a pedir permisos).
5. Te va a llevar al dashboard. ¡Estás dentro!

---

## 🗄️ PASO 3: Crear la base de datos PostgreSQL

Antes de subir la app, necesitamos la base de datos. Render la crea sola.

1. En el dashboard de Render, clic en **"+ New"** (arriba a la derecha) → **"Postgres"**.
2. Configuración:
   - **Name**: `hockey-db`
   - **Database**: dejalo vacío (lo llena solo)
   - **User**: dejalo vacío (lo llena solo)
   - **Region**: **Oregon (US West)** o la que esté más cerca tuyo
   - **PostgreSQL Version**: dejá la que viene por defecto
   - **Plan**: **Free**
3. Clic en **"Create Database"**.
4. Esperá ~1 minuto a que diga **"Available"** en la parte de arriba.
5. **MUY IMPORTANTE**: Una vez que esté "Available", scrolleá hasta encontrar **"Internal Database URL"** y **copiala** (vas a usarla en el próximo paso). Empieza con `postgresql://...`

⚠️ La base gratuita dura **30 días**. Antes de que se venza, te aviso cómo migrar o pagar el plan ($7 USD/mes para mantenerla).

---

## 🚢 PASO 4: Desplegar la app

Ahora subimos el código.

1. En el dashboard de Render, clic en **"+ New"** → **"Web Service"**.
2. Te muestra una lista de tus repos de GitHub. Buscá **`hockey-manager`** y clic en **"Connect"**.
   - Si no aparece tu repo: clic en "Configure account" y dale acceso a Render al repo.
3. Configuración:
   - **Name**: `hockey-manager` (será parte de la URL: hockey-manager.onrender.com)
   - **Region**: la misma que elegiste para la base de datos
   - **Branch**: `main`
   - **Runtime**: **Python 3** (lo detecta solo)
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app`
   - **Plan**: **Free**
4. Bajá hasta **"Environment Variables"** y clic en **"Add Environment Variable"**:
   - Variable 1:
     - **Key**: `DATABASE_URL`
     - **Value**: pegá ahí la "Internal Database URL" que copiaste en el paso anterior
   - Variable 2:
     - **Key**: `SECRET_KEY`
     - **Value**: inventá un texto largo y random, ej: `mi-clave-secreta-hockey-2026-xyz123`
5. Clic en **"Create Web Service"** abajo de todo.

🍿 Ahora Render va a:
- Descargar tu código de GitHub
- Instalar las dependencias
- Arrancar la app

Esto tarda **3-5 minutos la primera vez**. Vas a ver logs en pantalla. Cuando aparezca **"Your service is live 🎉"** o **"Deploy succeeded"**, está listo.

---

## ✅ PASO 5: Probar la URL pública

Arriba a la izquierda vas a ver la URL de tu app, algo como:

**https://hockey-manager.onrender.com**

(Será diferente si elegiste otro nombre)

1. Clic en esa URL.
2. Te abre la pantalla de login de tu app, ¡pero ahora online!
3. Hacé clic en "Registrate acá" y creá tu cuenta de entrenador.
4. Cargá una jugadora de prueba.

🎉 **¡Tu app está en internet!** Podés:
- Abrirla desde el celular
- Compartir el link con otros entrenadores
- Usarla desde cualquier compu

---

## 📱 Tip: Agregarla al celular como app

En Chrome/Safari del celu, abrí la URL → menú → **"Agregar a pantalla de inicio"**. Te queda como un ícono igual a una app nativa.

---

## 🔄 Cómo actualizar la app después

Cuando agreguemos funcionalidades nuevas (categorías, notas, estadísticas), el flujo es:

1. Yo te paso los archivos modificados.
2. Vos los subís al repo de GitHub (mismo método: arrastrar y dropear).
3. Render detecta el cambio **automáticamente** y redesplega solo. En 2-3 minutos tu app online tiene los cambios.

---

## ⚠️ Cosas a tener en cuenta del plan gratis

1. **La app duerme después de 15 minutos sin uso**. La primera persona que la abra después de un rato espera ~30 segundos a que despierte. Después funciona normal.
2. **La base PostgreSQL gratis dura 30 días**. Después hay que renovarla o pasar a un plan pago ($7/mes la base + $7/mes el web service = ~$14 USD/mes). Antes de que se venza te aviso y vemos qué hacer.
3. **750 horas de uso al mes incluidas**. Más que suficiente para empezar.

---

## ❓ Si algo falla

Pegame el error exacto que ves en pantalla (o sacale captura) y lo resolvemos. Los lugares donde puede fallar son:
- Logs del deploy en Render (pestaña "Logs" del web service)
- La URL no carga después de "Deploy succeeded"
- Error al registrarte (probablemente la base de datos no se conectó bien)

Avisame cuando esté funcionando o si te trabás en algún paso. 🏑
