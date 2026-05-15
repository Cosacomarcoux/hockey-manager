"""
Hockey Team Manager - App para entrenadores de hockey sobre césped
Fase 1: Plantel, asistencias y porcentajes con login multi-usuario
"""
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, timedelta
from functools import wraps
import os

# Módulo de rotación (lógica pura) y adaptador (Flask ↔ módulo)
from rotacion_module import FORMACIONES, ModoRotacion
import rotacion_adapter

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

POSICIONES = ['Arquera', 'Defensora', 'Volante', 'Delantera']

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
    equipos = db.relationship('Equipo', backref='entrenador', lazy=True, cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Equipo(db.Model):
    """
    Un Equipo es un conjunto independiente de plantel + asistencias + partidos.
    Una entrenadora puede tener múltiples equipos (sub-14, sub-16, primera, etc).
    Cada Equipo tiene su propio plantel separado (no se mezcla con otros equipos).
    """
    id = db.Column(db.Integer, primary_key=True)
    entrenador_id = db.Column(db.Integer, db.ForeignKey('entrenador.id'), nullable=False)
    nombre = db.Column(db.String(80), nullable=False)
    creado = db.Column(db.DateTime, default=datetime.utcnow)
    es_principal = db.Column(db.Boolean, default=False)  # Marca el equipo "default" del entrenador

    # Relaciones
    jugadoras = db.relationship('Jugadora', backref='equipo', lazy=True,
                                foreign_keys='Jugadora.equipo_id')
    sesiones = db.relationship('Sesion', backref='equipo', lazy=True,
                               foreign_keys='Sesion.equipo_id')
    partidos = db.relationship('Partido', backref='equipo', lazy=True,
                               foreign_keys='Partido.equipo_id')


class Jugadora(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    entrenador_id = db.Column(db.Integer, db.ForeignKey('entrenador.id'), nullable=False)
    equipo_id = db.Column(db.Integer, db.ForeignKey('equipo.id'), nullable=True)  # multi-equipo
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
    equipo_id = db.Column(db.Integer, db.ForeignKey('equipo.id'), nullable=True)  # multi-equipo
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
# MODELO DE CONFIGURACIÓN DE ROTACIÓN POR PARTIDO
# ============================================================
class ConfiguracionPartido(db.Model):
    """
    Guarda la configuración del módulo de rotación para un partido específico:
    K, formación, modo, anclas, umbrales.
    Las células y bloques se guardarán en otras tablas (Etapa 3).
    """
    id = db.Column(db.Integer, primary_key=True)
    partido_id = db.Column(db.Integer, db.ForeignKey('partido.id'), nullable=False, unique=True)

    K = db.Column(db.Float, default=0.7)                          # 0.6 a 0.9
    formacion = db.Column(db.String(20), default='4-3-3')         # 4-3-3, 4-4-2, 3-5-2, etc.
    modo = db.Column(db.String(20), default='libre')              # libre, celulas, bloques
    umbral_cambio_minutos = db.Column(db.Float, default=5.0)
    tiempo_pre_alerta_minutos = db.Column(db.Float, default=1.0)

    # Lista de IDs de jugadoras ancla, separados por coma. Ej: "5,12,7"
    # Es simple y suficiente para esta etapa. Más adelante podríamos normalizarlo.
    anclas_csv = db.Column(db.String(500), default='')

    creado = db.Column(db.DateTime, default=datetime.utcnow)
    modificado = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    partido = db.relationship('Partido', backref=db.backref('config_rotacion', uselist=False, cascade='all, delete-orphan'))

    @property
    def anclas_set(self) -> set:
        """Devuelve los IDs de anclas como set de int."""
        if not self.anclas_csv:
            return set()
        return {int(x) for x in self.anclas_csv.split(',') if x.strip()}

    def set_anclas(self, ids: list):
        """Recibe una lista de int y la guarda como CSV."""
        if not ids:
            self.anclas_csv = ''
        else:
            self.anclas_csv = ','.join(str(int(i)) for i in ids)


# ============================================================
# MODELO DE PLANIFICACIÓN POR TURNOS
# ============================================================
class PlanificacionPartido(db.Model):
    """
    Plan de turnos del partido. Por cada partido hay un único plan.
    El plan contiene N turnos según la duración elegida (60 / duracion_turno).
    Cada turno tiene una lista de jugadoras asignadas (idealmente 11).
    """
    id = db.Column(db.Integer, primary_key=True)
    partido_id = db.Column(db.Integer, db.ForeignKey('partido.id'), nullable=False, unique=True)

    duracion_turno_min = db.Column(db.Float, default=5.0)  # 3 a 7.5
    creado = db.Column(db.DateTime, default=datetime.utcnow)
    modificado = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    partido = db.relationship('Partido', backref=db.backref('planificacion', uselist=False, cascade='all, delete-orphan'))
    asignaciones = db.relationship('AsignacionTurno', backref='plan', lazy=True, cascade='all, delete-orphan')

    @property
    def cantidad_turnos(self) -> int:
        """Cuántos turnos tiene el plan total."""
        if self.duracion_turno_min <= 0:
            return 0
        return int(round(60 / self.duracion_turno_min))

    def turnos_de_jugadora(self, jugadora_id: int) -> list:
        """Devuelve la lista de números de turno donde está asignada esta jugadora."""
        return sorted([a.turno_numero for a in self.asignaciones if a.jugadora_id == jugadora_id])

    def jugadoras_de_turno(self, turno_numero: int) -> list:
        """Devuelve la lista de IDs de jugadoras asignadas a un turno específico."""
        return [a.jugadora_id for a in self.asignaciones if a.turno_numero == turno_numero]


class AsignacionTurno(db.Model):
    """
    Asignación: jugadora X juega el turno N del plan en el slot S.

    El slot_indice indica qué posición visual ocupa en la cancha.
    Convención de slots (0-indexed):
        Arquera:   slot 0
        Defensora: slots 100, 101, 102, ... (100 + índice dentro de defensoras)
        Volante:   slots 200, 201, 202, ...
        Delantera: slots 300, 301, 302, ...
    Esto permite saber rápido qué posición ocupa: slot // 100 da el grupo,
    slot % 100 da el índice dentro del grupo.

    Una jugadora puede aparecer en varios turnos pero en cada turno tiene un único slot.
    """
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('planificacion_partido.id'), nullable=False)
    jugadora_id = db.Column(db.Integer, db.ForeignKey('jugadora.id'), nullable=False)
    turno_numero = db.Column(db.Integer, nullable=False)  # 1, 2, 3, ...
    slot_indice = db.Column(db.Integer, nullable=False, default=0)

    jugadora = db.relationship('Jugadora')

    __table_args__ = (
        db.UniqueConstraint('plan_id', 'jugadora_id', 'turno_numero', name='_plan_jugadora_turno_uc'),
    )


# ============================================================
# MODELO DE BLOQUES (jugadoras que rotan juntas en el plan)
# ============================================================
class BloqueRotacion(db.Model):
    """
    Un bloque es un grupo de 2+ jugadoras que el DT considera deben moverse juntas.
    Está asociado a un partido específico (cada partido puede tener sus propios bloques).
    """
    id = db.Column(db.Integer, primary_key=True)
    partido_id = db.Column(db.Integer, db.ForeignKey('partido.id'), nullable=False)
    nombre = db.Column(db.String(100), nullable=False)
    color = db.Column(db.String(20), default='violeta')  # violeta, ambar, teal, coral, rosa
    creado = db.Column(db.DateTime, default=datetime.utcnow)

    partido = db.relationship('Partido', backref=db.backref('bloques', lazy=True, cascade='all, delete-orphan'))
    miembros = db.relationship('JugadoraBloque', backref='bloque', lazy=True, cascade='all, delete-orphan')

    @property
    def jugadoras_ids(self) -> list:
        """Devuelve los IDs de jugadoras del bloque."""
        return [m.jugadora_id for m in self.miembros]


class JugadoraBloque(db.Model):
    """
    Tabla de relación: qué jugadoras pertenecen a cada bloque.
    Una jugadora puede pertenecer a múltiples bloques.
    """
    id = db.Column(db.Integer, primary_key=True)
    bloque_id = db.Column(db.Integer, db.ForeignKey('bloque_rotacion.id'), nullable=False)
    jugadora_id = db.Column(db.Integer, db.ForeignKey('jugadora.id'), nullable=False)

    jugadora = db.relationship('Jugadora')

    __table_args__ = (
        db.UniqueConstraint('bloque_id', 'jugadora_id', name='_bloque_jugadora_uc'),
    )


# ============================================================
# MODELOS DE PARTIDOS
# ============================================================
class Partido(db.Model):
    """Un partido contra un rival."""
    id = db.Column(db.Integer, primary_key=True)
    entrenador_id = db.Column(db.Integer, db.ForeignKey('entrenador.id'), nullable=False)
    equipo_id = db.Column(db.Integer, db.ForeignKey('equipo.id'), nullable=True)  # multi-equipo
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

    # === Jugadora no disponible (se fue / se lesionó / otro motivo) ===
    no_disponible = db.Column(db.Boolean, default=False)
    no_disponible_motivo = db.Column(db.String(20))  # 'se_fue' / 'lesionada' / 'otro'
    no_disponible_cuarto = db.Column(db.Integer)     # En qué cuarto se marcó
    no_disponible_segundo = db.Column(db.Integer)    # En qué segundo del cuarto

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


def equipo_actual():
    """
    Devuelve el equipo activo del entrenador.
    El ID del equipo activo se guarda en sesión.
    Si no hay equipo activo en sesión, devuelve el equipo principal del entrenador.
    Si el entrenador no tiene ningún equipo, devuelve None.
    """
    ent = entrenador_actual()
    if not ent:
        return None

    # Si hay equipo en sesión, validamos que sea del entrenador actual
    eq_id = session.get('equipo_id')
    if eq_id:
        eq = Equipo.query.filter_by(id=eq_id, entrenador_id=ent.id).first()
        if eq:
            return eq

    # Si no, usamos el principal
    eq = Equipo.query.filter_by(entrenador_id=ent.id, es_principal=True).first()
    if eq:
        session['equipo_id'] = eq.id
        return eq

    # Si no hay principal, usamos el primero
    eq = Equipo.query.filter_by(entrenador_id=ent.id).order_by(Equipo.id).first()
    if eq:
        session['equipo_id'] = eq.id
        return eq

    return None


def cambiar_equipo_activo(equipo_id):
    """
    Cambia el equipo activo en la sesión.
    Valida que el equipo pertenezca al entrenador actual.
    Devuelve True si cambió, False si no.
    """
    ent = entrenador_actual()
    if not ent:
        return False
    eq = Equipo.query.filter_by(id=equipo_id, entrenador_id=ent.id).first()
    if not eq:
        return False
    session['equipo_id'] = eq.id
    return True


@app.context_processor
def inject_equipo_actual():
    """Hace disponibles 'eq_actual' y 'todos_los_equipos' en TODOS los templates."""
    if 'entrenador_id' not in session:
        return {}
    eq = equipo_actual()
    todos = Equipo.query.filter_by(entrenador_id=session['entrenador_id']).order_by(Equipo.creado).all()
    return {
        'eq_actual': eq,
        'todos_los_equipos': todos,
    }


class NotaPartido(db.Model):
    """
    Nota o comentario asociado a un partido o a un rival.
    - Si partido_id está seteado: nota sobre ese partido específico (post-partido).
    - Si partido_id es NULL: nota general sobre el rival (no atada a un partido).
    El campo 'rival' siempre está, porque las notas se agrupan por rival.
    """
    id = db.Column(db.Integer, primary_key=True)
    entrenador_id = db.Column(db.Integer, db.ForeignKey('entrenador.id'), nullable=False)
    equipo_id = db.Column(db.Integer, db.ForeignKey('equipo.id'), nullable=True)
    partido_id = db.Column(db.Integer, db.ForeignKey('partido.id'), nullable=True)
    rival = db.Column(db.String(120), nullable=False)
    texto = db.Column(db.Text, nullable=False)
    etiquetas = db.Column(db.String(500))  # tags separadas por coma: "tactica,defensa,jug7"
    creada = db.Column(db.DateTime, default=datetime.utcnow)
    actualizada = db.Column(db.DateTime, default=datetime.utcnow)

    entrenador = db.relationship('Entrenador')
    partido = db.relationship('Partido', backref=db.backref('comentarios_post_partido', lazy=True, cascade='all, delete-orphan'))

    @property
    def etiquetas_lista(self):
        """Devuelve etiquetas como lista. Si está vacío, devuelve []."""
        if not self.etiquetas:
            return []
        return [e.strip() for e in self.etiquetas.split(',') if e.strip()]


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

        # Crear el Equipo Principal automáticamente
        equipo_principal = Equipo(
            entrenador_id=entrenador.id,
            nombre="Equipo Principal",
            es_principal=True,
        )
        db.session.add(equipo_principal)
        db.session.commit()

        session['entrenador_id'] = entrenador.id
        session['equipo_id'] = equipo_principal.id
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
            # Setear equipo activo (principal o el primero que tenga)
            eq = Equipo.query.filter_by(entrenador_id=entrenador.id, es_principal=True).first()
            if not eq:
                eq = Equipo.query.filter_by(entrenador_id=entrenador.id).order_by(Equipo.id).first()
            if eq:
                session['equipo_id'] = eq.id
            return redirect(url_for('plantel'))

        flash('Email o contraseña incorrectos', 'error')

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ============================================================
# ============================================================
# RUTAS DE EQUIPOS (multi-equipo)
# ============================================================
@app.route('/equipos')
@login_requerido
def equipos_lista():
    """Lista de equipos del entrenador con opción de crear/editar/borrar."""
    entrenador = entrenador_actual()
    equipos = Equipo.query.filter_by(entrenador_id=entrenador.id).order_by(Equipo.creado).all()
    eq_activo = equipo_actual()

    # Calcular contadores por equipo (jugadoras, partidos)
    contadores = {}
    for eq in equipos:
        contadores[eq.id] = {
            'jugadoras': Jugadora.query.filter_by(equipo_id=eq.id).count(),
            'partidos': Partido.query.filter_by(equipo_id=eq.id).count(),
        }

    return render_template(
        'equipos_lista.html',
        entrenador=entrenador,
        equipos=equipos,
        eq_activo=eq_activo,
        contadores=contadores,
    )


@app.route('/equipo/nuevo', methods=['POST'])
@login_requerido
def equipo_nuevo():
    """Crea un nuevo equipo."""
    entrenador = entrenador_actual()
    nombre = (request.form.get('nombre') or '').strip()
    if not nombre:
        flash('Tenés que poner un nombre al equipo', 'error')
        return redirect(url_for('equipos_lista'))
    if len(nombre) > 80:
        nombre = nombre[:80]

    nuevo = Equipo(entrenador_id=entrenador.id, nombre=nombre, es_principal=False)
    db.session.add(nuevo)
    db.session.commit()
    flash(f'Equipo "{nombre}" creado', 'success')
    return redirect(url_for('equipos_lista'))


@app.route('/equipo/<int:equipo_id>/editar', methods=['POST'])
@login_requerido
def equipo_editar(equipo_id):
    """Cambia el nombre de un equipo."""
    entrenador = entrenador_actual()
    eq = Equipo.query.filter_by(id=equipo_id, entrenador_id=entrenador.id).first_or_404()
    nombre = (request.form.get('nombre') or '').strip()
    if not nombre:
        flash('Tenés que poner un nombre', 'error')
        return redirect(url_for('equipos_lista'))
    if len(nombre) > 80:
        nombre = nombre[:80]
    eq.nombre = nombre
    db.session.commit()
    flash(f'Equipo renombrado a "{nombre}"', 'success')
    return redirect(url_for('equipos_lista'))


@app.route('/equipo/<int:equipo_id>/borrar', methods=['POST'])
@login_requerido
def equipo_borrar(equipo_id):
    """Borra un equipo y todos sus datos asociados."""
    entrenador = entrenador_actual()
    eq = Equipo.query.filter_by(id=equipo_id, entrenador_id=entrenador.id).first_or_404()

    # No permitir borrar el último equipo
    cant_equipos = Equipo.query.filter_by(entrenador_id=entrenador.id).count()
    if cant_equipos <= 1:
        flash('No podés borrar tu único equipo. Creá otro primero.', 'error')
        return redirect(url_for('equipos_lista'))

    nombre = eq.nombre

    # Borrar todos los datos del equipo (jugadoras, partidos, sesiones)
    # SQLAlchemy se encarga de las cascadas a sus hijos (asistencias, eventos, etc.)
    Jugadora.query.filter_by(equipo_id=eq.id).delete()
    Sesion.query.filter_by(equipo_id=eq.id).delete()
    Partido.query.filter_by(equipo_id=eq.id).delete()
    db.session.delete(eq)
    db.session.commit()

    # Si era el equipo activo, cambiar al principal
    if session.get('equipo_id') == equipo_id:
        principal = Equipo.query.filter_by(entrenador_id=entrenador.id, es_principal=True).first()
        if not principal:
            principal = Equipo.query.filter_by(entrenador_id=entrenador.id).order_by(Equipo.id).first()
        if principal:
            session['equipo_id'] = principal.id
        else:
            session.pop('equipo_id', None)

    flash(f'Equipo "{nombre}" eliminado', 'success')
    return redirect(url_for('equipos_lista'))


@app.route('/equipo/<int:equipo_id>/activar', methods=['POST'])
@login_requerido
def equipo_activar(equipo_id):
    """Cambia el equipo activo en la sesión."""
    if cambiar_equipo_activo(equipo_id):
        eq = Equipo.query.get(equipo_id)
        flash(f'Cambiaste a "{eq.nombre}"', 'success')
    else:
        flash('No se pudo cambiar de equipo', 'error')
    # Redirigir a donde estaba el usuario o al plantel
    next_url = request.form.get('next') or url_for('plantel')
    return redirect(next_url)


# ============================================================
# RUTAS DEL PLANTEL
# ============================================================
@app.route('/plantel')
@login_requerido
def plantel():
    entrenador = entrenador_actual()
    eq_actual = equipo_actual()
    jugadoras = Jugadora.query.filter_by(equipo_id=eq_actual.id).order_by(Jugadora.apellido).all()

    # Stats generales
    stats_jugadoras = [(j, j.stats_asistencia()) for j in jugadoras]
    total_jug = len(jugadoras)
    total_sesiones = Sesion.query.filter_by(equipo_id=eq_actual.id).count()
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
    eq_actual = equipo_actual()
    if request.method == 'POST':
        try:
            fecha_nac = request.form.get('fecha_nacimiento') or None
            fecha_nac = datetime.strptime(fecha_nac, '%Y-%m-%d').date() if fecha_nac else None
            fecha_insc = request.form.get('fecha_inscripcion') or date.today().isoformat()
            fecha_insc = datetime.strptime(fecha_insc, '%Y-%m-%d').date()

            jugadora = Jugadora(
                entrenador_id=entrenador.id,
                equipo_id=eq_actual.id if eq_actual else None,
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
    eq_actual = equipo_actual()
    fecha_str = request.args.get('fecha', date.today().isoformat())
    try:
        fecha_sesion = datetime.strptime(fecha_str, '%Y-%m-%d').date()
    except ValueError:
        fecha_sesion = date.today()

    # Buscar o crear sesión virtual (no se guarda hasta que marquen al menos una)
    sesion = Sesion.query.filter_by(equipo_id=eq_actual.id, fecha=fecha_sesion).first() if eq_actual else None

    # Solo jugadoras inscriptas hasta esa fecha
    jugadoras_elegibles = Jugadora.query.filter(
        Jugadora.equipo_id == eq_actual.id if eq_actual else False,
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
    eq_actual = equipo_actual()
    data = request.get_json()
    fecha_str = data.get('fecha')
    jugadora_id = data.get('jugadora_id')
    estado = data.get('estado')

    if estado not in ['P', 'A', 'J']:
        return jsonify({'ok': False, 'error': 'Estado inválido'}), 400

    fecha_sesion = datetime.strptime(fecha_str, '%Y-%m-%d').date()
    jugadora = Jugadora.query.filter_by(id=jugadora_id, equipo_id=eq_actual.id).first() if eq_actual else None
    if not jugadora:
        return jsonify({'ok': False, 'error': 'Jugadora no encontrada'}), 404

    sesion = Sesion.query.filter_by(equipo_id=eq_actual.id, fecha=fecha_sesion).first()
    if not sesion:
        sesion = Sesion(entrenador_id=entrenador.id, equipo_id=eq_actual.id if eq_actual else None, fecha=fecha_sesion)
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
    eq_actual = equipo_actual()
    fecha_str = request.form.get('fecha')
    fecha_sesion = datetime.strptime(fecha_str, '%Y-%m-%d').date()

    sesion = Sesion.query.filter_by(equipo_id=eq_actual.id, fecha=fecha_sesion).first() if eq_actual else None
    if not sesion:
        sesion = Sesion(entrenador_id=entrenador.id, equipo_id=eq_actual.id if eq_actual else None, fecha=fecha_sesion)
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
    eq_actual = equipo_actual()
    fecha_str = request.form.get('fecha')
    fecha_sesion = datetime.strptime(fecha_str, '%Y-%m-%d').date()
    sesion = Sesion.query.filter_by(equipo_id=eq_actual.id, fecha=fecha_sesion).first() if eq_actual else None
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
    eq_actual = equipo_actual()
    sesiones = Sesion.query.filter_by(equipo_id=eq_actual.id).order_by(Sesion.fecha.desc()).all()

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
    eq_actual = equipo_actual()
    lista = Partido.query.filter_by(equipo_id=eq_actual.id).order_by(Partido.fecha.desc()).all()
    return render_template('partidos.html', entrenador=entrenador, partidos=lista)


@app.route('/partido/nuevo', methods=['GET', 'POST'])
@login_requerido
def partido_nuevo():
    entrenador = entrenador_actual()
    eq_actual = equipo_actual()
    jugadoras = Jugadora.query.filter_by(equipo_id=eq_actual.id).order_by(Jugadora.apellido).all()

    if request.method == 'POST':
        try:
            fecha_str = request.form.get('fecha')
            fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date() if fecha_str else date.today()

            partido = Partido(
                entrenador_id=entrenador.id,
                equipo_id=eq_actual.id if eq_actual else None,
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
    eq_actual = equipo_actual()
    partido = Partido.query.filter_by(id=partido_id, entrenador_id=entrenador.id).first_or_404()
    jugadoras = Jugadora.query.filter_by(equipo_id=eq_actual.id).order_by(Jugadora.apellido).all()

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

    # === INFO DEL PLAN PARA LA VISTA EN VIVO ===
    plan_info = _calcular_info_plan_en_vivo(partido)

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
            'posicion': c.jugadora.posicion,
            'posicion_alt': c.jugadora.posicion_alt,
            'en_cancha': c.en_cancha,
            'no_disponible': c.no_disponible,
            'no_disponible_motivo': c.no_disponible_motivo,
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
        } for e in partido.eventos],
        'plan_en_vivo': plan_info,
    }


def _calcular_info_plan_en_vivo(partido):
    """
    Calcula la info del plan según el cuarto y cronómetro actuales del partido.

    Convención: el plan completo cubre los 60 min del partido en N turnos.
    Esos N turnos se distribuyen por cuartos. Si N=12 y duración=5min:
    - Q1 → T1, T2, T3 (cada turno = 5 min del cuarto)
    - Q2 → T4, T5, T6
    - Q3 → T7, T8, T9
    - Q4 → T10, T11, T12

    Si no hay plan o el partido no está en curso, devuelve null.
    """
    if partido.estado != 'en_curso' or partido.cuarto_actual not in [1, 2, 3, 4]:
        return None

    plan = PlanificacionPartido.query.filter_by(partido_id=partido.id).first()
    if not plan:
        return None

    n_turnos_total = plan.cantidad_turnos  # ej. 12
    duracion_turno = plan.duracion_turno_min

    # Cuántos turnos por cuarto (asumimos distribución uniforme)
    if n_turnos_total % 4 != 0:
        # Si no es divisible por 4, simplemente no lo distribuimos por cuartos
        # (caso raro: 10, 11, 13, etc. turnos)
        turnos_por_cuarto = n_turnos_total / 4
    else:
        turnos_por_cuarto = n_turnos_total // 4

    # Cuarto actual y minuto dentro del cuarto
    cuarto = partido.cuarto_actual
    crono_seg_total = partido.cronometro_actual
    minuto_en_cuarto = crono_seg_total / 60.0
    seg_en_cuarto = crono_seg_total

    # Calcular turno actual:
    # Cada cuarto dura 15 min y tiene `turnos_por_cuarto` turnos.
    # Cada turno dentro del cuarto dura 15/turnos_por_cuarto minutos
    if turnos_por_cuarto <= 0:
        return None

    duracion_turno_en_cuarto = 15.0 / turnos_por_cuarto  # minutos por turno dentro del cuarto

    # Turno relativo dentro del cuarto (0-indexed)
    turno_idx_en_cuarto = int(minuto_en_cuarto / duracion_turno_en_cuarto)
    if turno_idx_en_cuarto >= turnos_por_cuarto:
        turno_idx_en_cuarto = int(turnos_por_cuarto) - 1

    # Turno absoluto (1-indexed)
    turno_actual_n = int((cuarto - 1) * turnos_por_cuarto + turno_idx_en_cuarto + 1)
    turno_actual_n = max(1, min(turno_actual_n, n_turnos_total))

    # Calcular cuándo termina el turno actual (en segundos del cuarto actual)
    # y si el próximo turno cae en este cuarto o es del próximo
    fin_turno_actual_seg_en_cuarto = (turno_idx_en_cuarto + 1) * duracion_turno_en_cuarto * 60

    # ¿El próximo turno está en este cuarto?
    proximo_en_mismo_cuarto = (turno_idx_en_cuarto + 1) < turnos_por_cuarto
    turno_proximo_n = turno_actual_n + 1 if turno_actual_n < n_turnos_total else None

    # Segundos hasta el próximo cambio (solo si está en mismo cuarto)
    segundos_hasta_cambio = None
    if proximo_en_mismo_cuarto and turno_proximo_n:
        segundos_hasta_cambio = max(0, int(fin_turno_actual_seg_en_cuarto - seg_en_cuarto))

    # Quiénes deberían estar en cancha AHORA según el plan
    asign_actual = AsignacionTurno.query.filter_by(plan_id=plan.id, turno_numero=turno_actual_n).all()
    plan_actual_ids = [a.jugadora_id for a in asign_actual]
    plan_actual_set = set(plan_actual_ids)

    # Detectar quiénes están en cancha AHORA
    convocadas = list(partido.convocadas)
    cancha_actual_set = {c.jugadora_id for c in convocadas if c.en_cancha}

    # ===========================================================================
    # LÓGICA DE CAMBIOS A MOSTRAR
    # ===========================================================================
    # Regla simple: siempre apuntamos a T_proximo y mostramos los cambios necesarios
    # para llegar al plan T_proximo desde la cancha REAL.
    # Si una jugadora ya está donde debe estar (porque vos no la sacaste), no aparece
    # ni en "salen" ni en "entran" - todo natural.
    # ===========================================================================
    cambios = []
    target_turno = None
    target_set = None

    cancha_alineada_actual = (cancha_actual_set == plan_actual_set)

    if turno_proximo_n and proximo_en_mismo_cuarto:
        # Mostrar los cambios necesarios para llegar al plan de T_proximo
        plan_proximo_set = {a.jugadora_id for a in
                            AsignacionTurno.query.filter_by(plan_id=plan.id, turno_numero=turno_proximo_n).all()}
        target_turno = turno_proximo_n
        target_set = plan_proximo_set
    else:
        # No hay próximo en mismo cuarto (último turno o final de cuarto)
        target_turno = turno_actual_n
        target_set = plan_actual_set

    # cancha_alineada = ¿ya estoy en la formación que muestra la card?
    cancha_alineada_target = (cancha_actual_set == target_set)

    # En cancha pero NO en target → SALEN (sobran)
    # PERO excluyendo a las "no disponibles" (no pueden ni salir ni entrar)
    no_disponibles = {c.jugadora_id for c in convocadas if c.no_disponible}
    ids_salen = (cancha_actual_set - target_set) - no_disponibles
    # En target pero NO en cancha → ENTRAN (faltan)
    # Excluyendo a las que están marcadas no disponibles
    ids_entran = (target_set - cancha_actual_set) - no_disponibles

    if ids_salen or ids_entran:
        jugs_relevantes = Jugadora.query.filter(
            Jugadora.id.in_(ids_salen | ids_entran)
        ).all()
        jugs_dict = {j.id: j for j in jugs_relevantes}

        for jid in ids_salen:
            if jid in jugs_dict:
                j = jugs_dict[jid]
                cambios.append({
                    'tipo': 'sale', 'jugadora_id': jid,
                    'nombre': j.nombre, 'apellido': j.apellido,
                    'iniciales': j.iniciales, 'posicion': j.posicion,
                })
        for jid in ids_entran:
            if jid in jugs_dict:
                j = jugs_dict[jid]
                cambios.append({
                    'tipo': 'entra', 'jugadora_id': jid,
                    'nombre': j.nombre, 'apellido': j.apellido,
                    'iniciales': j.iniciales, 'posicion': j.posicion,
                })

    # segundos_hasta_cambio solo cuando la cancha está alineada con T_actual
    # (vamos a tiempo) y el target es T_proximo
    segundos_a_devolver = None
    if target_turno == turno_proximo_n and cancha_alineada_actual:
        segundos_a_devolver = segundos_hasta_cambio

    return {
        'tiene_plan': True,
        'turno_actual': turno_actual_n,
        'turno_proximo': turno_proximo_n,
        'turno_objetivo': target_turno,
        'turnos_total': n_turnos_total,
        'duracion_turno_min': duracion_turno,
        'cuarto': cuarto,
        'segundos_hasta_cambio': segundos_a_devolver,
        'proximo_en_mismo_cuarto': proximo_en_mismo_cuarto,
        'cambios_proximos': cambios,
        'plan_actual_ids': list(plan_actual_set),
        'cancha_alineada_actual': cancha_alineada_actual,
        'cancha_alineada': cancha_alineada_target,
        'atrasado': False,
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
    """Arranca el partido en el primer cuarto y pone titulares del T1 en cancha."""
    entrenador = entrenador_actual()
    partido = Partido.query.filter_by(id=partido_id, entrenador_id=entrenador.id).first_or_404()

    if partido.estado == 'pendiente':
        partido.estado = 'en_curso'
        partido.cuarto_actual = 1
        partido.cronometro_segundos = 0
        partido.cronometro_iniciado = None  # Inicia pausado, el entrenador toca "play"

        # Si hay un plan, poner las titulares del T1 en cancha automáticamente
        plan = PlanificacionPartido.query.filter_by(partido_id=partido.id).first()
        if plan:
            asign_t1 = AsignacionTurno.query.filter_by(plan_id=plan.id, turno_numero=1).all()
            ids_titulares = {a.jugadora_id for a in asign_t1}
            # Marcar en_cancha=True a las titulares y False a las demás convocadas
            for c in partido.convocadas:
                c.en_cancha = c.jugadora_id in ids_titulares

    db.session.commit()
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

    elif accion == 'ajustar':
        # Ajustar el cronómetro sumando o restando segundos
        # Recibe ?delta=N en query o JSON con {"delta": N}
        delta = request.args.get('delta', type=int)
        if delta is None:
            data = request.get_json(silent=True) or {}
            delta = int(data.get('delta', 0))

        # Pausar primero si estaba corriendo, ajustar, y volver a poner play si estaba
        estaba_corriendo = partido.cronometro_iniciado is not None
        if estaba_corriendo:
            ahora = datetime.utcnow()
            delta_t = (ahora - partido.cronometro_iniciado).total_seconds()
            partido.cronometro_segundos += int(delta_t)
            partido.cronometro_iniciado = None
            # Acumular segundos jugados de las que están en cancha
            for c in partido.convocadas:
                if c.en_cancha and c.ultimo_ingreso:
                    delta_j = (ahora - c.ultimo_ingreso).total_seconds()
                    c.segundos_jugados += int(delta_j)
                    c.ultimo_ingreso = None

        # Aplicar el delta. El cronómetro de un cuarto va de 0 a 900 segundos (15 min).
        nuevo_segundos = partido.cronometro_segundos + delta
        nuevo_segundos = max(0, min(nuevo_segundos, 900))  # clamp [0, 900]
        partido.cronometro_segundos = nuevo_segundos

        # Volver a poner play si estaba corriendo
        if estaba_corriendo:
            ahora = datetime.utcnow()
            partido.cronometro_iniciado = ahora
            for c in partido.convocadas:
                if c.en_cancha:
                    c.ultimo_ingreso = ahora

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
        # Resetear cronometro_iniciado para que cronometro_actual calcule desde 0
        if partido.cronometro_iniciado:
            partido.cronometro_iniciado = datetime.utcnow()
    elif accion == 'anterior' and partido.cuarto_actual > 1:
        partido.cuarto_actual -= 1
        partido.cronometro_segundos = 0
        if partido.cronometro_iniciado:
            partido.cronometro_iniciado = datetime.utcnow()

    db.session.commit()
    return jsonify(_serializar_estado(partido))


@app.route('/partido/<int:partido_id>/jugadora/<int:jugadora_id>/candidatas_no_disponible')
@login_requerido
def partido_jugadora_candidatas_no_disponible(partido_id, jugadora_id):
    """
    Devuelve las candidatas del banco para reemplazar a una jugadora que vamos
    a marcar como no disponible. Las ordena por:
    1. Misma posición
    2. Posición alternativa
    3. Otras
    """
    entrenador = entrenador_actual()
    partido = Partido.query.filter_by(id=partido_id, entrenador_id=entrenador.id).first_or_404()
    convocatoria = ConvocatoriaPartido.query.filter_by(
        partido_id=partido_id, jugadora_id=jugadora_id).first_or_404()

    jugadora_que_sale = convocatoria.jugadora
    posicion_busca = jugadora_que_sale.posicion

    # Buscar todas las convocadas del partido que no son la que sale, no están en cancha, y no están marcadas no disponible
    convocadas = ConvocatoriaPartido.query.filter_by(partido_id=partido_id).all()

    candidatas = []
    for c in convocadas:
        if c.jugadora_id == jugadora_id:
            continue
        if c.no_disponible:
            continue
        if c.en_cancha:
            # Si ya está en cancha NO puede reemplazar (no podemos sacar otra para meterla)
            continue
        j = c.jugadora
        # Determinar tipo: misma posición / alternativa / otra
        if j.posicion == posicion_busca:
            tipo = 'misma'
            orden = 1
        elif j.posicion_alt and j.posicion_alt == posicion_busca:
            tipo = 'alternativa'
            orden = 2
        else:
            tipo = 'otra'
            orden = 3
        candidatas.append({
            'jugadora_id': j.id,
            'nombre': j.nombre,
            'apellido': j.apellido,
            'iniciales': j.iniciales,
            'posicion': j.posicion,
            'posicion_alt': j.posicion_alt,
            'tipo': tipo,
            'orden': orden,
        })

    candidatas.sort(key=lambda c: (c['orden'], c['apellido']))

    return jsonify({
        'ok': True,
        'jugadora_sale': {
            'id': jugadora_que_sale.id,
            'nombre': jugadora_que_sale.nombre,
            'apellido': jugadora_que_sale.apellido,
            'posicion': jugadora_que_sale.posicion,
        },
        'esta_en_cancha': convocatoria.en_cancha,
        'candidatas': candidatas,
    })


@app.route('/partido/<int:partido_id>/jugadora/<int:jugadora_id>/marcar_no_disponible', methods=['POST'])
@login_requerido
def partido_jugadora_marcar_no_disponible(partido_id, jugadora_id):
    """
    Marca a una jugadora como no disponible para el resto del partido.

    Body JSON:
    - motivo: 'se_fue' / 'lesionada' / 'otro'
    - reemplazo_id: ID de la jugadora del banco que la reemplaza (si está en cancha)

    Si la jugadora está en cancha → la saca y mete al reemplazo.
    Si no está en cancha → solo la marca como no disponible (no se necesita reemplazo).
    """
    entrenador = entrenador_actual()
    partido = Partido.query.filter_by(id=partido_id, entrenador_id=entrenador.id).first_or_404()
    convocatoria = ConvocatoriaPartido.query.filter_by(
        partido_id=partido_id, jugadora_id=jugadora_id).first_or_404()

    data = request.get_json() or {}
    motivo = data.get('motivo', 'otro')
    reemplazo_id = data.get('reemplazo_id')

    if motivo not in ['se_fue', 'lesionada', 'otro']:
        return jsonify({'ok': False, 'error': 'Motivo inválido'}), 400

    estaba_en_cancha = convocatoria.en_cancha

    # Si está en cancha, hay que tener reemplazo
    if estaba_en_cancha and not reemplazo_id:
        return jsonify({'ok': False, 'error': 'Necesita reemplazo si está en cancha'}), 400

    if reemplazo_id:
        # Validar que el reemplazo existe, es del partido, no está en cancha, no está no disponible
        reemp = ConvocatoriaPartido.query.filter_by(
            partido_id=partido_id, jugadora_id=reemplazo_id).first()
        if not reemp:
            return jsonify({'ok': False, 'error': 'Reemplazo no convocado'}), 400
        if reemp.en_cancha:
            return jsonify({'ok': False, 'error': 'Reemplazo ya está en cancha'}), 400
        if reemp.no_disponible:
            return jsonify({'ok': False, 'error': 'Reemplazo está marcado no disponible'}), 400

    ahora = datetime.utcnow()
    cuarto = partido.cuarto_actual or 1
    crono_seg = partido.cronometro_actual

    # === Sacar la jugadora de cancha (si estaba) ===
    if estaba_en_cancha:
        if convocatoria.ultimo_ingreso and partido.cronometro_iniciado:
            # Sumar el tiempo jugado hasta ahora
            ref = max(convocatoria.ultimo_ingreso, partido.cronometro_iniciado)
            delta = (ahora - ref).total_seconds()
            convocatoria.segundos_jugados += int(delta)
        convocatoria.en_cancha = False
        convocatoria.ultimo_ingreso = None

        # Registrar evento de salida
        db.session.add(EventoPartido(
            partido_id=partido.id,
            tipo='salida',
            cuarto=cuarto,
            minuto=crono_seg // 60,
            segundo=crono_seg % 60,
            jugadora_id=convocatoria.jugadora_id,
            detalle=f"Sale {convocatoria.jugadora.nombre} {convocatoria.jugadora.apellido} ({motivo})",
        ))

    # === Marcar como no disponible ===
    convocatoria.no_disponible = True
    convocatoria.no_disponible_motivo = motivo
    convocatoria.no_disponible_cuarto = cuarto
    convocatoria.no_disponible_segundo = crono_seg

    # === Meter el reemplazo (si corresponde) ===
    if reemplazo_id and estaba_en_cancha:
        reemp.en_cancha = True
        reemp.ultimo_ingreso = ahora if partido.cronometro_iniciado else None

        # Registrar evento de entrada
        db.session.add(EventoPartido(
            partido_id=partido.id,
            tipo='entrada',
            cuarto=cuarto,
            minuto=crono_seg // 60,
            segundo=crono_seg % 60,
            jugadora_id=reemp.jugadora_id,
            detalle=f"Entra {reemp.jugadora.nombre} {reemp.jugadora.apellido} (reemplaza)",
        ))

    db.session.commit()

    return jsonify(_serializar_estado(partido))


@app.route('/partido/<int:partido_id>/jugadora/<int:jugadora_id>/desmarcar_no_disponible', methods=['POST'])
@login_requerido
def partido_jugadora_desmarcar_no_disponible(partido_id, jugadora_id):
    """Si te equivocaste al marcar, esto deshace el 'no disponible' (no la mete en cancha)."""
    entrenador = entrenador_actual()
    partido = Partido.query.filter_by(id=partido_id, entrenador_id=entrenador.id).first_or_404()
    convocatoria = ConvocatoriaPartido.query.filter_by(
        partido_id=partido_id, jugadora_id=jugadora_id).first_or_404()

    convocatoria.no_disponible = False
    convocatoria.no_disponible_motivo = None
    convocatoria.no_disponible_cuarto = None
    convocatoria.no_disponible_segundo = None
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
# RUTAS DE ROTACIÓN (Etapa 1: configuración + plan)
# ============================================================
@app.route('/partido/<int:partido_id>/rotacion/configurar', methods=['GET', 'POST'])
@login_requerido
def rotacion_configurar(partido_id):
    """Pantalla de configuración del módulo de rotación para un partido."""
    entrenador = entrenador_actual()
    eq_actual = equipo_actual()
    partido = Partido.query.filter_by(id=partido_id, entrenador_id=entrenador.id).first_or_404()
    config = ConfiguracionPartido.query.filter_by(partido_id=partido.id).first()

    jugadoras = Jugadora.query.filter_by(equipo_id=eq_actual.id).order_by(Jugadora.apellido).all()
    convocadas_ids = {c.jugadora_id for c in partido.convocadas}

    if request.method == 'POST':
        try:
            K = float(request.form.get('K', 0.7))
            if not (0.6 <= K <= 0.9):
                K = 0.7
            formacion = request.form.get('formacion', '4-3-3')
            if formacion not in FORMACIONES:
                formacion = '4-3-3'
            modo = request.form.get('modo', 'libre')
            if modo not in ['libre', 'celulas', 'bloques']:
                modo = 'libre'
            umbral = float(request.form.get('umbral', 5.0))
            anclas_lista = request.form.getlist('anclas')

            if config is None:
                config = ConfiguracionPartido(partido_id=partido.id)
                db.session.add(config)
            config.K = K
            config.formacion = formacion
            config.modo = modo
            config.umbral_cambio_minutos = umbral
            config.tiempo_pre_alerta_minutos = 1.0
            config.set_anclas([int(x) for x in anclas_lista])

            db.session.commit()
            flash('Configuración de rotación guardada', 'success')
            return redirect(url_for('rotacion_plan', partido_id=partido.id))
        except Exception as e:
            flash(f'Error al guardar: {str(e)}', 'error')

    # Solo mostrar convocadas como candidatas a ancla
    jugadoras_convocadas = [j for j in jugadoras if j.id in convocadas_ids]

    return render_template(
        'rotacion_configurar.html',
        entrenador=entrenador,
        partido=partido,
        config=config,
        jugadoras_convocadas=jugadoras_convocadas,
        formaciones=list(FORMACIONES.keys())
    )


@app.route('/partido/<int:partido_id>/rotacion/sugerencias')
@login_requerido
def rotacion_sugerencias(partido_id):
    """
    Endpoint AJAX para la tabla de sugerencias en vivo.
    Devuelve para cada convocada: min teóricos, min jugados (en tiempo real), déficit.
    """
    entrenador = entrenador_actual()
    eq_actual = equipo_actual()
    partido = Partido.query.filter_by(id=partido_id, entrenador_id=entrenador.id).first_or_404()
    config = ConfiguracionPartido.query.filter_by(partido_id=partido.id).first()

    if config is None:
        return jsonify({'ok': False, 'error': 'Sin configuración de rotación'}), 404

    if not partido.convocadas:
        return jsonify({'ok': True, 'jugadoras': []})

    # Construir el plan teórico
    jugadoras = Jugadora.query.filter_by(equipo_id=eq_actual.id).all()
    try:
        mc = rotacion_adapter.crear_match_controller(partido, jugadoras, config)
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

    # Mapa: jugadora_id → minutos teóricos calculados
    teoricos = {p.id: p.minutos_teoricos for p in mc.players}

    # Para los minutos reales jugados, leemos directo de la base
    # (segundos_jugados acumulados en ConvocatoriaPartido + lo que está en cancha ahora)
    resultado = []
    for conv in partido.convocadas:
        j = conv.jugadora
        teorico_min = round(teoricos.get(j.id, 0), 1)

        # Min reales jugados (incluye el tiempo en cancha si está corriendo)
        seg_jugados = conv.segundos_jugados
        if conv.en_cancha and conv.ultimo_ingreso and partido.cronometro_iniciado:
            from datetime import datetime as dt
            delta = (dt.utcnow() - conv.ultimo_ingreso).total_seconds()
            seg_jugados += int(delta)
        jugados_min = round(seg_jugados / 60, 1)

        deficit = round(teorico_min - jugados_min, 1)

        # Estado de alerta visual
        if conv.en_cancha:
            estado = 'en_cancha'
        else:
            estado = 'banco'

        resultado.append({
            'jugadora_id': j.id,
            'nombre': j.nombre,
            'apellido': j.apellido,
            'iniciales': j.iniciales,
            'posicion': j.posicion,
            'es_ancla': j.id in config.anclas_set,
            'estado': estado,
            'teoricos': teorico_min,
            'jugados': jugados_min,
            'deficit': deficit,
        })

    # Ordenar: primero por mayor déficit (las que más les falta)
    resultado.sort(key=lambda x: x['deficit'], reverse=True)

    return jsonify({
        'ok': True,
        'jugadoras': resultado,
        'config': {
            'K': config.K,
            'formacion': config.formacion,
            'modo': config.modo,
        }
    })


@app.route('/partido/<int:partido_id>/rotacion/plan')
@login_requerido
def rotacion_plan(partido_id):
    """Pantalla de plan del partido: prioridad calculada y minutos teóricos."""
    entrenador = entrenador_actual()
    eq_actual = equipo_actual()
    partido = Partido.query.filter_by(id=partido_id, entrenador_id=entrenador.id).first_or_404()
    config = ConfiguracionPartido.query.filter_by(partido_id=partido.id).first()

    if config is None:
        flash('Primero configurá la rotación del partido', 'error')
        return redirect(url_for('rotacion_configurar', partido_id=partido.id))

    if not partido.convocadas:
        flash('Este partido no tiene jugadoras convocadas. Editalo y agregá convocadas.', 'error')
        return redirect(url_for('partido_editar', partido_id=partido.id))

    # Construir el MatchController con los datos reales
    jugadoras = Jugadora.query.filter_by(equipo_id=eq_actual.id).all()

    try:
        mc = rotacion_adapter.crear_match_controller(partido, jugadoras, config)
        # Asignar titulares automáticamente para mostrarlos
        titulares = mc.asignar_titulares_automaticos()
    except Exception as e:
        flash(f'Error al calcular el plan: {str(e)}', 'error')
        return redirect(url_for('rotacion_configurar', partido_id=partido.id))

    # Agrupar players por posición para la vista
    from rotacion_module import Posicion as PosEnum, Estado as EstEnum
    POS_ORDER = [PosEnum.ARQUERA, PosEnum.DEFENSORA, PosEnum.VOLANTE, PosEnum.DELANTERA]

    grupos = {pos: {'titulares': [], 'banco': [], 'no_convocadas': []} for pos in POS_ORDER}
    for p in mc.players:
        if p.posicion not in grupos:
            continue
        if p.estado == EstEnum.EN_CANCHA:
            grupos[p.posicion]['titulares'].append(p)
        elif p.estado == EstEnum.BANCO:
            grupos[p.posicion]['banco'].append(p)
        else:
            grupos[p.posicion]['no_convocadas'].append(p)

    # Ordenar cada subgrupo por prioridad desc
    for pos in POS_ORDER:
        for k in ['titulares', 'banco', 'no_convocadas']:
            grupos[pos][k].sort(key=lambda x: x.prioridad, reverse=True)

    return render_template(
        'rotacion_plan.html',
        entrenador=entrenador,
        partido=partido,
        config=config,
        grupos=grupos,
        pos_order=[pos.value for pos in POS_ORDER]
    )


# ============================================================
# RUTAS DEL PLANIFICADOR DE TURNOS (Etapa A1: configuración + generación)
# ============================================================
@app.route('/partido/<int:partido_id>/planificador/configurar', methods=['GET', 'POST'])
@login_requerido
def planificador_configurar(partido_id):
    """Pantalla de configuración del plan: elegir duración del turno."""
    entrenador = entrenador_actual()
    eq_actual = equipo_actual()
    partido = Partido.query.filter_by(id=partido_id, entrenador_id=entrenador.id).first_or_404()
    config = ConfiguracionPartido.query.filter_by(partido_id=partido.id).first()

    # Validar pre-requisitos
    if config is None:
        flash('Primero configurá la rotación del partido (K, formación, anclas)', 'error')
        return redirect(url_for('rotacion_configurar', partido_id=partido.id))

    if not partido.convocadas:
        flash('Este partido no tiene jugadoras convocadas. Editalo y agregá convocadas.', 'error')
        return redirect(url_for('partido_editar', partido_id=partido.id))

    plan = PlanificacionPartido.query.filter_by(partido_id=partido.id).first()

    if request.method == 'POST':
        try:
            duracion = float(request.form.get('duracion_turno', 5.0))
            if not (3.0 <= duracion <= 7.5):
                flash('La duración del turno debe estar entre 3 y 7.5 minutos', 'error')
                return redirect(url_for('planificador_configurar', partido_id=partido.id))

            # Verificar que dé un múltiplo razonable de 60 minutos
            cantidad_turnos = round(60 / duracion)
            if cantidad_turnos < 8 or cantidad_turnos > 20:
                flash('La duración elegida genera muchos pocos o muchos turnos', 'error')
                return redirect(url_for('planificador_configurar', partido_id=partido.id))

            # Modo de generación: 'completo', 'titulares', 'mantener'
            modo_generacion = request.form.get('modo_generacion', 'completo')

            # Crear o actualizar el plan
            if plan is None:
                plan = PlanificacionPartido(partido_id=partido.id, duracion_turno_min=duracion)
                db.session.add(plan)
                db.session.flush()
            else:
                # Si cambió la duración o se pidió regenerar, borramos asignaciones existentes
                if plan.duracion_turno_min != duracion or modo_generacion != 'mantener':
                    AsignacionTurno.query.filter_by(plan_id=plan.id).delete()
                    plan.duracion_turno_min = duracion

            db.session.flush()

            # Generar plan según modo
            if modo_generacion in ('completo', 'titulares'):
                jugadoras = Jugadora.query.filter_by(equipo_id=eq_actual.id).all()
                mc = rotacion_adapter.crear_match_controller(partido, jugadoras, config)

                if modo_generacion == 'completo':
                    from planificador_logic import generar_plan_automatico
                    plan_dict = generar_plan_automatico(
                        mc.players,
                        duracion_turno=duracion,
                        formacion=config.formacion,
                        anclas_ids=config.anclas_set,
                    )
                else:  # 'titulares' → cascada
                    from planificador_logic import generar_titulares_y_cascada
                    plan_dict = generar_titulares_y_cascada(
                        mc.players,
                        duracion_turno=duracion,
                        formacion=config.formacion,
                        anclas_ids=config.anclas_set,
                    )

                # Persistir las asignaciones con slot
                for turno_n, asignaciones_turno in plan_dict.items():
                    for jid, slot in asignaciones_turno:
                        db.session.add(AsignacionTurno(
                            plan_id=plan.id, jugadora_id=jid,
                            turno_numero=turno_n, slot_indice=slot
                        ))

            db.session.commit()
            flash('Plan guardado', 'success')
            return redirect(url_for('planificador_ver', partido_id=partido.id))
        except Exception as e:
            db.session.rollback()
            flash(f'Error al guardar: {str(e)}', 'error')

    # Si ya hay plan, mostrar info
    cantidad_actual = plan.cantidad_turnos if plan else 0
    duracion_actual = plan.duracion_turno_min if plan else 5.0
    tiene_asignaciones = (plan and len(plan.asignaciones) > 0) if plan else False

    return render_template(
        'planificador_configurar.html',
        entrenador=entrenador,
        partido=partido,
        config=config,
        plan=plan,
        cantidad_actual=cantidad_actual,
        duracion_actual=duracion_actual,
        tiene_asignaciones=tiene_asignaciones,
    )


@app.route('/partido/<int:partido_id>/planificador')
@login_requerido
def planificador_ver(partido_id):
    """
    Pantalla principal del planificador con cancha visual y tap-to-swap.
    """
    entrenador = entrenador_actual()
    partido = Partido.query.filter_by(id=partido_id, entrenador_id=entrenador.id).first_or_404()
    plan = PlanificacionPartido.query.filter_by(partido_id=partido.id).first()
    config = ConfiguracionPartido.query.filter_by(partido_id=partido.id).first()

    if plan is None:
        return redirect(url_for('planificador_configurar', partido_id=partido.id))

    return render_template(
        'planificador_ver.html',
        entrenador=entrenador,
        partido=partido,
        plan=plan,
        config=config,
    )


def _armar_datos_plan(partido, entrenador):
    """
    Arma el dict con todo el estado del plan para devolver al frontend.
    Lo usan los endpoints /datos, /swap y /swap_bloque.
    """
    plan = PlanificacionPartido.query.filter_by(partido_id=partido.id).first()
    if not plan:
        return None
    config = ConfiguracionPartido.query.filter_by(partido_id=partido.id).first()

    # El equipo del partido (puede ser != equipo activo si llegamos por URL directa)
    equipo_id_partido = partido.equipo_id

    # Convocadas
    convocadas_ids = {c.jugadora_id for c in partido.convocadas}
    jugadoras = Jugadora.query.filter(
        Jugadora.entrenador_id == entrenador.id,
        Jugadora.id.in_(convocadas_ids) if convocadas_ids else False
    ).all()

    # Mapeo de posiciones del modelo a las 4 estándar del módulo
    POS_NORMALIZACION = {
        'Mediocampista': 'Volante',
    }
    def normalizar_pos(pos):
        return POS_NORMALIZACION.get(pos, pos) if pos else pos

    # Calcular minutos teóricos por jugadora usando el módulo de rotación
    minutos_teoricos_por_id = {}
    if config:
        try:
            todas_jugadoras = Jugadora.query.filter_by(equipo_id=equipo_id_partido).all()
            mc = rotacion_adapter.crear_match_controller(partido, todas_jugadoras, config)
            for pl in mc.players:
                minutos_teoricos_por_id[pl.id] = pl.minutos_teoricos
        except Exception:
            minutos_teoricos_por_id = {}

    duracion_turno = plan.duracion_turno_min

    # Cargar bloques del partido y mapear jugadora → lista de bloques
    bloques_partido = BloqueRotacion.query.filter_by(partido_id=partido.id).all()
    bloques_por_jugadora = {}
    for bloque in bloques_partido:
        for miembro in bloque.miembros:
            bloques_por_jugadora.setdefault(miembro.jugadora_id, []).append({
                'id': bloque.id,
                'nombre': bloque.nombre,
                'color': bloque.color,
            })

    # Cargar TODAS las asignaciones del plan en una sola query (mucho más rápido
    # que hacerlo N veces en un loop)
    todas_asignaciones = AsignacionTurno.query.filter_by(plan_id=plan.id).all()

    # Indexar por turno y por jugadora para evitar recorridos múltiples
    asignaciones_por_turno = {}
    turnos_por_jugadora = {}
    for a in todas_asignaciones:
        asignaciones_por_turno.setdefault(a.turno_numero, []).append(a)
        turnos_por_jugadora.setdefault(a.jugadora_id, []).append(a.turno_numero)

    jugs_data = {}
    for j in jugadoras:
        turnos_asignados = sorted(turnos_por_jugadora.get(j.id, []))
        cantidad_planificados = len(turnos_asignados)
        minutos_teor = minutos_teoricos_por_id.get(j.id, 0)
        if duracion_turno > 0 and minutos_teor > 0:
            turnos_teoricos = max(1, round(minutos_teor / duracion_turno))
        else:
            turnos_teoricos = 0

        jugs_data[j.id] = {
            'id': j.id,
            'nombre': j.nombre,
            'apellido': j.apellido,
            'iniciales': j.iniciales,
            'posicion': normalizar_pos(j.posicion),
            'posicion_alt': normalizar_pos(j.posicion_alt),
            'es_ancla': bool(config and j.id in config.anclas_set),
            'cantidad_turnos': cantidad_planificados,
            'turnos': turnos_asignados,
            'minutos_planeados': cantidad_planificados * duracion_turno,
            'turnos_teoricos': turnos_teoricos,
            'minutos_teoricos': round(minutos_teor, 1),
            'bloques': bloques_por_jugadora.get(j.id, []),
        }

    # Por cada turno, lista de {jugadora_id, slot_indice}
    turnos_data = {}
    for n in range(1, plan.cantidad_turnos + 1):
        asigs = asignaciones_por_turno.get(n, [])
        turnos_data[n] = [
            {'jugadora_id': a.jugadora_id, 'slot': a.slot_indice}
            for a in asigs
        ]

    bloques_data = [
        {
            'id': b.id,
            'nombre': b.nombre,
            'color': b.color,
            'jugadoras_ids': b.jugadoras_ids,
        }
        for b in bloques_partido
    ]

    # Calcular promedio de capacidad por turno
    cap_por_jugadora = {j.id: j.calificacion for j in jugadoras}
    promedios_por_turno = {}
    for turno_n in range(1, plan.cantidad_turnos + 1):
        ids_en_turno = [a['jugadora_id'] for a in turnos_data.get(turno_n, [])]
        if not ids_en_turno:
            promedios_por_turno[str(turno_n)] = None
            continue
        caps = [cap_por_jugadora.get(jid, 0) for jid in ids_en_turno]
        prom = sum(caps) / len(caps) if caps else 0
        promedios_por_turno[str(turno_n)] = round(prom, 2)

    return {
        'plan': {
            'id': plan.id,
            'duracion_turno_min': plan.duracion_turno_min,
            'cantidad_turnos': plan.cantidad_turnos,
        },
        'config': {
            'formacion': config.formacion if config else '4-3-3',
            'K': config.K if config else 0.7,
        },
        'turnos': turnos_data,
        'promedios_capacidad': promedios_por_turno,
        'jugadoras': jugs_data,
        'bloques': bloques_data,
    }


@app.route('/partido/<int:partido_id>/planificador/datos')
@login_requerido
def planificador_datos(partido_id):
    """
    Devuelve el estado completo del plan en JSON para el frontend.
    """
    entrenador = entrenador_actual()
    partido = Partido.query.filter_by(id=partido_id, entrenador_id=entrenador.id).first_or_404()
    plan = PlanificacionPartido.query.filter_by(partido_id=partido.id).first_or_404()  # noqa: F841

    datos = _armar_datos_plan(partido, entrenador)
    if datos is None:
        return jsonify({'ok': False, 'error': 'Plan no encontrado'}), 404

    return jsonify({'ok': True, **datos})


@app.route('/partido/<int:partido_id>/planificador/swap', methods=['POST'])
@login_requerido
def planificador_swap(partido_id):
    """
    Intercambia dos jugadoras en un turno específico. Soporta dos casos:

    1. CANCHA-BANCO: una está en el turno (sale), la otra no (entra).
       La que entra ocupa el slot que tenía la que sale.

    2. CANCHA-CANCHA: ambas están en el turno. Se intercambian los slots.

    No hay restricción de posición: si la entrenadora quiere cambiar una
    defensora por una delantera, se permite.
    """
    entrenador = entrenador_actual()
    partido = Partido.query.filter_by(id=partido_id, entrenador_id=entrenador.id).first_or_404()
    plan = PlanificacionPartido.query.filter_by(partido_id=partido.id).first_or_404()

    data = request.get_json()
    turno_n = int(data.get('turno', 0))
    j1_id = int(data.get('j1_id', data.get('sale_id', 0)))  # acepta ambos nombres por compat
    j2_id = int(data.get('j2_id', data.get('entra_id', 0)))

    if turno_n < 1 or turno_n > plan.cantidad_turnos:
        return jsonify({'ok': False, 'error': 'Turno inválido'}), 400
    if j1_id == j2_id:
        return jsonify({'ok': False, 'error': 'No se puede intercambiar una jugadora consigo misma'}), 400

    j1 = Jugadora.query.filter_by(id=j1_id, entrenador_id=entrenador.id).first()
    j2 = Jugadora.query.filter_by(id=j2_id, entrenador_id=entrenador.id).first()
    if not j1 or not j2:
        return jsonify({'ok': False, 'error': 'Jugadora no encontrada'}), 404

    # Validar que ambas estén convocadas
    convocadas_ids = {c.jugadora_id for c in partido.convocadas}
    if j1.id not in convocadas_ids or j2.id not in convocadas_ids:
        return jsonify({'ok': False, 'error': 'Una de las jugadoras no está convocada'}), 400

    # Buscar las asignaciones existentes
    asign_j1 = AsignacionTurno.query.filter_by(
        plan_id=plan.id, jugadora_id=j1.id, turno_numero=turno_n
    ).first()
    asign_j2 = AsignacionTurno.query.filter_by(
        plan_id=plan.id, jugadora_id=j2.id, turno_numero=turno_n
    ).first()

    # Helper: aplicar cascada hacia adelante.
    # Para cada turno > turno_n, si "sale_id" todavía está en ese turno (con algún slot),
    # reemplazarla por "entra_id" en el mismo slot. Si en ese turno ya no estaba sale_id
    # (porque hubo otro cambio manual posterior), no tocamos nada y cortamos la cascada.
    def aplicar_cascada(sale_id: int, entra_id: int, desde_turno: int):
        cascada_aplicada = 0
        for t in range(desde_turno + 1, plan.cantidad_turnos + 1):
            # Si entra_id ya está en t (caso poco común pero posible), saltamos
            ya_entra = AsignacionTurno.query.filter_by(
                plan_id=plan.id, jugadora_id=entra_id, turno_numero=t
            ).first()
            if ya_entra:
                # entra_id ya está en este turno: no podemos meterla dos veces
                # cortamos la cascada acá
                break
            asign_sale_t = AsignacionTurno.query.filter_by(
                plan_id=plan.id, jugadora_id=sale_id, turno_numero=t
            ).first()
            if not asign_sale_t:
                # sale_id ya no está en este turno (cambio manual posterior) — cortamos cascada
                break
            slot_t = asign_sale_t.slot_indice
            db.session.delete(asign_sale_t)
            db.session.flush()
            db.session.add(AsignacionTurno(
                plan_id=plan.id, jugadora_id=entra_id,
                turno_numero=t, slot_indice=slot_t
            ))
            cascada_aplicada += 1
        return cascada_aplicada

    # Caso 1: ambas están en el turno → swap de slots
    # En este caso la cascada es más compleja porque ambas estaban en el turno.
    # Aplicamos la lógica: en los turnos siguientes, si las dos siguen estando
    # con sus slots originales, intercambiamos slots. Si una ya no está, cortamos.
    if asign_j1 and asign_j2:
        slot_j1_orig = asign_j1.slot_indice
        slot_j2_orig = asign_j2.slot_indice
        # Swap en el turno actual
        asign_j1.slot_indice = slot_j2_orig
        asign_j2.slot_indice = slot_j1_orig

        # Cascada: en turnos siguientes, si ambas siguen con los slots originales, swappear
        cascada_n = 0
        for t in range(turno_n + 1, plan.cantidad_turnos + 1):
            a1 = AsignacionTurno.query.filter_by(
                plan_id=plan.id, jugadora_id=j1.id, turno_numero=t
            ).first()
            a2 = AsignacionTurno.query.filter_by(
                plan_id=plan.id, jugadora_id=j2.id, turno_numero=t
            ).first()
            if not a1 or not a2:
                break  # alguna ya no está → cortamos cascada
            # Si los slots no son los originales, también cortamos (hay cambio manual)
            if a1.slot_indice != slot_j1_orig or a2.slot_indice != slot_j2_orig:
                break
            a1.slot_indice = slot_j2_orig
            a2.slot_indice = slot_j1_orig
            cascada_n += 1

        db.session.commit()
        msg = f'{j1.nombre} ↔ {j2.nombre} (cambio de posición en cancha)'
        if cascada_n > 0:
            msg += f' · cascada en {cascada_n} turno{"s" if cascada_n != 1 else ""}'
        datos = _armar_datos_plan(partido, entrenador)
        return jsonify({'ok': True, 'mensaje': msg, **datos})

    # Caso 2: j1 está en el turno, j2 no → j1 sale, j2 entra
    if asign_j1 and not asign_j2:
        slot = asign_j1.slot_indice
        db.session.delete(asign_j1)
        db.session.flush()
        db.session.add(AsignacionTurno(
            plan_id=plan.id, jugadora_id=j2.id, turno_numero=turno_n, slot_indice=slot
        ))
        # Cascada: aplicar el mismo cambio hacia adelante
        cascada_n = aplicar_cascada(sale_id=j1.id, entra_id=j2.id, desde_turno=turno_n)
        db.session.commit()
        msg = f'{j1.nombre} ↔ {j2.nombre}'
        if cascada_n > 0:
            msg += f' · cascada en {cascada_n} turno{"s" if cascada_n != 1 else ""}'
        datos = _armar_datos_plan(partido, entrenador)
        return jsonify({'ok': True, 'mensaje': msg, **datos})

    if asign_j2 and not asign_j1:
        slot = asign_j2.slot_indice
        db.session.delete(asign_j2)
        db.session.flush()
        db.session.add(AsignacionTurno(
            plan_id=plan.id, jugadora_id=j1.id, turno_numero=turno_n, slot_indice=slot
        ))
        cascada_n = aplicar_cascada(sale_id=j2.id, entra_id=j1.id, desde_turno=turno_n)
        db.session.commit()
        msg = f'{j2.nombre} ↔ {j1.nombre}'
        if cascada_n > 0:
            msg += f' · cascada en {cascada_n} turno{"s" if cascada_n != 1 else ""}'
        datos = _armar_datos_plan(partido, entrenador)
        return jsonify({'ok': True, 'mensaje': msg, **datos})

    # Caso edge: ninguna está en el turno → no podemos intercambiar
    return jsonify({'ok': False, 'error': 'Ninguna de las dos jugadoras está en este turno'}), 400


@app.route('/partido/<int:partido_id>/planificador/swap_bloque', methods=['POST'])
@login_requerido
def planificador_swap_bloque(partido_id):
    """
    Intercambia un grupo de jugadoras (un bloque) por otras jugadoras (del banco)
    en un turno específico. Si alguna del bloque ya no está en el turno, esa pareja
    se ignora.

    Recibe:
        turno: int
        pares: [{'sale_id': int, 'entra_id': int}, ...]

    Aplica también la cascada: el mismo cambio se replica en turnos siguientes
    mientras la jugadora que sale siga en ese turno.
    """
    entrenador = entrenador_actual()
    partido = Partido.query.filter_by(id=partido_id, entrenador_id=entrenador.id).first_or_404()
    plan = PlanificacionPartido.query.filter_by(partido_id=partido.id).first_or_404()

    data = request.get_json() or {}
    turno_n = int(data.get('turno', 0))
    pares = data.get('pares', [])

    if turno_n < 1 or turno_n > plan.cantidad_turnos:
        return jsonify({'ok': False, 'error': 'Turno inválido'}), 400
    if not pares:
        return jsonify({'ok': False, 'error': 'Sin pares de swap'}), 400

    # Validar que todas las jugadoras existan y estén convocadas
    convocadas_ids = {c.jugadora_id for c in partido.convocadas}
    todas_ids = set()
    for p in pares:
        todas_ids.add(int(p['sale_id']))
        todas_ids.add(int(p['entra_id']))
    if not all(jid in convocadas_ids for jid in todas_ids):
        return jsonify({'ok': False, 'error': 'Alguna jugadora no está convocada'}), 400

    # Helper para cascada (igual que en swap individual)
    def aplicar_cascada(sale_id: int, entra_id: int, desde_turno: int):
        cascada_aplicada = 0
        for t in range(desde_turno + 1, plan.cantidad_turnos + 1):
            ya_entra = AsignacionTurno.query.filter_by(
                plan_id=plan.id, jugadora_id=entra_id, turno_numero=t
            ).first()
            if ya_entra:
                break
            asign_sale_t = AsignacionTurno.query.filter_by(
                plan_id=plan.id, jugadora_id=sale_id, turno_numero=t
            ).first()
            if not asign_sale_t:
                break
            slot_t = asign_sale_t.slot_indice
            db.session.delete(asign_sale_t)
            db.session.flush()
            db.session.add(AsignacionTurno(
                plan_id=plan.id, jugadora_id=entra_id,
                turno_numero=t, slot_indice=slot_t
            ))
            cascada_aplicada += 1
        return cascada_aplicada

    aplicados = 0
    saltados = 0
    cascada_total = 0

    for p in pares:
        sale_id = int(p['sale_id'])
        entra_id = int(p['entra_id'])

        # Buscar asignaciones actuales
        asign_sale = AsignacionTurno.query.filter_by(
            plan_id=plan.id, jugadora_id=sale_id, turno_numero=turno_n
        ).first()
        asign_entra = AsignacionTurno.query.filter_by(
            plan_id=plan.id, jugadora_id=entra_id, turno_numero=turno_n
        ).first()

        if not asign_sale:
            # La que debe salir ya no está en el turno (alguien más ya la sacó)
            saltados += 1
            continue
        if asign_entra:
            # La que debe entrar ya está en el turno (no se puede duplicar)
            saltados += 1
            continue

        # Aplicar swap en este turno
        slot = asign_sale.slot_indice
        db.session.delete(asign_sale)
        db.session.flush()
        db.session.add(AsignacionTurno(
            plan_id=plan.id, jugadora_id=entra_id,
            turno_numero=turno_n, slot_indice=slot
        ))
        aplicados += 1

        # Cascada
        cascada_total += aplicar_cascada(sale_id, entra_id, turno_n)

    db.session.commit()

    msg = f'{aplicados} cambio{"s" if aplicados != 1 else ""} aplicado{"s" if aplicados != 1 else ""}'
    if saltados > 0:
        msg += f' · {saltados} saltado{"s" if saltados != 1 else ""}'
    if cascada_total > 0:
        msg += f' · cascada en {cascada_total} turno{"s" if cascada_total != 1 else ""}'

    datos = _armar_datos_plan(partido, entrenador)
    return jsonify({'ok': True, 'mensaje': msg, 'aplicados': aplicados, 'saltados': saltados, **datos})


# ============================================================
# RUTAS DE BLOQUES (configuración + edición)
# ============================================================
COLORES_BLOQUE = ['violeta', 'ambar', 'teal', 'coral', 'rosa']


@app.route('/partido/<int:partido_id>/bloques')
@login_requerido
def bloques_lista(partido_id):
    """Lista de bloques del partido y formulario para crear/editar."""
    entrenador = entrenador_actual()
    partido = Partido.query.filter_by(id=partido_id, entrenador_id=entrenador.id).first_or_404()

    bloques = BloqueRotacion.query.filter_by(partido_id=partido.id).all()

    convocadas_ids = {c.jugadora_id for c in partido.convocadas}
    jugadoras = Jugadora.query.filter(
        Jugadora.entrenador_id == entrenador.id,
        Jugadora.id.in_(convocadas_ids) if convocadas_ids else False
    ).order_by(Jugadora.posicion, Jugadora.apellido).all()

    return render_template(
        'bloques_lista.html',
        entrenador=entrenador,
        partido=partido,
        bloques=bloques,
        jugadoras=jugadoras,
        colores=COLORES_BLOQUE,
    )


@app.route('/partido/<int:partido_id>/bloques/nuevo', methods=['POST'])
@login_requerido
def bloque_nuevo(partido_id):
    """Crear un bloque nuevo para un partido."""
    entrenador = entrenador_actual()
    partido = Partido.query.filter_by(id=partido_id, entrenador_id=entrenador.id).first_or_404()

    nombre = (request.form.get('nombre') or '').strip()
    color = request.form.get('color', 'violeta')
    jugadoras_ids = request.form.getlist('jugadoras')

    if not nombre:
        flash('El bloque necesita un nombre', 'error')
        return redirect(url_for('bloques_lista', partido_id=partido.id))
    if len(jugadoras_ids) < 2:
        flash('El bloque debe tener al menos 2 jugadoras', 'error')
        return redirect(url_for('bloques_lista', partido_id=partido.id))
    if color not in COLORES_BLOQUE:
        color = 'violeta'

    bloque = BloqueRotacion(partido_id=partido.id, nombre=nombre, color=color)
    db.session.add(bloque)
    db.session.flush()

    # Verificar que las jugadoras estén convocadas y que no se dupliquen
    convocadas_ids = {c.jugadora_id for c in partido.convocadas}
    ids_unicos = set()
    for jid_str in jugadoras_ids:
        try:
            jid = int(jid_str)
        except ValueError:
            continue
        if jid in convocadas_ids and jid not in ids_unicos:
            ids_unicos.add(jid)
            db.session.add(JugadoraBloque(bloque_id=bloque.id, jugadora_id=jid))

    db.session.commit()
    flash(f'Bloque "{nombre}" creado con {len(ids_unicos)} jugadoras', 'success')
    return redirect(url_for('bloques_lista', partido_id=partido.id))


@app.route('/partido/<int:partido_id>/bloques/<int:bloque_id>/editar', methods=['POST'])
@login_requerido
def bloque_editar(partido_id, bloque_id):
    """Editar un bloque existente."""
    entrenador = entrenador_actual()
    partido = Partido.query.filter_by(id=partido_id, entrenador_id=entrenador.id).first_or_404()
    bloque = BloqueRotacion.query.filter_by(id=bloque_id, partido_id=partido.id).first_or_404()

    nombre = (request.form.get('nombre') or '').strip()
    color = request.form.get('color', bloque.color)
    jugadoras_ids = request.form.getlist('jugadoras')

    if not nombre:
        flash('El bloque necesita un nombre', 'error')
        return redirect(url_for('bloques_lista', partido_id=partido.id))
    if len(jugadoras_ids) < 2:
        flash('El bloque debe tener al menos 2 jugadoras', 'error')
        return redirect(url_for('bloques_lista', partido_id=partido.id))
    if color not in COLORES_BLOQUE:
        color = 'violeta'

    bloque.nombre = nombre
    bloque.color = color

    # Borrar miembros actuales y agregar los nuevos
    JugadoraBloque.query.filter_by(bloque_id=bloque.id).delete()
    db.session.flush()

    convocadas_ids = {c.jugadora_id for c in partido.convocadas}
    ids_unicos = set()
    for jid_str in jugadoras_ids:
        try:
            jid = int(jid_str)
        except ValueError:
            continue
        if jid in convocadas_ids and jid not in ids_unicos:
            ids_unicos.add(jid)
            db.session.add(JugadoraBloque(bloque_id=bloque.id, jugadora_id=jid))

    db.session.commit()
    flash(f'Bloque "{nombre}" actualizado', 'success')
    return redirect(url_for('bloques_lista', partido_id=partido.id))


@app.route('/partido/<int:partido_id>/bloques/<int:bloque_id>/eliminar', methods=['POST'])
@login_requerido
def bloque_eliminar(partido_id, bloque_id):
    """Eliminar un bloque."""
    entrenador = entrenador_actual()
    partido = Partido.query.filter_by(id=partido_id, entrenador_id=entrenador.id).first_or_404()
    bloque = BloqueRotacion.query.filter_by(id=bloque_id, partido_id=partido.id).first_or_404()

    db.session.delete(bloque)
    db.session.commit()
    flash('Bloque eliminado', 'success')
    return redirect(url_for('bloques_lista', partido_id=partido.id))


# ============================================================
# RUTAS DE NOTAS
# ============================================================
@app.route('/notas')
@login_requerido
def notas_lista():
    """Lista todas las notas del entrenador (filtrable por rival)."""
    entrenador = entrenador_actual()
    rival_filtro = request.args.get('rival', '').strip()
    rival_nuevo = request.args.get('nuevo_para_rival', '').strip()

    try:
        notas = NotaPartido.query.filter_by(entrenador_id=entrenador.id).order_by(NotaPartido.creada.desc()).all()
    except Exception:
        notas = []

    try:
        rivales_con_notas = sorted(set(n.rival for n in notas if n.rival))
    except Exception:
        rivales_con_notas = []

    try:
        partidos = Partido.query.filter_by(entrenador_id=entrenador.id).all()
        rivales_partidos = sorted(set(p.rival for p in partidos if p.rival))
    except Exception:
        rivales_partidos = []

    if rival_filtro:
        notas = [n for n in notas if n.rival == rival_filtro]

    rivales_todos = sorted(set(rivales_con_notas + rivales_partidos))

    return render_template(
        'notas_lista.html',
        notas=notas,
        rivales_con_notas=rivales_con_notas,
        rivales_todos=rivales_todos,
        rival_filtro=rival_filtro,
        rival_nuevo=rival_nuevo,
    )


@app.route('/nota/nueva', methods=['POST'])
@login_requerido
def nota_nueva():
    """Crea una nueva nota."""
    entrenador = entrenador_actual()
    eq_actual = equipo_actual()

    rival = (request.form.get('rival') or '').strip()
    rival_nuevo = (request.form.get('rival_nuevo') or '').strip()
    # Si eligió "Otro rival" desde el dropdown, usar rival_nuevo
    if rival == '__nuevo__' and rival_nuevo:
        rival = rival_nuevo

    texto = (request.form.get('texto') or '').strip()
    etiquetas = (request.form.get('etiquetas') or '').strip()

    if not rival:
        return redirect(url_for('notas_lista') + '?error=rival_vacio')
    if not texto:
        return redirect(url_for('notas_lista') + '?error=texto_vacio')

    nota = NotaPartido(
        entrenador_id=entrenador.id,
        equipo_id=eq_actual.id if eq_actual else None,
        partido_id=None,
        rival=rival,
        texto=texto,
        etiquetas=etiquetas if etiquetas else None,
    )
    db.session.add(nota)
    db.session.commit()

    return redirect(url_for('notas_lista', rival=rival))


@app.route('/nota/<int:nota_id>/editar', methods=['POST'])
@login_requerido
def nota_editar(nota_id):
    """Edita una nota existente."""
    entrenador = entrenador_actual()
    nota = NotaPartido.query.filter_by(id=nota_id, entrenador_id=entrenador.id).first_or_404()

    rival = (request.form.get('rival') or '').strip()
    rival_nuevo = (request.form.get('rival_nuevo') or '').strip()
    if rival == '__nuevo__' and rival_nuevo:
        rival = rival_nuevo

    texto = (request.form.get('texto') or '').strip()
    etiquetas = (request.form.get('etiquetas') or '').strip()

    if rival:
        nota.rival = rival
    if texto:
        nota.texto = texto
    nota.etiquetas = etiquetas if etiquetas else None
    nota.actualizada = datetime.utcnow()
    db.session.commit()

    return redirect(url_for('notas_lista', rival=nota.rival))


@app.route('/nota/<int:nota_id>/borrar', methods=['POST'])
@login_requerido
def nota_borrar(nota_id):
    """Borra una nota."""
    entrenador = entrenador_actual()
    nota = NotaPartido.query.filter_by(id=nota_id, entrenador_id=entrenador.id).first_or_404()
    db.session.delete(nota)
    db.session.commit()
    return redirect(url_for('notas_lista'))


# ============================================================
# RUTAS DE ESTADÍSTICAS
# ============================================================
def _calcular_periodo(periodo_str):
    """Devuelve (fecha_inicio, fecha_fin, label) según el período seleccionado."""
    hoy = date.today()
    if periodo_str == 'mes':
        inicio = date(hoy.year, hoy.month, 1)
        fin = hoy
        label = f'{hoy.strftime("%B %Y").capitalize()}'
        return inicio, fin, label
    elif periodo_str == 'mes_anterior':
        primer_dia_mes = date(hoy.year, hoy.month, 1)
        ultimo_mes_anterior = primer_dia_mes - timedelta(days=1)
        inicio = date(ultimo_mes_anterior.year, ultimo_mes_anterior.month, 1)
        fin = ultimo_mes_anterior
        label = f'{inicio.strftime("%B %Y").capitalize()}'
        return inicio, fin, label
    elif periodo_str == 'anio':
        inicio = date(hoy.year, 1, 1)
        fin = hoy
        label = f'Año {hoy.year}'
        return inicio, fin, label
    else:  # 'todos'
        inicio = date(2000, 1, 1)
        fin = date(2100, 12, 31)
        label = 'Todos los partidos'
        return inicio, fin, label


def _stats_jugadora(jugadora, partidos):
    """Calcula PC, PJ, minutos, goles para una jugadora en una lista de partidos."""
    pc = 0  # Partidos convocados
    pj = 0  # Partidos jugados (con minutos > 0)
    minutos = 0
    goles = 0
    goles_jugada = 0
    goles_corner = 0
    goles_penal = 0
    detalle_partidos = []  # Para la vista detalle de jugadora

    for p in partidos:
        # Buscar convocatoria
        conv = next((c for c in p.convocadas if c.jugadora_id == jugadora.id), None)
        if not conv:
            continue
        pc += 1
        min_partido = conv.segundos_jugados // 60
        if min_partido > 0:
            pj += 1
        minutos += min_partido

        # Goles de esta jugadora en este partido
        goles_partido = 0
        for e in p.eventos:
            if e.tipo == 'gol_favor' and e.jugadora_id == jugadora.id:
                goles += 1
                goles_partido += 1
                if e.subtipo == 'jugada':
                    goles_jugada += 1
                elif e.subtipo == 'corner_corto':
                    goles_corner += 1
                elif e.subtipo == 'penal':
                    goles_penal += 1

        detalle_partidos.append({
            'partido': p,
            'minutos': min_partido,
            'goles': goles_partido,
            'jugo': min_partido > 0
        })

    return {
        'pc': pc,
        'pj': pj,
        'minutos': minutos,
        'goles': goles,
        'goles_jugada': goles_jugada,
        'goles_corner': goles_corner,
        'goles_penal': goles_penal,
        'promedio_min': round(minutos / pj, 1) if pj > 0 else 0,
        'detalle': detalle_partidos
    }


@app.route('/estadisticas')
@login_requerido
def estadisticas():
    entrenador = entrenador_actual()
    eq_actual = equipo_actual()
    periodo = request.args.get('periodo', 'mes')
    inicio, fin, label = _calcular_periodo(periodo)

    # Partidos del entrenador en el período (incluye en curso y finalizados, no pendientes)
    partidos = Partido.query.filter(
        Partido.entrenador_id == entrenador.id,
        Partido.fecha >= inicio,
        Partido.fecha <= fin,
        Partido.estado != 'pendiente'
    ).all()

    jugadoras = Jugadora.query.filter_by(equipo_id=eq_actual.id).order_by(Jugadora.apellido).all()

    # Calcular stats por jugadora
    stats = []
    for j in jugadoras:
        s = _stats_jugadora(j, partidos)
        if s['pc'] > 0:  # Solo mostrar jugadoras que tuvieron al menos una convocatoria
            stats.append((j, s))

    # Ordenar por minutos jugados desc
    stats.sort(key=lambda x: x[1]['minutos'], reverse=True)

    # Totales del equipo
    total_partidos = len(partidos)

    return render_template(
        'estadisticas.html',
        entrenador=entrenador,
        stats=stats,
        periodo=periodo,
        periodo_label=label,
        total_partidos=total_partidos
    )


@app.route('/jugadora/<int:jugadora_id>/estadisticas')
@login_requerido
def jugadora_estadisticas(jugadora_id):
    entrenador = entrenador_actual()
    jugadora = Jugadora.query.filter_by(id=jugadora_id, entrenador_id=entrenador.id).first_or_404()

    periodo = request.args.get('periodo', 'mes')
    inicio, fin, label = _calcular_periodo(periodo)

    partidos = Partido.query.filter(
        Partido.entrenador_id == entrenador.id,
        Partido.fecha >= inicio,
        Partido.fecha <= fin,
        Partido.estado != 'pendiente'
    ).order_by(Partido.fecha.desc()).all()

    stats = _stats_jugadora(jugadora, partidos)

    return render_template(
        'jugadora_estadisticas.html',
        entrenador=entrenador,
        jugadora=jugadora,
        stats=stats,
        periodo=periodo,
        periodo_label=label
    )


# ============================================================
# INICIALIZACIÓN
# ============================================================
with app.app_context():
    db.create_all()
    aplicar_migraciones()


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
