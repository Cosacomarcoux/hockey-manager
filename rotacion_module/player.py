"""
Player: representa una jugadora en el módulo de rotación.

Esta clase es PURA — no toca la base de datos, no sabe de Flask.
Es solo el modelo de datos en memoria que el MatchController manipula
durante un partido.

La integración con tu app (Jugadora del modelo Flask) se hace en
una capa de adaptación que crea Player a partir de Jugadora.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Posicion(str, Enum):
    ARQUERA = "Arquera"
    DEFENSORA = "Defensora"
    VOLANTE = "Volante"
    DELANTERA = "Delantera"


class Estado(str, Enum):
    EN_CANCHA = "en_cancha"
    BANCO = "banco"
    NO_CONVOCADA = "no_convocada"


class Alerta(str, Enum):
    NINGUNA = "ninguna"
    PRE_ALERTA = "pre_alerta"   # T-1 min: que vaya entrando en calor
    CAMBIO = "cambio"           # T: pedir el cambio ahora
    LESIONADA = "lesionada"     # Failsafe: cambio inmediato


@dataclass
class Player:
    # === Identidad ===
    id: int
    nombre: str
    apellido: str

    # === Atributos del modelo de datos pedido ===
    capacidad: int                  # 1 a 5
    asistencia: float               # 0 a 100 (porcentaje)
    posicion: Posicion
    estado: Estado = Estado.NO_CONVOCADA

    # === Acumuladores en tiempo real ===
    minutos_totales_jugados: float = 0.0   # acumulado del partido
    bloque_actual: float = 0.0             # min desde el último ingreso

    # === Atributos calculados por el algoritmo ===
    prioridad: float = 0.0                  # P del algoritmo (0 a 1)
    minutos_teoricos: float = 0.0           # cuánto debería jugar
    es_ancla: bool = False                  # no se sugiere su cambio
    alerta_actual: Alerta = Alerta.NINGUNA
    lesionada: bool = False                 # failsafe

    # === Validación ===
    def __post_init__(self):
        if not (1 <= self.capacidad <= 5):
            raise ValueError(f"capacidad debe estar entre 1 y 5, llegó {self.capacidad}")
        if not (0 <= self.asistencia <= 100):
            raise ValueError(f"asistencia debe estar entre 0 y 100, llegó {self.asistencia}")
        if not isinstance(self.posicion, Posicion):
            self.posicion = Posicion(self.posicion)
        if not isinstance(self.estado, Estado):
            self.estado = Estado(self.estado)

    # === Helpers ===
    @property
    def nombre_completo(self) -> str:
        return f"{self.nombre} {self.apellido}"

    @property
    def capacidad_normalizada(self) -> float:
        """C = nivel / 5, devuelve un valor entre 0.2 y 1.0"""
        return self.capacidad / 5.0

    @property
    def asistencia_normalizada(self) -> float:
        """A = % / 100, devuelve un valor entre 0.0 y 1.0"""
        return self.asistencia / 100.0

    @property
    def deficit_minutos(self) -> float:
        """
        Cuántos minutos le faltan (o sobran) para alcanzar lo que le toca.
        Positivo: le falta jugar. Negativo: ya jugó de más.
        """
        return self.minutos_teoricos - self.minutos_totales_jugados

    def __repr__(self):
        return (
            f"Player({self.nombre_completo}, {self.posicion.value}, "
            f"cap={self.capacidad}, asist={self.asistencia}%, "
            f"P={self.prioridad:.3f}, min_teor={self.minutos_teoricos:.1f}, "
            f"jugados={self.minutos_totales_jugados:.1f})"
        )
