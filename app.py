"""
Hockey Team Manager - App para entrenadores de hockey sobre césped
Fase 1: Plantel, asistencias y porcentajes con login multi-usuario
"""
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date
from functools import wraps
import os

# ============================================================
# CONFIGURACIÓN
# ============================================================
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'cambiar-esta-clave-en-produccion-12345')

# Compatibilidad con Render: convierte 'postgres://' a 'postgresql://'
database_url = os.environ.get('DATABASE_URL', 'sqlite:///hockey.db')
if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

POSICIONES = ['Arquera', 'Defensora', 'Mediocampista', 'Volante', 'Delantera']

# ============================================================
# MODELOS DE BASE DE DATOS
# ============================================================
class Entrenador(db.Model):
    """Cada entrenador es un usuario que tiene su propio plantel."""
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    nombre = db.Column(db.String(80), nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    creado = db.Column(db.DateTime, default=datetime.utcnow)

    jugadoras = db.relationship('Jugadora', backref='entrenador', lazy=True, cascade='all, delete-orphan')
    sesiones = db.relationship('Sesion', backref='entrenador', lazy=True, cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Jugadora(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    entrenador_id = db.Column(db.Integer, db.ForeignKey('entrenador.id'), nullable=False)
    nombre = db.Column(db.String(80), nullable=False)
    apellido = db.Column(db.String(80), nullable=False)
    apodo = db.Column(db.String(50))
    fecha_nacimiento = db.Column(db.Date)
    posicion = db.Column(db.String(30), nullable=False)
    posicion_alt = db.Column(db.String(30))
    calificacion = db.Column(db.Integer, default=3)
    fecha_inscripcion = db.Column(db.Date, default=date.today, nullable=False)
    creada = db.Column(db.DateTime, default=datetime.utcnow)

    asistencias = db.relationship('Asistencia', backref='jugadora', lazy=True, cascade='all, delete-orphan')

    @property
    def edad(self):
        if not self.fecha_nacimiento:
            return None
        hoy = date.today()
        return hoy.year - self.fecha_nacimiento.year - (
            (hoy.month, hoy.day) < (self.fecha_nacimiento.month, self.fecha_nacimiento.day)
        )

    @property
    def iniciales(self):
        return (self.nombre[0] + self.apellido[0]).upper()

    def stats_asistencia(self):
        """Calcula % asistencia desde fecha de inscripción en adelante."""
        registros = [a for a in self.asistencias if a.sesion.fecha >= self.fecha_inscripcion]
        presentes = sum(1 for a in registros if a.estado == 'P')
        ausentes = sum(1 for a in registros if a.estado == 'A')
        justificadas = sum(1 for a in registros if a.estado == 'J')
        total = presentes + ausentes + justificadas
        pct = round((presentes / total) * 100) if total > 0 else 0
        return {
            'pct': pct,
            'presentes': presentes,
            'ausentes': ausentes,
            'justificadas': justificadas,
            'total': total
        }


class Sesion(db.Model):
    """Una sesión = un día de entrenamiento donde se tomó asistencia."""
    id = db.Column(db.Integer, primary_key=True)
    entrenador_id = db.Column(db.Integer, db.ForeignKey('entrenador.id'), nullable=False)
    fecha = db.Column(db.Date, nullable=False)
    notas = db.Column(db.Text)
    creada = db.Column(db.DateTime, default=datetime.utcnow)

    asistencias = db.relationship('Asistencia', backref='sesion', lazy=True, cascade='all, delete-orphan')

    __table_args__ = (db.UniqueConstraint('entrenador_id', 'fecha', name='_entrenador_fecha_uc'),)


class Asistencia(db.Model):
    """Registro: en tal sesión, tal jugadora estuvo Presente/Ausente/Justificada."""
    id = db.Column(db.Integer, primary_key=True)
    sesion_id = db.Column(db.Integer, db.ForeignKey('sesion.id'), nullable=False)
    jugadora_id = db.Column(db.Integer, db.ForeignKey('jugadora.id'), nullable=False)
    estado = db.Column(db.String(1), nullable=False)  # P, A o J

    __table_args__ = (db.UniqueConstraint('sesion_id', 'jugadora_id', name='_sesion_jugadora_uc'),)


# ============================================================
# MODELOS DE PARTIDOS
# ============================================================
class Partido(db.Model):
    """Un partido contra un rival."""
    id = db.Column(db.Integer, primary_key=True)
    entrenador_id = db.Column(db.Integer, db.ForeignKey('entrenador.id'), nullable=False)
    rival = db.Column(db.String(120), nullable=False)
    fecha = db.Column(db.Date, nullable=False)
    lugar = db.Column(db.String(20), default='Local')  # Local / Visitante / Neutral

    # Estado del partido: 'pendiente' (sin jugar), 'en_curso' (jugándose), 'finalizado'
    estado = db.Column(db.String(20), default='pendiente')

    # Cuarto actual: 1, 2, 3, 4 (o 0 si todavía no arrancó)
    cuarto_actual = db.Column(db.Integer, default=0)

    # Cronómetro: segundos transcurridos del cuarto actual
    cronometro_segundos = db.Column(db.Integer, default=0)

    # Si está corriendo el cronómetro, guardamos cuándo arrancó (para calcular tiempo real)
    cronometro_iniciado = db.Column(db.DateTime)  # null si está pausado

    # Resultado
    goles_favor = db.Column(db.Integer, default=0)
    goles_contra = db.Column(db.Integer, default=0)

    notas = db.Column(db.Text)
    creado = db.Column(db.DateTime, default=datetime.utcnow)

    convocadas = db.relationship('ConvocatoriaPartido', backref='partido', lazy=True, cascade='all, delete-orphan')
    eventos = db.relationship('EventoPartido', backref='partido', lazy=True, cascade='all, delete-orphan',
                              order_by='EventoPartido.cuarto, EventoPartido.minuto, EventoPartido.id')

    @property
    def resultado_str(self):
        if self.estado == 'pendiente':
            return 'Sin jugar'
        return f'{self.goles_favor} - {self.goles_contra}'

    @property
    def cronometro_actual(self):
        """Devuelve segundos actuales del cronómetro (calculando si está corriendo)."""
        if self.cronometro_iniciado:
            delta = (datetime.utcnow() - self.cronometro_iniciado).total_seconds()
            return self.cronometro_segundos + int(delta)
        return self.cronometro_segundos


class ConvocatoriaPartido(db.Model):
    """Jugadora convocada a un partido."""
    id = db.Column(db.Integer, primary_key=True)
    partido_id = db.Column(db.Integer, db.ForeignKey('partido.id'), nullable=False)
    jugadora_id = db.Column(db.Integer, db.ForeignKey('jugadora.id'), nullable=False)

    # Estado durante el partido en vivo
    en_cancha = db.Column(db.Boolean, default=False)

    # Tiempo total jugado (en segundos)
    segundos_jugados = db.Column(db.Integer, default=0)

    # Cuándo entró a cancha por última vez (para ir sumando tiempo)
    ultimo_ingreso = db.Column(db.DateTime)

    jugadora = db.relationship('Jugadora')

    __table_args__ = (db.UniqueConstraint('partido_id', 'jugadora_id', name='_partido_jugadora_uc'),)

    @property
    def minutos_jugados(self):
        """Calcula minutos totales (incluyendo si está en cancha ahora)."""
        total_seg = self.segundos_jugados
        if self.en_cancha and self.ultimo_ingreso and self.partido.cronometro_iniciado:
            # Sumar tiempo desde el último ingreso (solo si el reloj está corriendo)
            delta = (datetime.utcnow() - max(self.ultimo_ingreso, self.partido.cronometro_iniciado)).total_seconds()
            total_seg += int(delta)
        return total_seg // 60

    @property
    def tiempo_str(self):
        total_seg = self.segundos_jugados
        if self.en_cancha and self.ultimo_ingreso and self.partido.cronometro_iniciado:
            delta = (datetime.utcnow() - max(self.ultimo_ingreso, self.partido.cronometro_iniciado)).total_seconds()
            total_seg += int(delta)
        m = total_seg // 60
        s = total_seg % 60
        return f"{m}:{s:02d}"


class EventoPartido(db.Model):
    """Un evento durante el partido: gol, sustitución, etc."""
    id = db.Column(db.Integer, primary_key=True)
    partido_id = db.Column(db.Integer, db.ForeignKey('partido.id'), nullable=False)

    tipo = db.Column(db.String(30), nullable=False)
    # gol_favor, gol_contra, ataque_favor, ataque_contra,
    # tiro_favor, tiro_contra, corner_favor, corner_contra,
    # entrada, salida, nota

    # Subtipo (solo para goles): 'jugada', 'corner_corto', 'penal'
    subtipo = db.Column(db.String(20))

    cuarto = db.Column(db.Integer, nullable=False)
    minuto = db.Column(db.Integer, nullable=False)  # minuto del cuarto (0-15+)
    segundo = db.Column(db.Integer, default=0)

    jugadora_id = db.Column(db.Integer, db.ForeignKey('jugadora.id'))
    detalle = db.Column(db.String(200))

    creado = db.Column(db.DateTime, default=datetime.utcnow)

    jugadora = db.relationship('Jugadora')

    @property
    def tiempo_str(self):
        return f"Q{self.cuarto} - {self.minuto:02d}:{self.segundo:02d}"

    @property
    def descripcion(self):
        # Texto del subtipo para goles
        sub = ''
        if self.subtipo == 'jugada':
            sub = ' (de jugada)'
        elif self.subtipo == 'corner_corto':
            sub = ' (de córner corto)'
        elif self.subtipo == 'penal':
            sub = ' (de penal)'

        if self.tipo == 'gol_favor':
            nombre = f"{self.jugadora.nombre} {self.jugadora.apellido}" if self.jugadora else "Sin asignar"
            return f"🏑 Gol a favor — {nombre}{sub}"
        if self.tipo == 'gol_contra':
            return f"❌ Gol en contra{sub}"
        if self.tipo == 'ataque_favor':
            return "🟢 Ataque a favor"
        if self.tipo == 'ataque_contra':
            return "🔴 Ataque en contra"
        if self.tipo == 'tiro_favor':
            return "🎯 Tiro al arco a favor"
        if self.tipo == 'tiro_contra':
            return "🛡️ Tiro al arco en contra"
        if self.tipo == 'corner_favor':
            return "🚩 Córner corto a favor"
        if self.tipo == 'corner_contra':
            return "⚠️ Córner corto en contra"
        if self.tipo == 'entrada':
            return f"🔼 Ingresa: {self.jugadora.nombre} {self.jugadora.apellido}"
        if self.tipo == 'salida':
            return f"🔽 Sale: {self.jugadora.nombre} {self.jugadora.apellido}"
        if self.tipo == 'nota':
            return f"📝 {self.detalle}"
        return self.tipo


# ============================================================
# RELACIÓN DE ENTRENADOR → PARTIDOS
# ============================================================
Entrenador.partidos = db.relationship('Partido', backref='entrenador', lazy=True, cascade='all, delete-orphan')


# ============================================================
# DECORADOR PARA RUTAS PROTEGIDAS
# ============================================================
def login_requerido(f):
    @wraps(f)
    def decorada(*args, **kwargs):
        if 'entrenador_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorada


def entrenador_actual():
    if 'entrenador_id' not in session:
        return None
    return Entrenador.query.get(session['entrenador_id'])


# ============================================================
# RUTAS DE AUTENTICACIÓN
# ============================================================
@app.route('/')
def index():
    if 'entrenador_id' in session:
        return redirect(url_for('plantel'))
    return redirect(url_for('login'))


@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        nombre = request.form.get('nombre', '').strip()
        password = request.form.get('password', '')

        if not email or not nombre or not password:
            flash('Todos los campos son obligatorios', 'error')
            return render_template('registro.html')

        if len(password) < 6:
            flash('La contraseña debe tener al menos 6 caracteres', 'error')
            return render_template('registro.html')

        if Entrenador.query.filter_by(email=email).first():
            flash('Ese email ya está registrado', 'error')
            return render_template('registro.html')

        entrenador = Entrenador(email=email, nombre=nombre)
        entrenador.set_password(password)
        db.session.add(entrenador)
        db.session.commit()

        session['entrenador_id'] = entrenador.id
        flash(f'¡Bienvenido {nombre}!', 'success')
        return redirect(url_for('plantel'))

    return render_template('registro.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        entrenador = Entrenador.query.filter_by(email=email).first()
        if entrenador and entrenador.check_password(password):
            session['entrenador_id'] = entrenador.id
            return redirect(url_for('plantel'))

        flash('Email o contraseña incorrectos', 'error')

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ============================================================
# RUTAS DEL PLANTEL
# ============================================================
@app.route('/plantel')
@login_requerido
def plantel():
    entrenador = entrenador_actual()
    jugadoras = Jugadora.query.filter_by(entrenador_id=entrenador.id).order_by(Jugadora.apellido).all()

    # Stats generales
    stats_jugadoras = [(j, j.stats_asistencia()) for j in jugadoras]
    total_jug = len(jugadoras)
    total_sesiones = Sesion.query.filter_by(entrenador_id=entrenador.id).count()
    pct_promedio = round(
        sum(s['pct'] for _, s in stats_jugadoras) / total_jug
    ) if total_jug > 0 else 0

    # Ranking (solo las que tienen asistencias registradas)
    ranking = sorted(
        [(j, s) for j, s in stats_jugadoras if s['total'] > 0],
        key=lambda x: x[1]['pct'],
        reverse=True
    )

    return render_template(
        'plantel.html',
        entrenador=entrenador,
        stats_jugadoras=stats_jugadoras,
        total_jug=total_jug,
        total_sesiones=total_sesiones,
        pct_promedio=pct_promedio,
        ranking=ranking,
        posiciones=POSICIONES
    )


@app.route('/jugadora/nueva', methods=['GET', 'POST'])
@login_requerido
def jugadora_nueva():
    entrenador = entrenador_actual()
    if request.method == 'POST':
        try:
            fecha_nac = request.form.get('fecha_nacimiento') or None
            fecha_nac = datetime.strptime(fecha_nac, '%Y-%m-%d').date() if fecha_nac else None
            fecha_insc = request.form.get('fecha_inscripcion') or date.today().isoformat()
            fecha_insc = datetime.strptime(fecha_insc, '%Y-%m-%d').date()

            jugadora = Jugadora(
                entrenador_id=entrenador.id,
                nombre=request.form.get('nombre', '').strip(),
                apellido=request.form.get('apellido', '').strip(),
                apodo=request.form.get('apodo', '').strip() or None,
                fecha_nacimiento=fecha_nac,
                posicion=request.form.get('posicion'),
                posicion_alt=request.form.get('posicion_alt') or None,
                calificacion=int(request.form.get('calificacion', 3)),
                fecha_inscripcion=fecha_insc
            )

            if not jugadora.nombre or not jugadora.apellido:
                flash('Nombre y apellido son obligatorios', 'error')
                return render_template('jugadora_form.html', jugadora=None, posiciones=POSICIONES, entrenador=entrenador, fecha_hoy=date.today().isoformat())

            db.session.add(jugadora)
            db.session.commit()
            flash(f'{jugadora.nombre} {jugadora.apellido} agregada al plantel', 'success')
            return redirect(url_for('plantel'))
        except Exception as e:
            flash(f'Error al guardar: {str(e)}', 'error')

    return render_template('jugadora_form.html', jugadora=None, posiciones=POSICIONES, entrenador=entrenador, fecha_hoy=date.today().isoformat())


@app.route('/jugadora/<int:jugadora_id>/editar', methods=['GET', 'POST'])
@login_requerido
def jugadora_editar(jugadora_id):
    entrenador = entrenador_actual()
    jugadora = Jugadora.query.filter_by(id=jugadora_id, entrenador_id=entrenador.id).first_or_404()

    if request.method == 'POST':
        try:
            fecha_nac = request.form.get('fecha_nacimiento') or None
            jugadora.fecha_nacimiento = datetime.strptime(fecha_nac, '%Y-%m-%d').date() if fecha_nac else None
            fecha_insc = request.form.get('fecha_inscripcion')
            jugadora.fecha_inscripcion = datetime.strptime(fecha_insc, '%Y-%m-%d').date()
            jugadora.nombre = request.form.get('nombre', '').strip()
            jugadora.apellido = request.form.get('apellido', '').strip()
            jugadora.apodo = request.form.get('apodo', '').strip() or None
            jugadora.posicion = request.form.get('posicion')
            jugadora.posicion_alt = request.form.get('posicion_alt') or None
            jugadora.calificacion = int(request.form.get('calificacion', 3))

            db.session.commit()
            flash('Jugadora actualizada', 'success')
            return redirect(url_for('plantel'))
        except Exception as e:
            flash(f'Error: {str(e)}', 'error')

    return render_template('jugadora_form.html', jugadora=jugadora, posiciones=POSICIONES, entrenador=entrenador, fecha_hoy=date.today().isoformat())


@app.route('/jugadora/<int:jugadora_id>/eliminar', methods=['POST'])
@login_requerido
def jugadora_eliminar(jugadora_id):
    entrenador = entrenador_actual()
    jugadora = Jugadora.query.filter_by(id=jugadora_id, entrenador_id=entrenador.id).first_or_404()
    nombre_completo = f'{jugadora.nombre} {jugadora.apellido}'
    db.session.delete(jugadora)
    db.session.commit()
    flash(f'{nombre_completo} eliminada del plantel', 'success')
    return redirect(url_for('plantel'))


# ============================================================
# RUTAS DE ASISTENCIA
# ============================================================
@app.route('/asistencia', methods=['GET'])
@login_requerido
def asistencia():
    entrenador = entrenador_actual()
    fecha_str = request.args.get('fecha', date.today().isoformat())
    try:
        fecha_sesion = datetime.strptime(fecha_str, '%Y-%m-%d').date()
    except ValueError:
        fecha_sesion = date.today()

    # Buscar o crear sesión virtual (no se guarda hasta que marquen al menos una)
    sesion = Sesion.query.filter_by(entrenador_id=entrenador.id, fecha=fecha_sesion).first()

    # Solo jugadoras inscriptas hasta esa fecha
    jugadoras_elegibles = Jugadora.query.filter(
        Jugadora.entrenador_id == entrenador.id,
        Jugadora.fecha_inscripcion <= fecha_sesion
    ).order_by(Jugadora.apellido).all()

    # Mapa de asistencias actuales
    estados = {}
    if sesion:
        for a in sesion.asistencias:
            estados[a.jugadora_id] = a.estado

    contadores = {
        'P': sum(1 for j in jugadoras_elegibles if estados.get(j.id) == 'P'),
        'A': sum(1 for j in jugadoras_elegibles if estados.get(j.id) == 'A'),
        'J': sum(1 for j in jugadoras_elegibles if estados.get(j.id) == 'J'),
    }
    contadores['pendientes'] = len(jugadoras_elegibles) - contadores['P'] - contadores['A'] - contadores['J']

    return render_template(
        'asistencia.html',
        entrenador=entrenador,
        fecha_sesion=fecha_sesion,
        jugadoras=jugadoras_elegibles,
        estados=estados,
        contadores=contadores,
        sesion=sesion,
        hoy=date.today().isoformat()
    )


@app.route('/asistencia/marcar', methods=['POST'])
@login_requerido
def asistencia_marcar():
    """Endpoint AJAX para marcar/desmarcar asistencia de una jugadora."""
    entrenador = entrenador_actual()
    data = request.get_json()
    fecha_str = data.get('fecha')
    jugadora_id = data.get('jugadora_id')
    estado = data.get('estado')

    if estado not in ['P', 'A', 'J']:
        return jsonify({'ok': False, 'error': 'Estado inválido'}), 400

    fecha_sesion = datetime.strptime(fecha_str, '%Y-%m-%d').date()
    jugadora = Jugadora.query.filter_by(id=jugadora_id, entrenador_id=entrenador.id).first()
    if not jugadora:
        return jsonify({'ok': False, 'error': 'Jugadora no encontrada'}), 404

    sesion = Sesion.query.filter_by(entrenador_id=entrenador.id, fecha=fecha_sesion).first()
    if not sesion:
        sesion = Sesion(entrenador_id=entrenador.id, fecha=fecha_sesion)
        db.session.add(sesion)
        db.session.flush()

    asistencia = Asistencia.query.filter_by(sesion_id=sesion.id, jugadora_id=jugadora_id).first()
    if asistencia:
        if asistencia.estado == estado:
            db.session.delete(asistencia)
            nuevo_estado = None
        else:
            asistencia.estado = estado
            nuevo_estado = estado
    else:
        db.session.add(Asistencia(sesion_id=sesion.id, jugadora_id=jugadora_id, estado=estado))
        nuevo_estado = estado

    db.session.commit()

    # Recalcular contadores y % de la jugadora
    contadores = {'P': 0, 'A': 0, 'J': 0}
    todas_jug = Jugadora.query.filter(
        Jugadora.entrenador_id == entrenador.id,
        Jugadora.fecha_inscripcion <= fecha_sesion
    ).all()
    for j in todas_jug:
        a = Asistencia.query.filter_by(sesion_id=sesion.id, jugadora_id=j.id).first()
        if a:
            contadores[a.estado] = contadores.get(a.estado, 0) + 1
    contadores['pendientes'] = len(todas_jug) - contadores['P'] - contadores['A'] - contadores['J']

    return jsonify({
        'ok': True,
        'nuevo_estado': nuevo_estado,
        'contadores': contadores,
        'pct_jugadora': jugadora.stats_asistencia()['pct']
    })


@app.route('/asistencia/marcar-todas-presentes', methods=['POST'])
@login_requerido
def marcar_todas_presentes():
    entrenador = entrenador_actual()
    fecha_str = request.form.get('fecha')
    fecha_sesion = datetime.strptime(fecha_str, '%Y-%m-%d').date()

    sesion = Sesion.query.filter_by(entrenador_id=entrenador.id, fecha=fecha_sesion).first()
    if not sesion:
        sesion = Sesion(entrenador_id=entrenador.id, fecha=fecha_sesion)
        db.session.add(sesion)
        db.session.flush()

    jugadoras = Jugadora.query.filter(
        Jugadora.entrenador_id == entrenador.id,
        Jugadora.fecha_inscripcion <= fecha_sesion
    ).all()

    for j in jugadoras:
        a = Asistencia.query.filter_by(sesion_id=sesion.id, jugadora_id=j.id).first()
        if a:
            a.estado = 'P'
        else:
            db.session.add(Asistencia(sesion_id=sesion.id, jugadora_id=j.id, estado='P'))

    db.session.commit()
    flash(f'Marcadas {len(jugadoras)} jugadoras como presentes', 'success')
    return redirect(url_for('asistencia', fecha=fecha_str))


@app.route('/asistencia/borrar', methods=['POST'])
@login_requerido
def asistencia_borrar():
    entrenador = entrenador_actual()
    fecha_str = request.form.get('fecha')
    fecha_sesion = datetime.strptime(fecha_str, '%Y-%m-%d').date()
    sesion = Sesion.query.filter_by(entrenador_id=entrenador.id, fecha=fecha_sesion).first()
    if sesion:
        db.session.delete(sesion)
        db.session.commit()
        flash('Planilla borrada', 'success')
    return redirect(url_for('asistencia', fecha=fecha_str))


# ============================================================
# HISTORIAL
# ============================================================
@app.route('/historial')
@login_requerido
def historial():
    entrenador = entrenador_actual()
    sesiones = Sesion.query.filter_by(entrenador_id=entrenador.id).order_by(Sesion.fecha.desc()).all()

    datos = []
    for s in sesiones:
        elegibles = [j for j in entrenador.jugadoras if j.fecha_inscripcion <= s.fecha]
        p = sum(1 for a in s.asistencias if a.estado == 'P')
        a = sum(1 for a in s.asistencias if a.estado == 'A')
        j = sum(1 for a in s.asistencias if a.estado == 'J')
        total = p + a + j
        pct = round((p / total) * 100) if total > 0 else 0
        datos.append({
            'sesion': s,
            'presentes': p,
            'ausentes': a,
            'justificadas': j,
            'total': total,
            'pct': pct,
            'elegibles': len(elegibles)
        })

    return render_template('historial.html', entrenador=entrenador, datos=datos)


# ============================================================
# RUTAS DE PARTIDOS
# ============================================================
@app.route('/partidos')
@login_requerido
def partidos():
    entrenador = entrenador_actual()
    lista = Partido.query.filter_by(entrenador_id=entrenador.id).order_by(Partido.fecha.desc()).all()
    return render_template('partidos.html', entrenador=entrenador, partidos=lista)


@app.route('/partido/nuevo', methods=['GET', 'POST'])
@login_requerido
def partido_nuevo():
    entrenador = entrenador_actual()
    jugadoras = Jugadora.query.filter_by(entrenador_id=entrenador.id).order_by(Jugadora.apellido).all()

    if request.method == 'POST':
        try:
            fecha_str = request.form.get('fecha')
            fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date() if fecha_str else date.today()

            partido = Partido(
                entrenador_id=entrenador.id,
                rival=request.form.get('rival', '').strip(),
                fecha=fecha,
                lugar=request.form.get('lugar', 'Local'),
                notas=request.form.get('notas', '').strip() or None
            )

            if not partido.rival:
                flash('El rival es obligatorio', 'error')
                return render_template('partido_form.html', partido=None, jugadoras=jugadoras,
                                       convocadas_ids=[], entrenador=entrenador, fecha_hoy=date.today().isoformat())

            db.session.add(partido)
            db.session.flush()

            # Convocadas
            convocadas_ids = request.form.getlist('convocadas')
            for jid in convocadas_ids:
                db.session.add(ConvocatoriaPartido(partido_id=partido.id, jugadora_id=int(jid)))

            db.session.commit()
            flash(f'Partido vs {partido.rival} creado', 'success')
            return redirect(url_for('partido_detalle', partido_id=partido.id))
        except Exception as e:
            flash(f'Error: {str(e)}', 'error')

    return render_template('partido_form.html', partido=None, jugadoras=jugadoras,
                           convocadas_ids=[], entrenador=entrenador, fecha_hoy=date.today().isoformat())


@app.route('/partido/<int:partido_id>/editar', methods=['GET', 'POST'])
@login_requerido
def partido_editar(partido_id):
    entrenador = entrenador_actual()
    partido = Partido.query.filter_by(id=partido_id, entrenador_id=entrenador.id).first_or_404()
    jugadoras = Jugadora.query.filter_by(entrenador_id=entrenador.id).order_by(Jugadora.apellido).all()

    if request.method == 'POST':
        try:
            fecha_str = request.form.get('fecha')
            partido.fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
            partido.rival = request.form.get('rival', '').strip()
            partido.lugar = request.form.get('lugar', 'Local')
            partido.notas = request.form.get('notas', '').strip() or None

            # Actualizar convocadas (solo si el partido no arrancó)
            if partido.estado == 'pendiente':
                convocadas_nuevas = set(int(x) for x in request.form.getlist('convocadas'))
                convocadas_actuales = {c.jugadora_id for c in partido.convocadas}

                # Agregar nuevas
                for jid in convocadas_nuevas - convocadas_actuales:
                    db.session.add(ConvocatoriaPartido(partido_id=partido.id, jugadora_id=jid))
                # Quitar las que ya no están
                for c in partido.convocadas:
                    if c.jugadora_id not in convocadas_nuevas:
                        db.session.delete(c)

            db.session.commit()
            flash('Partido actualizado', 'success')
            return redirect(url_for('partido_detalle', partido_id=partido.id))
        except Exception as e:
            flash(f'Error: {str(e)}', 'error')

    convocadas_ids = [c.jugadora_id for c in partido.convocadas]
    return render_template('partido_form.html', partido=partido, jugadoras=jugadoras,
                           convocadas_ids=convocadas_ids, entrenador=entrenador,
                           fecha_hoy=date.today().isoformat())


@app.route('/partido/<int:partido_id>')
@login_requerido
def partido_detalle(partido_id):
    entrenador = entrenador_actual()
    partido = Partido.query.filter_by(id=partido_id, entrenador_id=entrenador.id).first_or_404()
    return render_template('partido_detalle.html', partido=partido, entrenador=entrenador)


@app.route('/partido/<int:partido_id>/eliminar', methods=['POST'])
@login_requerido
def partido_eliminar(partido_id):
    entrenador = entrenador_actual()
    partido = Partido.query.filter_by(id=partido_id, entrenador_id=entrenador.id).first_or_404()
    rival = partido.rival
    db.session.delete(partido)
    db.session.commit()
    flash(f'Partido vs {rival} eliminado', 'success')
    return redirect(url_for('partidos'))


# ============================================================
# RUTAS DE PARTIDO EN VIVO (AJAX)
# ============================================================
def _detener_cronometro(partido):
    """Pausa el cronómetro y guarda los segundos transcurridos."""
    if partido.cronometro_iniciado:
        delta = (datetime.utcnow() - partido.cronometro_iniciado).total_seconds()
        partido.cronometro_segundos += int(delta)
        partido.cronometro_iniciado = None

        # También sumar tiempo a las jugadoras en cancha
        for c in partido.convocadas:
            if c.en_cancha and c.ultimo_ingreso:
                inicio = max(c.ultimo_ingreso, partido.cronometro_iniciado_anterior if hasattr(partido, 'cronometro_iniciado_anterior') else c.ultimo_ingreso)
                # Actualizar segundos jugados
                pass  # Ya lo manejamos en otro lado

def _serializar_estado(partido):
    """Devuelve el estado completo del partido para el frontend."""
    # Contar eventos por tipo y por cuarto
    tipos_stats = ['ataque_favor', 'ataque_contra', 'tiro_favor', 'tiro_contra',
                   'corner_favor', 'corner_contra', 'gol_favor', 'gol_contra']

    # stats_por_cuarto[tipo] = {'1': 0, '2': 0, '3': 0, '4': 0, 'total': 0}
    stats_por_cuarto = {tipo: {'1': 0, '2': 0, '3': 0, '4': 0, 'total': 0} for tipo in tipos_stats}

    for e in partido.eventos:
        if e.tipo in stats_por_cuarto:
            cuarto_str = str(e.cuarto) if e.cuarto in [1, 2, 3, 4] else '1'
            stats_por_cuarto[e.tipo][cuarto_str] += 1
            stats_por_cuarto[e.tipo]['total'] += 1

    # Compatibilidad: dejar también el dict simple "stats" (totales)
    stats_totales = {tipo: stats_por_cuarto[tipo]['total'] for tipo in tipos_stats}

    return {
        'estado': partido.estado,
        'cuarto_actual': partido.cuarto_actual,
        'cronometro_segundos': partido.cronometro_actual,
        'cronometro_corriendo': partido.cronometro_iniciado is not None,
        'goles_favor': partido.goles_favor,
        'goles_contra': partido.goles_contra,
        'stats': stats_totales,
        'stats_por_cuarto': stats_por_cuarto,
        'jugadoras': [{
            'id': c.jugadora_id,
            'nombre': c.jugadora.nombre,
            'apellido': c.jugadora.apellido,
            'apodo': c.jugadora.apodo,
            'iniciales': c.jugadora.iniciales,
            'en_cancha': c.en_cancha,
            'segundos_jugados': c.segundos_jugados + (
                int((datetime.utcnow() - c.ultimo_ingreso).total_seconds())
                if c.en_cancha and c.ultimo_ingreso and partido.cronometro_iniciado else 0
            )
        } for c in partido.convocadas],
        'eventos': [{
            'id': e.id,
            'tipo': e.tipo,
            'subtipo': e.subtipo,
            'cuarto': e.cuarto,
            'minuto': e.minuto,
            'segundo': e.segundo,
            'descripcion': e.descripcion,
            'tiempo_str': e.tiempo_str
        } for e in partido.eventos]
    }


@app.route('/partido/<int:partido_id>/estado')
@login_requerido
def partido_estado(partido_id):
    """Devuelve el estado actual del partido (para refrescar la pantalla en vivo)."""
    entrenador = entrenador_actual()
    partido = Partido.query.filter_by(id=partido_id, entrenador_id=entrenador.id).first_or_404()
    return jsonify(_serializar_estado(partido))


@app.route('/partido/<int:partido_id>/iniciar', methods=['POST'])
@login_requerido
def partido_iniciar(partido_id):
    """Arranca el partido en el primer cuarto."""
    entrenador = entrenador_actual()
    partido = Partido.query.filter_by(id=partido_id, entrenador_id=entrenador.id).first_or_404()

    if partido.estado == 'pendiente':
        partido.estado = 'en_curso'
        partido.cuarto_actual = 1
        partido.cronometro_segundos = 0
        partido.cronometro_iniciado = None  # Inicia pausado, el entrenador toca "play"

    db.session.commit()
    # Redirigir al detalle (la pantalla en vivo)
    return redirect(url_for('partido_detalle', partido_id=partido_id))


@app.route('/partido/<int:partido_id>/cronometro/<accion>', methods=['POST'])
@login_requerido
def partido_cronometro(partido_id, accion):
    """play, pause, reset"""
    entrenador = entrenador_actual()
    partido = Partido.query.filter_by(id=partido_id, entrenador_id=entrenador.id).first_or_404()

    if accion == 'play':
        if not partido.cronometro_iniciado:
            ahora = datetime.utcnow()
            partido.cronometro_iniciado = ahora
            # A las jugadoras en cancha, marcarles ultimo_ingreso = ahora
            for c in partido.convocadas:
                if c.en_cancha:
                    c.ultimo_ingreso = ahora

    elif accion == 'pause':
        if partido.cronometro_iniciado:
            ahora = datetime.utcnow()
            delta = (ahora - partido.cronometro_iniciado).total_seconds()
            partido.cronometro_segundos += int(delta)
            partido.cronometro_iniciado = None
            # Acumular segundos jugados a las jugadoras en cancha
            for c in partido.convocadas:
                if c.en_cancha and c.ultimo_ingreso:
                    delta_j = (ahora - c.ultimo_ingreso).total_seconds()
                    c.segundos_jugados += int(delta_j)
                    c.ultimo_ingreso = None

    elif accion == 'reset':
        # Resetea el cronómetro del cuarto a 0
        if partido.cronometro_iniciado:
            # Acumular tiempo de jugadoras antes de resetear
            ahora = datetime.utcnow()
            for c in partido.convocadas:
                if c.en_cancha and c.ultimo_ingreso:
                    delta_j = (ahora - c.ultimo_ingreso).total_seconds()
                    c.segundos_jugados += int(delta_j)
                    c.ultimo_ingreso = ahora if c.en_cancha else None
        partido.cronometro_segundos = 0
        partido.cronometro_iniciado = None

    db.session.commit()
    return jsonify(_serializar_estado(partido))


@app.route('/partido/<int:partido_id>/cuarto/<accion>', methods=['POST'])
@login_requerido
def partido_cuarto(partido_id, accion):
    """siguiente o anterior cuarto"""
    entrenador = entrenador_actual()
    partido = Partido.query.filter_by(id=partido_id, entrenador_id=entrenador.id).first_or_404()

    # Pausar cronómetro y acumular tiempo si está corriendo
    if partido.cronometro_iniciado:
        ahora = datetime.utcnow()
        delta = (ahora - partido.cronometro_iniciado).total_seconds()
        partido.cronometro_segundos += int(delta)
        partido.cronometro_iniciado = None
        for c in partido.convocadas:
            if c.en_cancha and c.ultimo_ingreso:
                delta_j = (ahora - c.ultimo_ingreso).total_seconds()
                c.segundos_jugados += int(delta_j)
                c.ultimo_ingreso = None

    if accion == 'siguiente' and partido.cuarto_actual < 4:
        partido.cuarto_actual += 1
        partido.cronometro_segundos = 0
    elif accion == 'anterior' and partido.cuarto_actual > 1:
        partido.cuarto_actual -= 1
        partido.cronometro_segundos = 0

    db.session.commit()
    return jsonify(_serializar_estado(partido))


@app.route('/partido/<int:partido_id>/jugadora/<int:jugadora_id>/<accion>', methods=['POST'])
@login_requerido
def partido_jugadora_accion(partido_id, jugadora_id, accion):
    """entrar o salir de cancha"""
    entrenador = entrenador_actual()
    partido = Partido.query.filter_by(id=partido_id, entrenador_id=entrenador.id).first_or_404()
    convocatoria = ConvocatoriaPartido.query.filter_by(
        partido_id=partido_id, jugadora_id=jugadora_id).first_or_404()

    ahora = datetime.utcnow()
    minuto_actual = partido.cronometro_actual // 60
    segundo_actual = partido.cronometro_actual % 60

    if accion == 'entrar':
        if not convocatoria.en_cancha:
            convocatoria.en_cancha = True
            # Solo arranca a contar si el cronómetro está corriendo
            convocatoria.ultimo_ingreso = ahora if partido.cronometro_iniciado else None
            # Registrar evento
            db.session.add(EventoPartido(
                partido_id=partido_id, tipo='entrada',
                cuarto=partido.cuarto_actual, minuto=minuto_actual, segundo=segundo_actual,
                jugadora_id=jugadora_id
            ))

    elif accion == 'salir':
        if convocatoria.en_cancha:
            # Acumular tiempo si estaba contando
            if convocatoria.ultimo_ingreso and partido.cronometro_iniciado:
                delta_j = (ahora - convocatoria.ultimo_ingreso).total_seconds()
                convocatoria.segundos_jugados += int(delta_j)
            convocatoria.en_cancha = False
            convocatoria.ultimo_ingreso = None
            # Registrar evento
            db.session.add(EventoPartido(
                partido_id=partido_id, tipo='salida',
                cuarto=partido.cuarto_actual, minuto=minuto_actual, segundo=segundo_actual,
                jugadora_id=jugadora_id
            ))

    db.session.commit()
    return jsonify(_serializar_estado(partido))


@app.route('/partido/<int:partido_id>/gol', methods=['POST'])
@login_requerido
def partido_gol(partido_id):
    """Registra un gol a favor (con jugadora y tipo) o en contra (con tipo)."""
    entrenador = entrenador_actual()
    partido = Partido.query.filter_by(id=partido_id, entrenador_id=entrenador.id).first_or_404()

    data = request.get_json()
    tipo = data.get('tipo')  # 'favor' o 'contra'
    jugadora_id = data.get('jugadora_id')  # Solo si tipo == 'favor'
    subtipo = data.get('subtipo')  # 'jugada', 'corner_corto', 'penal'

    minuto_actual = partido.cronometro_actual // 60
    segundo_actual = partido.cronometro_actual % 60

    if tipo == 'favor':
        partido.goles_favor += 1
        db.session.add(EventoPartido(
            partido_id=partido_id, tipo='gol_favor', subtipo=subtipo,
            cuarto=partido.cuarto_actual, minuto=minuto_actual, segundo=segundo_actual,
            jugadora_id=jugadora_id
        ))
    elif tipo == 'contra':
        partido.goles_contra += 1
        db.session.add(EventoPartido(
            partido_id=partido_id, tipo='gol_contra', subtipo=subtipo,
            cuarto=partido.cuarto_actual, minuto=minuto_actual, segundo=segundo_actual
        ))

    db.session.commit()
    return jsonify(_serializar_estado(partido))


@app.route('/partido/<int:partido_id>/stat', methods=['POST'])
@login_requerido
def partido_stat(partido_id):
    """Registra un evento de estadística genérica (ataque, tiro, córner)."""
    entrenador = entrenador_actual()
    partido = Partido.query.filter_by(id=partido_id, entrenador_id=entrenador.id).first_or_404()

    data = request.get_json()
    tipo = data.get('tipo')  # ataque_favor, ataque_contra, tiro_favor, etc.

    tipos_validos = {'ataque_favor', 'ataque_contra', 'tiro_favor', 'tiro_contra',
                     'corner_favor', 'corner_contra'}
    if tipo not in tipos_validos:
        return jsonify({'ok': False, 'error': 'Tipo de evento inválido'}), 400

    minuto_actual = partido.cronometro_actual // 60
    segundo_actual = partido.cronometro_actual % 60

    db.session.add(EventoPartido(
        partido_id=partido_id, tipo=tipo,
        cuarto=partido.cuarto_actual, minuto=minuto_actual, segundo=segundo_actual
    ))

    db.session.commit()
    return jsonify(_serializar_estado(partido))


@app.route('/partido/<int:partido_id>/evento/<int:evento_id>/eliminar', methods=['POST'])
@login_requerido
def partido_evento_eliminar(partido_id, evento_id):
    """Elimina un evento del partido (para corregir errores)."""
    entrenador = entrenador_actual()
    partido = Partido.query.filter_by(id=partido_id, entrenador_id=entrenador.id).first_or_404()
    evento = EventoPartido.query.filter_by(id=evento_id, partido_id=partido_id).first_or_404()

    # Si era un gol, descontar del marcador
    if evento.tipo == 'gol_favor' and partido.goles_favor > 0:
        partido.goles_favor -= 1
    elif evento.tipo == 'gol_contra' and partido.goles_contra > 0:
        partido.goles_contra -= 1

    db.session.delete(evento)
    db.session.commit()
    return jsonify(_serializar_estado(partido))


@app.route('/partido/<int:partido_id>/finalizar', methods=['POST'])
@login_requerido
def partido_finalizar(partido_id):
    """Termina el partido."""
    entrenador = entrenador_actual()
    partido = Partido.query.filter_by(id=partido_id, entrenador_id=entrenador.id).first_or_404()

    # Pausar cronómetro y acumular tiempos
    if partido.cronometro_iniciado:
        ahora = datetime.utcnow()
        delta = (ahora - partido.cronometro_iniciado).total_seconds()
        partido.cronometro_segundos += int(delta)
        partido.cronometro_iniciado = None
        for c in partido.convocadas:
            if c.en_cancha and c.ultimo_ingreso:
                delta_j = (ahora - c.ultimo_ingreso).total_seconds()
                c.segundos_jugados += int(delta_j)
                c.ultimo_ingreso = None
                c.en_cancha = False

    partido.estado = 'finalizado'
    db.session.commit()
    flash('Partido finalizado', 'success')
    return redirect(url_for('partido_detalle', partido_id=partido_id))


@app.route('/partido/<int:partido_id>/reanudar', methods=['POST'])
@login_requerido
def partido_reanudar(partido_id):
    """Vuelve a poner un partido finalizado en estado 'en curso'."""
    entrenador = entrenador_actual()
    partido = Partido.query.filter_by(id=partido_id, entrenador_id=entrenador.id).first_or_404()
    if partido.estado == 'finalizado':
        partido.estado = 'en_curso'
        db.session.commit()
        flash('Partido reanudado', 'success')
    return redirect(url_for('partido_detalle', partido_id=partido_id))


# ============================================================
# MIGRACIÓN AUTOMÁTICA DE BASE DE DATOS
# ============================================================
def aplicar_migraciones():
    """Aplica cambios necesarios a la base de datos existente.
    Es seguro correr esto múltiples veces — solo aplica lo que falta."""
    from sqlalchemy import inspect, text

    with app.app_context():
        inspector = inspect(db.engine)

        # Migración 1: agregar columna 'subtipo' a evento_partido
        if 'evento_partido' in inspector.get_table_names():
            cols = [c['name'] for c in inspector.get_columns('evento_partido')]
            if 'subtipo' not in cols:
                print('[MIGRACIÓN] Agregando columna subtipo a evento_partido...')
                with db.engine.connect() as conn:
                    conn.execute(text('ALTER TABLE evento_partido ADD COLUMN subtipo VARCHAR(20)'))
                    conn.commit()
                print('[MIGRACIÓN] ✓ Columna subtipo agregada')


# ============================================================
# INICIALIZACIÓN
# ============================================================
with app.app_context():
    db.create_all()
    aplicar_migraciones()


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
