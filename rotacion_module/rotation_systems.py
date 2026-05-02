"""
rotation_systems.py — Tres sistemas de cambio para gestionar rotaciones.

- ModoCelulas: rotaciones de parejas/tríos predefinidos.
- ModoBloques: cambios de líneas completas cada X minutos.
- ModoAnclas: marca jugadoras "intocables" que el sistema nunca sugiere para cambio.

Los tres modos son COMPATIBLES entre sí. Se pueden combinar:
ej. usar ModoBloques con algunas jugadoras marcadas como ancla.
"""
from dataclasses import dataclass, field
from typing import List, Set, Optional, Dict
from enum import Enum
from .player import Player


class ModoRotacion(str, Enum):
    CELULAS = "celulas"
    BLOQUES = "bloques"
    LIBRE = "libre"   # ni células ni bloques: solo prioridad pura


# ============================================================
# CÉLULA: grupo predefinido de jugadoras que rotan juntas
# ============================================================
@dataclass
class Celula:
    """
    Una célula es un grupo de 2-3 jugadoras que entran/salen juntas.
    Útil para parejas que se entienden bien y para no romper sociedades tácticas.
    """
    nombre: str                          # ej. "Defensa derecha"
    jugadoras_ids: List[int]             # IDs de las jugadoras que la componen

    def __post_init__(self):
        if not (2 <= len(self.jugadoras_ids) <= 4):
            raise ValueError(
                f"Una célula debe tener entre 2 y 4 jugadoras, llegó {len(self.jugadoras_ids)}"
            )


# ============================================================
# BLOQUE: línea completa que cambia junta cada X min
# ============================================================
@dataclass
class Bloque:
    """
    Un bloque es una posición completa (ej. "todas las delanteras").
    Cuando se cumple el intervalo, se cambia el bloque entero.
    """
    nombre: str                              # ej. "Línea de delanteras"
    posicion: str                            # "Defensora", "Volante", "Delantera"
    intervalo_minutos: float = 5.0           # cambia cada X min
    ultimo_cambio_minuto: float = 0.0        # cuándo fue el último cambio


# ============================================================
# CONFIGURACIÓN GENERAL
# ============================================================
@dataclass
class ConfiguracionRotacion:
    """
    Empaqueta los 3 sistemas de cambio para un partido específico.
    El MatchController lee esta config y aplica las reglas correspondientes.
    """
    modo: ModoRotacion = ModoRotacion.LIBRE
    umbral_cambio_minutos: float = 5.0      # cuánto tiempo es "mucho" sin rotar
    tiempo_pre_alerta_minutos: float = 1.0  # T-1: pre-alerta para entrar en calor

    # Para Modo Células:
    celulas: List[Celula] = field(default_factory=list)

    # Para Modo Bloques:
    bloques: List[Bloque] = field(default_factory=list)

    # Anclas: IDs de jugadoras que NO se sugieren para cambio (compatible con todos los modos)
    anclas_ids: Set[int] = field(default_factory=set)


# ============================================================
# HELPERS PARA SABER QUIÉN ESTÁ "ANCLADA"
# ============================================================
def es_ancla(player: Player, config: ConfiguracionRotacion) -> bool:
    """Devuelve True si la jugadora no debe ser sugerida para cambio."""
    return player.id in config.anclas_ids or player.es_ancla


def aplicar_anclas(players: List[Player], config: ConfiguracionRotacion) -> None:
    """Sincroniza el flag .es_ancla de cada player con la configuración."""
    for p in players:
        p.es_ancla = (p.id in config.anclas_ids)


# ============================================================
# HELPERS PARA CÉLULAS
# ============================================================
def encontrar_celula_de(player_id: int, config: ConfiguracionRotacion) -> Optional[Celula]:
    """Devuelve la célula a la que pertenece una jugadora, o None."""
    for celula in config.celulas:
        if player_id in celula.jugadoras_ids:
            return celula
    return None


def jugadoras_de_celula(celula: Celula, players: List[Player]) -> List[Player]:
    """Devuelve los Player objects de una célula."""
    return [p for p in players if p.id in celula.jugadoras_ids]


# ============================================================
# HELPERS PARA BLOQUES
# ============================================================
def bloque_para_posicion(posicion: str, config: ConfiguracionRotacion) -> Optional[Bloque]:
    """Devuelve el Bloque definido para una posición (si existe)."""
    for bloque in config.bloques:
        if bloque.posicion == posicion:
            return bloque
    return None


def tiempo_desde_ultimo_cambio_bloque(bloque: Bloque, minuto_actual: float) -> float:
    """Cuántos minutos pasaron desde el último cambio de este bloque."""
    return max(0.0, minuto_actual - bloque.ultimo_cambio_minuto)


def bloque_listo_para_cambio(bloque: Bloque, minuto_actual: float) -> bool:
    """¿Llegó el momento de cambiar el bloque?"""
    return tiempo_desde_ultimo_cambio_bloque(bloque, minuto_actual) >= bloque.intervalo_minutos
