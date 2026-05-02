"""
Módulo de Rotación Semiautomática para Hockey.

Lógica pura sin GUI ni base de datos. Pensado para integrarse con
una capa de adaptación (ej. tu app Flask) que sincronice los datos.

Uso típico:

    from rotacion_module import (
        Player, Posicion, Estado,
        ConfiguracionRotacion, ModoRotacion, Celula, Bloque,
        MatchController,
    )

    # 1. Armar el plantel
    players = [
        Player(id=1, nombre="Sofia", apellido="Garcia", capacidad=5, asistencia=95, posicion=Posicion.DELANTERA),
        # ... más jugadoras
    ]

    # 2. Configurar el partido
    config = ConfiguracionRotacion(
        modo=ModoRotacion.LIBRE,
        umbral_cambio_minutos=5.0,
        anclas_ids={1},  # Sofia es ancla, no se sugiere su cambio
    )

    # 3. Crear el controller
    mc = MatchController(players, config, K=0.7, formacion="4-3-3")
    mc.asignar_titulares_automaticos()

    # 4. Loop del partido
    mc.tick(0.5)  # avanza 30 segundos
    sugerencias = mc.obtener_sugerencias()
    if sugerencias:
        for s in sugerencias:
            print(s)
            # Si el entrenador acepta:
            # mc.confirmar_cambio(s.sale.id, s.entra.id)
"""
from .player import Player, Posicion, Estado, Alerta
from .priority import (
    calcular_prioridad,
    asignar_prioridades,
    repartir_minutos_por_posicion,
    calcular_y_repartir,
    FORMACIONES,
    DURACION_PARTIDO,
)
from .rotation_systems import (
    ConfiguracionRotacion,
    ModoRotacion,
    Celula,
    Bloque,
)
from .match_controller import MatchController, SugerenciaCambio

__all__ = [
    # Modelo
    "Player", "Posicion", "Estado", "Alerta",
    # Algoritmo
    "calcular_prioridad", "asignar_prioridades",
    "repartir_minutos_por_posicion", "calcular_y_repartir",
    "FORMACIONES", "DURACION_PARTIDO",
    # Sistemas
    "ConfiguracionRotacion", "ModoRotacion", "Celula", "Bloque",
    # Controller
    "MatchController", "SugerenciaCambio",
]
