"""
priority.py — El algoritmo de prioridad dinámica y reparto de minutos.

Funciones puras: reciben listas de Player y números, devuelven nuevos
valores. No mutan estado externo.
"""
from typing import Iterable, Dict
from .player import Player, Posicion


# ============================================================
# CONSTANTES DE FORMACIÓN
# ============================================================
# Cada formación define cuántas jugadoras en cancha por posición.
# La arquera siempre es 1.
FORMACIONES = {
    "4-3-3": {Posicion.ARQUERA: 1, Posicion.DEFENSORA: 4, Posicion.VOLANTE: 3, Posicion.DELANTERA: 3},
    "4-4-2": {Posicion.ARQUERA: 1, Posicion.DEFENSORA: 4, Posicion.VOLANTE: 4, Posicion.DELANTERA: 2},
    "3-5-2": {Posicion.ARQUERA: 1, Posicion.DEFENSORA: 3, Posicion.VOLANTE: 5, Posicion.DELANTERA: 2},
    "5-3-2": {Posicion.ARQUERA: 1, Posicion.DEFENSORA: 5, Posicion.VOLANTE: 3, Posicion.DELANTERA: 2},
    "4-2-3-1": {Posicion.ARQUERA: 1, Posicion.DEFENSORA: 4, Posicion.VOLANTE: 5, Posicion.DELANTERA: 1},
}

# Duración total del partido en minutos
DURACION_PARTIDO = 60  # 4 cuartos de 15 minutos


# ============================================================
# CÁLCULO DE PRIORIDAD INDIVIDUAL
# ============================================================
def calcular_prioridad(player: Player, K: float) -> float:
    """
    Calcula la prioridad P de una jugadora.

    P = (C * K) + (A * (1 - K))

    Donde:
      C = capacidad normalizada (1-5 → 0.2-1.0)
      A = asistencia normalizada (0-100% → 0.0-1.0)
      K = factor de competitividad (0.6 a 0.9)

    K alto (0.9) → priorizamos capacidad sobre asistencia (modo competitivo)
    K bajo (0.6) → priorizamos asistencia sobre capacidad (modo formativo)

    Devuelve un float entre 0.0 y 1.0.
    """
    if not (0.6 <= K <= 0.9):
        raise ValueError(f"K debe estar entre 0.6 y 0.9, llegó {K}")

    C = player.capacidad_normalizada
    A = player.asistencia_normalizada
    return (C * K) + (A * (1 - K))


def asignar_prioridades(players: Iterable[Player], K: float) -> None:
    """Mutea la lista de Player asignando .prioridad a cada uno."""
    for p in players:
        p.prioridad = calcular_prioridad(p, K)


# ============================================================
# REPARTO DE MINUTOS TEÓRICOS POR POSICIÓN
# ============================================================
def repartir_minutos_por_posicion(
    players: Iterable[Player],
    formacion: str = "4-3-3",
    duracion: int = DURACION_PARTIDO,
    incluir_no_convocadas: bool = False,
) -> Dict[Posicion, list]:
    """
    Reparte los minutos disponibles entre las jugadoras de cada posición,
    proporcionalmente a su prioridad P, con TOPE de `duracion` (60 min) por jugadora.

    Reglas:
    - Cada posición tiene N jugadoras en cancha simultáneamente (según formación).
    - Total minutos-jugadora por posición = N × duración del partido.
    - Esos minutos se reparten entre las jugadoras de esa posición proporcional a P.
    - Una jugadora NUNCA puede recibir más de `duracion` (60 min) — porque solo
      hay un partido. Si la fórmula proporcional le diera más, se le pone 60 y
      el excedente se redistribuye entre las demás (proceso iterativo).
    - Por defecto, las NO_CONVOCADA se excluyen del reparto.

    Devuelve un dict: {posicion: [Player ordenados por prioridad desc]}
    Mutea cada Player asignando .minutos_teoricos.
    """
    if formacion not in FORMACIONES:
        raise ValueError(
            f"Formación {formacion} no soportada. Opciones: {list(FORMACIONES.keys())}"
        )

    config = FORMACIONES[formacion]

    # Agrupar por posición (filtrando convocadas si corresponde)
    grupos: Dict[Posicion, list] = {pos: [] for pos in Posicion}
    for p in players:
        if not incluir_no_convocadas and p.estado.value == "no_convocada":
            p.minutos_teoricos = 0.0
            continue
        grupos[p.posicion].append(p)

    # Para cada posición, repartir minutos proporcional a P (con tope)
    for posicion, jugadoras_grupo in grupos.items():
        n_en_cancha = config.get(posicion, 0)
        minutos_disponibles = n_en_cancha * duracion

        if not jugadoras_grupo or minutos_disponibles == 0:
            for p in jugadoras_grupo:
                p.minutos_teoricos = 0.0
            continue

        _repartir_con_tope(jugadoras_grupo, minutos_disponibles, tope_individual=duracion)

        # Ordenar dentro del grupo por prioridad desc
        jugadoras_grupo.sort(key=lambda x: x.prioridad, reverse=True)

    return grupos


