"""
planificador_logic.py — Lógica para generar planes de turnos automáticamente.

Funciones puras (sin DB ni Flask). Reciben datos, devuelven datos.

Convención de slots:
    Arquera:   slot 0
    Defensora: slots 100, 101, 102, 103, 104 (hasta 5)
    Volante:   slots 200, 201, 202, 203, 204 (hasta 5)
    Delantera: slots 300, 301, 302, 303, 304 (hasta 5)
"""
from rotacion_module import Player, Posicion, Estado
from rotacion_module import FORMACIONES


# Slots base por posición
SLOT_ARQUERA = 0
SLOT_DEFENSORA_BASE = 100
SLOT_VOLANTE_BASE = 200
SLOT_DELANTERA_BASE = 300


def slot_base_de_posicion(posicion: str) -> int:
    """Devuelve el slot base según la posición."""
    if posicion == 'Arquera':
        return SLOT_ARQUERA
    elif posicion == 'Defensora':
        return SLOT_DEFENSORA_BASE
    elif posicion == 'Volante':
        return SLOT_VOLANTE_BASE
    elif posicion == 'Delantera':
        return SLOT_DELANTERA_BASE
    return SLOT_VOLANTE_BASE


def calcular_turnos_por_jugadora(player: Player, duracion_turno: float) -> int:
    """Cuántos turnos le tocan a una jugadora según sus minutos teóricos."""
    if duracion_turno <= 0:
        return 0
    if player.minutos_teoricos <= 0:
        return 0
    return max(1, round(player.minutos_teoricos / duracion_turno))


def generar_plan_automatico(
    players: list,
    duracion_turno: float,
    formacion: str,
    anclas_ids: set,
) -> dict:
    """
    Genera un plan automático: para cada turno, qué jugadoras juegan y en qué slot.

    Devuelve: {turno_numero: [(jugadora_id, slot_indice), ...], ...}

    Si una posición no tiene suficientes jugadoras, redistribuye los slots a las
    posiciones con sobrante para mantener siempre 11 jugadoras en cancha.
    """
    cantidad_turnos = int(round(60 / duracion_turno))
    if cantidad_turnos <= 0:
        return {}

    config_formacion = dict(FORMACIONES[formacion])

    convocadas = [p for p in players if p.estado != Estado.NO_CONVOCADA]

    # Redistribuir slots no cubiertos
    posiciones_orden = [Posicion.ARQUERA, Posicion.DEFENSORA, Posicion.VOLANTE, Posicion.DELANTERA]
    disponibles = {pos: 0 for pos in posiciones_orden}
    for p in convocadas:
        if p.posicion in disponibles:
            disponibles[p.posicion] += 1

    faltantes_total = 0
    for pos in posiciones_orden:
        slots_pedidos = config_formacion.get(pos, 0)
        if disponibles[pos] < slots_pedidos:
            faltante = slots_pedidos - disponibles[pos]
            faltantes_total += faltante
            config_formacion[pos] = disponibles[pos]

    slots_a_redistribuir = faltantes_total
    posiciones_destino = [Posicion.DEFENSORA, Posicion.VOLANTE, Posicion.DELANTERA]
    while slots_a_redistribuir > 0:
        progreso = False
        for pos in posiciones_destino:
            if slots_a_redistribuir == 0:
                break
            slots_actuales = config_formacion.get(pos, 0)
            sobrante = disponibles[pos] - slots_actuales
            if sobrante > 0:
                config_formacion[pos] = slots_actuales + 1
                slots_a_redistribuir -= 1
                progreso = True
        if not progreso:
            break

    turnos_objetivo = {}
    for p in convocadas:
        if p.id in anclas_ids:
            turnos_objetivo[p.id] = cantidad_turnos
        else:
            turnos_objetivo[p.id] = calcular_turnos_por_jugadora(p, duracion_turno)

    turnos_asignados = {p.id: 0 for p in convocadas}

    plan = {}

    slot_bases = {
        Posicion.ARQUERA: SLOT_ARQUERA,
        Posicion.DEFENSORA: SLOT_DEFENSORA_BASE,
        Posicion.VOLANTE: SLOT_VOLANTE_BASE,
        Posicion.DELANTERA: SLOT_DELANTERA_BASE,
    }

    for turno_n in range(1, cantidad_turnos + 1):
        plan[turno_n] = []
        ya_en_turno = set()

        for pos in posiciones_orden:
            n_cancha = config_formacion.get(pos, 0)
            if n_cancha == 0:
                continue

            candidatas = [
                p for p in convocadas
                if p.posicion == pos and p.id not in ya_en_turno
            ]

            def prioridad_seleccion(p):
                turnos_pendientes = turnos_objetivo[p.id] - turnos_asignados[p.id]
                es_ancla = 1 if p.id in anclas_ids else 0
                return (es_ancla, turnos_pendientes, p.prioridad)

            candidatas.sort(key=prioridad_seleccion, reverse=True)

            seleccionadas = []
            for cand in candidatas:
                if len(seleccionadas) >= n_cancha:
                    break
                pendiente = turnos_objetivo[cand.id] - turnos_asignados[cand.id]
                if pendiente > 0:
                    seleccionadas.append(cand)

            if len(seleccionadas) < n_cancha:
                for cand in candidatas:
                    if cand in seleccionadas:
                        continue
                    if len(seleccionadas) >= n_cancha:
                        break
                    seleccionadas.append(cand)

            base = slot_bases[pos]
            for i, sel in enumerate(seleccionadas):
                slot = base + i
                plan[turno_n].append((sel.id, slot))
                ya_en_turno.add(sel.id)
                turnos_asignados[sel.id] += 1

    return plan
