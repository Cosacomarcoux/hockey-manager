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
# INICIALIZACIÓN
# ============================================================
with app.app_context():
    db.create_all()


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