def _repartir_con_tope(jugadoras: list, minutos_a_repartir: float, tope_individual: float):
    """
    Reparte `minutos_a_repartir` entre `jugadoras` proporcional a su .prioridad,
    pero ninguna recibe más de `tope_individual`.

    Algoritmo iterativo:
    1. Reparto proporcional según P.
    2. Las que pasan el tope se les fija el tope, y "salen" del reparto.
    3. Los minutos sobrantes se redistribuyen entre las que NO llegaron al tope.
    4. Repetir hasta que nadie pase del tope o ya no haya capacidad libre.
    """
    if not jugadoras:
        return

    # Inicializar todas en 0
    for p in jugadoras:
        p.minutos_teoricos = 0.0

    # Lista de jugadoras "en juego" para el reparto (las que aún pueden recibir más min)
    en_juego = list(jugadoras)
    minutos_pendientes = minutos_a_repartir

    # Iterar hasta convergencia (máximo N+1 iteraciones, donde N=cantidad jugadoras)
    max_iter = len(jugadoras) + 2
    for _ in range(max_iter):
        if not en_juego or minutos_pendientes <= 0.001:
            break

        suma_p = sum(p.prioridad for p in en_juego)

        if suma_p == 0:
            # Edge case: todas con prioridad 0 → reparto equitativo
            por_jugadora = minutos_pendientes / len(en_juego)
            tope_alcanzadas = []
            for p in en_juego:
                disponible = tope_individual - p.minutos_teoricos
                asignar = min(por_jugadora, disponible)
                p.minutos_teoricos += asignar
                if abs(p.minutos_teoricos - tope_individual) < 0.001:
                    tope_alcanzadas.append(p)
            for p in tope_alcanzadas:
                en_juego.remove(p)
            # Recalcular pendientes (es lo que no se pudo asignar)
            minutos_pendientes = minutos_a_repartir - sum(p.minutos_teoricos for p in jugadoras)
            if abs(minutos_pendientes) < 0.001:
                break
            continue

        # Reparto proporcional
        nuevas_topadas = []
        excedente = 0.0
        for p in en_juego:
            asignacion_proporcional = (p.prioridad / suma_p) * minutos_pendientes
            disponible = tope_individual - p.minutos_teoricos
            if asignacion_proporcional >= disponible:
                # Llega al tope
                excedente += (asignacion_proporcional - disponible)
                p.minutos_teoricos = tope_individual
                nuevas_topadas.append(p)
            else:
                p.minutos_teoricos += asignacion_proporcional

        # Sacar las topadas del reparto
        for p in nuevas_topadas:
            en_juego.remove(p)

        # Lo que queda para repartir es el excedente acumulado
        minutos_pendientes = excedente

    # Si todavía sobran minutos pero todas están topadas, los minutos "se pierden"
    # (es físicamente imposible que jueguen más). Esto pasa cuando hay menos
    # jugadoras que las necesarias para cubrir todas las posiciones.


def calcular_y_repartir(
    players: Iterable[Player],
    K: float = 0.7,
    formacion: str = "4-3-3",
    incluir_no_convocadas: bool = False,
) -> Dict[Posicion, list]:
    """
    Atajo que hace todo: calcula prioridad y reparte minutos.
    Es el punto de entrada normal antes de empezar un partido.
    """
    asignar_prioridades(players, K)
    return repartir_minutos_por_posicion(
        players, formacion, incluir_no_convocadas=incluir_no_convocadas
    )
