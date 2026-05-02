"""
Adaptador entre los modelos Flask (Jugadora, Partido) y el módulo de rotación
(Player, ConfiguracionRotacion).

Esto mantiene el módulo de rotación 100% independiente de Flask/SQLAlchemy.
"""
from rotacion_module import (
    Player, Posicion, Estado,
    ConfiguracionRotacion, ModoRotacion,
    MatchController,
)


# Mapeo de strings de tu base ↔ enums del módulo
POSICION_MAP = {
    'Arquera': Posicion.ARQUERA,
    'Defensora': Posicion.DEFENSORA,
    'Volante': Posicion.VOLANTE,
    'Delantera': Posicion.DELANTERA,
}

MODO_MAP = {
    'libre': ModoRotacion.LIBRE,
    'celulas': ModoRotacion.CELULAS,
    'bloques': ModoRotacion.BLOQUES,
}


def jugadora_a_player(jugadora, asistencia_pct: float = 100.0, convocada: bool = True) -> Player:
    """
    Convierte una Jugadora del modelo Flask en un Player del módulo de rotación.

    Args:
        jugadora: instancia de Jugadora (modelo SQLAlchemy)
        asistencia_pct: % de asistencia de la jugadora (calculado desde la app)
        convocada: si está convocada al partido (True) o no (False)
    """
    posicion = POSICION_MAP.get(jugadora.posicion, Posicion.VOLANTE)

    # Si la posición no se mapea (ej. valores legacy como "Mediocampista"),
    # caemos en Volante por defecto.

    return Player(
        id=jugadora.id,
        nombre=jugadora.nombre,
        apellido=jugadora.apellido,
        capacidad=jugadora.calificacion,
        asistencia=asistencia_pct,
        posicion=posicion,
        estado=Estado.BANCO if convocada else Estado.NO_CONVOCADA,
    )


def construir_players_para_partido(partido, jugadoras_entrenador: list) -> list:
    """
    Toma un Partido y la lista completa de jugadoras del entrenador, y arma
    la lista de Players para alimentar al MatchController.

    - Convocadas → Estado.BANCO (el controller las distribuye)
    - No convocadas → Estado.NO_CONVOCADA (el algoritmo las puede incluir o no)
    """
    convocadas_ids = {c.jugadora_id for c in partido.convocadas}
    players = []

    for j in jugadoras_entrenador:
        # Calcular asistencia de la jugadora (desde el método de la app)
        try:
            stats = j.stats_asistencia()
            asistencia_pct = stats.get('pct', 0)
        except Exception:
            asistencia_pct = 0

        convocada = j.id in convocadas_ids
        try:
            player = jugadora_a_player(j, asistencia_pct=asistencia_pct, convocada=convocada)
            players.append(player)
        except (ValueError, KeyError):
            # Si una jugadora tiene datos inválidos (ej. calificación fuera de rango),
            # la salteamos y seguimos.
            continue

    return players


def config_db_a_modulo(config_db) -> ConfiguracionRotacion:
    """
    Convierte una ConfiguracionPartido (modelo Flask) en una ConfiguracionRotacion (módulo).
    """
    if config_db is None:
        # Devolver config default
        return ConfiguracionRotacion(modo=ModoRotacion.LIBRE)

    modo = MODO_MAP.get(config_db.modo, ModoRotacion.LIBRE)

    return ConfiguracionRotacion(
        modo=modo,
        umbral_cambio_minutos=config_db.umbral_cambio_minutos,
        tiempo_pre_alerta_minutos=config_db.tiempo_pre_alerta_minutos,
        anclas_ids=config_db.anclas_set,
    )


def crear_match_controller(partido, jugadoras_entrenador: list, config_db=None):
    """
    Atajo: crea un MatchController listo para usar a partir de un Partido y la config DB.
    """
    K = 0.7
    formacion = '4-3-3'
    if config_db:
        K = config_db.K
        formacion = config_db.formacion

    players = construir_players_para_partido(partido, jugadoras_entrenador)
    config = config_db_a_modulo(config_db)

    return MatchController(players, config, K=K, formacion=formacion)
