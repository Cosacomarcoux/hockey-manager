"""
match_controller.py — El controlador de partido en runtime.

Esta es la pieza central. Su trabajo:
1. Llevar el reloj del partido (avanzar minutos).
2. Acumular tiempo en cancha de cada jugadora.
3. Comparar bloque_actual vs umbral → generar pre-alertas y alertas de cambio.
4. Producir sugerencias concretas: "Sale X, entra Y".
5. Recibir confirmaciones del usuario y aplicar el cambio.
6. Recalcular todo si hay una lesión (failsafe).

NO toca base de datos. NO toca Flask. Solo manipula objetos Player en memoria.
La integración a la app real va a ser una capa de adaptación que sincronice
este controller con la base de datos en cada tick.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from .player import Player, Posicion, Estado, Alerta
from .rotation_systems import (
    ConfiguracionRotacion, ModoRotacion, Celula, Bloque,
    es_ancla, encontrar_celula_de, jugadoras_de_celula,
    bloque_para_posicion, bloque_listo_para_cambio,
    aplicar_anclas,
)
from . import priority


# ============================================================
# SUGERENCIA DE CAMBIO
# ============================================================
@dataclass
class SugerenciaCambio:
    """
    Una sugerencia concreta: tal jugadora sale, tal otra entra.
    El usuario decide si la confirma o no.
    """
    sale: Player
    entra: Player
    motivo: str                          # texto humano: "bloque cumplido", "déficit alto"
    urgencia: Alerta = Alerta.CAMBIO     # CAMBIO o LESIONADA

    # Para sugerencias de células/bloques que mueven varias a la vez:
    grupo_sale: List[Player] = field(default_factory=list)
    grupo_entra: List[Player] = field(default_factory=list)

    @property
    def es_grupal(self) -> bool:
        """True si la sugerencia involucra un grupo (células o bloques), aunque sea de tamaño 1."""
        return len(self.grupo_sale) >= 1 and len(self.grupo_entra) >= 1

    def __repr__(self):
        if self.es_grupal:
            sale_str = ", ".join(p.nombre_completo for p in self.grupo_sale)
            entra_str = ", ".join(p.nombre_completo for p in self.grupo_entra)
            return f"SugerenciaCambio(grupo: salen [{sale_str}], entran [{entra_str}], motivo={self.motivo})"
        return f"SugerenciaCambio({self.sale.nombre_completo} → {self.entra.nombre_completo}, motivo={self.motivo})"


# ============================================================
# MATCH CONTROLLER
# ============================================================
class MatchController:
    """
    Controla un partido en runtime. Se instancia al iniciar el partido,
    se le manda tick(delta_minutos) cada vez que avanza el reloj, y
    consultás .obtener_sugerencias() para saber qué hacer.
    """

    def __init__(
        self,
        players: List[Player],
        config: ConfiguracionRotacion,
        K: float = 0.7,
        formacion: str = "4-3-3",
    ):
        self.players = players
        self.config = config
        self.K = K
        self.formacion = formacion
        self.minuto_actual: float = 0.0
        self.partido_finalizado: bool = False

        # Calcular prioridades y minutos teóricos al arranque
        priority.calcular_y_repartir(
            self.players, K=K, formacion=formacion, incluir_no_convocadas=True
        )
        # Sincronizar flag de anclas
        aplicar_anclas(self.players, self.config)

    # =========================================================
    # AVANCE DEL RELOJ
    # =========================================================
    def tick(self, delta_minutos: float = 0.5) -> None:
        """
        Avanza el reloj del partido. Acumula tiempo en cancha
        de cada jugadora EN_CANCHA y actualiza alertas.

        delta_minutos: cuánto avanzó el reloj desde el último tick.
        Por defecto 0.5 min = 30 seg, una resolución razonable.
        """
        if self.partido_finalizado:
            return

        self.minuto_actual += delta_minutos

        # Acumular tiempo de las que están en cancha
        for p in self.players:
            if p.estado == Estado.EN_CANCHA:
                p.minutos_totales_jugados += delta_minutos
                p.bloque_actual += delta_minutos

        # Recalcular alertas
        self._actualizar_alertas()

    # =========================================================
    # SUGERENCIAS
    # =========================================================
    def obtener_sugerencias(self) -> List[SugerenciaCambio]:
        """
        Devuelve la lista de sugerencias activas según el modo configurado.
        El usuario decide cuál confirmar.
        """
        if self.partido_finalizado:
            return []

        # Si hay lesionadas, prioridad MÁXIMA: cambio de emergencia
        emergencias = self._sugerencias_por_lesion()
        if emergencias:
            return emergencias

        # Si no, según el modo elegido
        if self.config.modo == ModoRotacion.CELULAS:
            return self._sugerencias_por_celulas()
        elif self.config.modo == ModoRotacion.BLOQUES:
            return self._sugerencias_por_bloques()
        else:
            return self._sugerencias_libres()

    # =========================================================
    # CONFIRMAR UN CAMBIO (UI llama acá cuando el usuario aprueba)
    # =========================================================
    def confirmar_cambio(self, sale_id: int, entra_id: int) -> bool:
        """
        Aplica un cambio: la jugadora `sale_id` va al banco, `entra_id` entra a cancha.
        Resetea el bloque_actual de la que entra. Devuelve True si se aplicó OK.
        """
        sale = self._buscar_player(sale_id)
        entra = self._buscar_player(entra_id)
        if not sale or not entra:
            return False
        if sale.estado != Estado.EN_CANCHA:
            return False
        if entra.estado != Estado.BANCO:
            return False
        if sale.posicion != entra.posicion:
            # Por seguridad: solo permitir cambios en la misma posición
            return False

        sale.estado = Estado.BANCO
        sale.bloque_actual = 0.0
        sale.alerta_actual = Alerta.NINGUNA

        entra.estado = Estado.EN_CANCHA
        entra.bloque_actual = 0.0
        entra.alerta_actual = Alerta.NINGUNA

        # Si era un bloque, marcar el momento del cambio
        bloque = bloque_para_posicion(sale.posicion.value, self.config)
        if bloque and self.config.modo == ModoRotacion.BLOQUES:
            bloque.ultimo_cambio_minuto = self.minuto_actual

        return True

    def confirmar_cambio_grupal(self, salen_ids: List[int], entran_ids: List[int]) -> bool:
        """
        Confirma un cambio de varias jugadoras a la vez (células o bloques).
        """
        if len(salen_ids) != len(entran_ids):
            return False
        # Validar que todos los cambios sean válidos antes de aplicar ninguno
        salen = [self._buscar_player(i) for i in salen_ids]
        entran = [self._buscar_player(i) for i in entran_ids]
        if any(p is None for p in salen + entran):
            return False
        if any(p.estado != Estado.EN_CANCHA for p in salen):
            return False
        if any(p.estado != Estado.BANCO for p in entran):
            return False
        # Aplicar
        for sale, entra in zip(salen, entran):
            sale.estado = Estado.BANCO
            sale.bloque_actual = 0.0
            sale.alerta_actual = Alerta.NINGUNA
            entra.estado = Estado.EN_CANCHA
            entra.bloque_actual = 0.0
            entra.alerta_actual = Alerta.NINGUNA
        return True

    # =========================================================
    # PLANTEL INICIAL (titulares al arranque)
    # =========================================================
    def asignar_titulares_automaticos(self) -> Dict[Posicion, List[Player]]:
        """
        Selecciona automáticamente los titulares según prioridad y formación.
        Las primeras N de cada posición (con mayor P) van EN_CANCHA, el resto BANCO.
        Las NO_CONVOCADA quedan como están.
        """
        from .priority import FORMACIONES
        config_formacion = FORMACIONES[self.formacion]
        titulares = {pos: [] for pos in Posicion}

        # Agrupar convocadas por posición
        por_posicion: Dict[Posicion, List[Player]] = {pos: [] for pos in Posicion}
        for p in self.players:
            if p.estado != Estado.NO_CONVOCADA:
                por_posicion[p.posicion].append(p)

        # Seleccionar titulares
        for pos, lista in por_posicion.items():
            n_titulares = config_formacion.get(pos, 0)
            # Ordenar por prioridad desc
            lista.sort(key=lambda x: x.prioridad, reverse=True)
            for i, p in enumerate(lista):
                if i < n_titulares:
                    p.estado = Estado.EN_CANCHA
                    titulares[pos].append(p)
                else:
                    p.estado = Estado.BANCO
        return titulares

    # =========================================================
    # FAILSAFE: lesión / tarjeta roja
    # =========================================================
    def marcar_lesionada(self, player_id: int) -> Optional[SugerenciaCambio]:
        """
        Marca una jugadora como lesionada y genera una sugerencia urgente
        para reemplazarla. NO aplica el cambio automáticamente — el usuario
        debe confirmar el reemplazo (que también se le sugiere).
        """
        p = self._buscar_player(player_id)
        if not p or p.estado != Estado.EN_CANCHA:
            return None

        p.lesionada = True
        p.alerta_actual = Alerta.LESIONADA

        # Buscar el mejor reemplazo
        candidata = self._mejor_candidata_para_entrar(p.posicion, excluir_lesionadas=True)
        if not candidata:
            # Sin candidatas → sigue marcada como lesionada pero sin sugerencia
            return None

        return SugerenciaCambio(
            sale=p, entra=candidata,
            motivo=f"⚠️ Lesión / tarjeta — reemplazo urgente de {p.nombre_completo}",
            urgencia=Alerta.LESIONADA,
        )

    def recalcular_minutos_post_lesion(self) -> None:
        """
        Cuando alguien queda lesionada y no puede jugar más, redistribuir
        sus minutos teóricos restantes entre las demás de su posición.
        """
        for lesionada in [p for p in self.players if p.lesionada]:
            # Minutos que la lesionada NO va a jugar (de los que tenía teóricos)
            min_perdidos = max(0, lesionada.minutos_teoricos - lesionada.minutos_totales_jugados)
            if min_perdidos == 0:
                continue
            # Repartir entre las demás de su misma posición que NO estén lesionadas
            companieras = [
                p for p in self.players
                if p.posicion == lesionada.posicion
                and p.id != lesionada.id
                and not p.lesionada
                and p.estado != Estado.NO_CONVOCADA
            ]
            if not companieras:
                continue
            suma_p = sum(p.prioridad for p in companieras)
            if suma_p == 0:
                # reparto equitativo
                extra = min_perdidos / len(companieras)
                for p in companieras:
                    p.minutos_teoricos += extra
            else:
                for p in companieras:
                    p.minutos_teoricos += (p.prioridad / suma_p) * min_perdidos
            # Borrar los minutos teóricos de la lesionada (no los va a jugar)
            lesionada.minutos_teoricos = lesionada.minutos_totales_jugados

    # =========================================================
    # FINALIZAR
    # =========================================================
    def finalizar_partido(self) -> None:
        """Cierra el partido. Las que estaban en cancha pasan al banco."""
        self.partido_finalizado = True
        for p in self.players:
            if p.estado == Estado.EN_CANCHA:
                p.estado = Estado.BANCO
            p.alerta_actual = Alerta.NINGUNA

    # =========================================================
    # MÉTODOS INTERNOS
    # =========================================================
    def _buscar_player(self, player_id: int) -> Optional[Player]:
        return next((p for p in self.players if p.id == player_id), None)

    def _actualizar_alertas(self) -> None:
        """
        Recalcula la .alerta_actual de cada jugadora EN_CANCHA según:
        - Si está cerca del umbral → PRE_ALERTA
        - Si pasó el umbral → CAMBIO
        - Si es ancla → no se le pone alerta de cambio (excepto si está lesionada)
        """
        umbral = self.config.umbral_cambio_minutos
        pre_aviso = umbral - self.config.tiempo_pre_alerta_minutos

        for p in self.players:
            if p.lesionada:
                p.alerta_actual = Alerta.LESIONADA
                continue
            if p.estado != Estado.EN_CANCHA:
                p.alerta_actual = Alerta.NINGUNA
                continue
            if es_ancla(p, self.config):
                p.alerta_actual = Alerta.NINGUNA
                continue

            if p.bloque_actual >= umbral:
                p.alerta_actual = Alerta.CAMBIO
            elif p.bloque_actual >= pre_aviso:
                p.alerta_actual = Alerta.PRE_ALERTA
            else:
                p.alerta_actual = Alerta.NINGUNA

    def _sugerencias_por_lesion(self) -> List[SugerenciaCambio]:
        """Devuelve sugerencias urgentes para todas las lesionadas que aún están EN_CANCHA."""
        sugerencias = []
        for p in self.players:
            if p.lesionada and p.estado == Estado.EN_CANCHA:
                candidata = self._mejor_candidata_para_entrar(p.posicion, excluir_lesionadas=True)
                if candidata:
                    sugerencias.append(SugerenciaCambio(
                        sale=p, entra=candidata,
                        motivo=f"⚠️ Lesión / tarjeta — {p.nombre_completo}",
                        urgencia=Alerta.LESIONADA,
                    ))
        return sugerencias

    def _sugerencias_libres(self) -> List[SugerenciaCambio]:
        """
        Modo libre: sugerir cambios para las jugadoras con alerta CAMBIO
        que no son anclas. Reemplazo: la del banco con mayor déficit en su posición.
        """
        sugerencias = []
        for p in self.players:
            if p.alerta_actual != Alerta.CAMBIO:
                continue
            candidata = self._mejor_candidata_para_entrar(p.posicion)
            if candidata:
                sugerencias.append(SugerenciaCambio(
                    sale=p, entra=candidata,
                    motivo=f"⏱ {p.nombre_completo} llegó al umbral de cambio ({p.bloque_actual:.1f} min)",
                ))
        return sugerencias

    def _sugerencias_por_celulas(self) -> List[SugerenciaCambio]:
        """
        Modo células: cuando AL MENOS UNA jugadora de una célula activa el umbral,
        sugerir cambiar la célula entera por la "célula compañera" de banco.
        """
        sugerencias = []
        for celula in self.config.celulas:
            jugs = jugadoras_de_celula(celula, self.players)
            jugs_en_cancha = [p for p in jugs if p.estado == Estado.EN_CANCHA]
            if not jugs_en_cancha:
                continue
            # ¿Alguna llegó al umbral?
            necesita_cambio = any(
                p.alerta_actual == Alerta.CAMBIO and not es_ancla(p, self.config)
                for p in jugs_en_cancha
            )
            if not necesita_cambio:
                continue
            # Buscar reemplazos para la célula (mismas posiciones)
            reemplazos = []
            usadas = set()
            for p in jugs_en_cancha:
                cand = self._mejor_candidata_para_entrar(p.posicion, excluir_ids=usadas)
                if cand:
                    reemplazos.append(cand)
                    usadas.add(cand.id)
            if len(reemplazos) == len(jugs_en_cancha):
                sugerencias.append(SugerenciaCambio(
                    sale=jugs_en_cancha[0], entra=reemplazos[0],
                    motivo=f"🔄 Cambio de célula '{celula.nombre}'",
                    grupo_sale=jugs_en_cancha,
                    grupo_entra=reemplazos,
                ))
        return sugerencias

    def _sugerencias_por_bloques(self) -> List[SugerenciaCambio]:
        """
        Modo bloques: cuando llega el momento de cambiar un bloque,
        sugerir cambiar TODAS las jugadoras de esa posición (excepto anclas).
        """
        sugerencias = []
        for bloque in self.config.bloques:
            if not bloque_listo_para_cambio(bloque, self.minuto_actual):
                continue
            # Jugadoras de esa posición, en cancha, que NO sean anclas
            posicion_enum = Posicion(bloque.posicion)
            en_cancha = [
                p for p in self.players
                if p.posicion == posicion_enum
                and p.estado == Estado.EN_CANCHA
                and not es_ancla(p, self.config)
            ]
            if not en_cancha:
                continue
            # Buscar reemplazos (banco, misma posición)
            banco = [
                p for p in self.players
                if p.posicion == posicion_enum
                and p.estado == Estado.BANCO
            ]
            # Ordenar banco por déficit (más necesitadas primero)
            banco.sort(key=lambda x: x.deficit_minutos, reverse=True)
            n_cambios = min(len(en_cancha), len(banco))
            if n_cambios > 0:
                salen = en_cancha[:n_cambios]
                entran = banco[:n_cambios]
                sugerencias.append(SugerenciaCambio(
                    sale=salen[0], entra=entran[0],
                    motivo=f"⏱ Cambio de bloque '{bloque.nombre}' ({bloque.intervalo_minutos} min cumplidos)",
                    grupo_sale=salen,
                    grupo_entra=entran,
                ))
        return sugerencias

    def _mejor_candidata_para_entrar(
        self,
        posicion: Posicion,
        excluir_lesionadas: bool = True,
        excluir_ids: Optional[set] = None,
    ) -> Optional[Player]:
        """
        Devuelve la jugadora del banco que mejor entra:
        - misma posición
        - estado BANCO
        - no lesionada
        - mayor déficit de minutos (que más le falta jugar)
        En empate, gana mayor prioridad.
        """
        excluir_ids = excluir_ids or set()
        candidatas = [
            p for p in self.players
            if p.posicion == posicion
            and p.estado == Estado.BANCO
            and (not excluir_lesionadas or not p.lesionada)
            and p.id not in excluir_ids
        ]
        if not candidatas:
            return None
        candidatas.sort(key=lambda x: (x.deficit_minutos, x.prioridad), reverse=True)
        return candidatas[0]

    # =========================================================
    # REPORTING / DEBUG
    # =========================================================
    def estado_actual(self) -> dict:
        """Snapshot del estado del partido para inspeccionar/debugear."""
        return {
            "minuto_actual": round(self.minuto_actual, 2),
            "modo": self.config.modo.value,
            "K": self.K,
            "formacion": self.formacion,
            "en_cancha": [
                {
                    "id": p.id,
                    "nombre": p.nombre_completo,
                    "posicion": p.posicion.value,
                    "min_jugados": round(p.minutos_totales_jugados, 1),
                    "min_teoricos": round(p.minutos_teoricos, 1),
                    "deficit": round(p.deficit_minutos, 1),
                    "bloque_actual": round(p.bloque_actual, 1),
                    "alerta": p.alerta_actual.value,
                    "ancla": p.es_ancla,
                }
                for p in self.players if p.estado == Estado.EN_CANCHA
            ],
            "banco": [
                {
                    "id": p.id,
                    "nombre": p.nombre_completo,
                    "posicion": p.posicion.value,
                    "min_jugados": round(p.minutos_totales_jugados, 1),
                    "min_teoricos": round(p.minutos_teoricos, 1),
                    "deficit": round(p.deficit_minutos, 1),
                }
                for p in self.players if p.estado == Estado.BANCO
            ],
        }
