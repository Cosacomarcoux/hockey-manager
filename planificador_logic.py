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


def generar_titulares_y_cascada(
    players: list,
    duracion_turno: float,
    formacion: str,
    anclas_ids: set,
) -> dict:
    """
    Genera el T1 con los 11 titulares según prioridad y replica idéntico
    en todos los turnos siguientes (cascada). El usuario después hace los
    cambios manuales que considere y la cascada se va aplicando turno a turno.

    Devuelve: {turno_numero: [(jugadora_id, slot_indice), ...], ...}
    """
    cantidad_turnos = int(round(60 / duracion_turno))
    if cantidad_turnos <= 0:
        return {}

    config_formacion = dict(FORMACIONES[formacion])
    convocadas = [p for p in players if p.estado != Estado.NO_CONVOCADA]

    # Redistribuir slots si faltan jugadoras (igual que en generación automática)
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

    # Asignar titulares para T1 (mejores N por posición según prioridad)
    slot_bases = {
        Posicion.ARQUERA: SLOT_ARQUERA,
        Posicion.DEFENSORA: SLOT_DEFENSORA_BASE,
        Posicion.VOLANTE: SLOT_VOLANTE_BASE,
        Posicion.DELANTERA: SLOT_DELANTERA_BASE,
    }

    titulares_t1 = []  # [(jid, slot), ...]
    for pos in posiciones_orden:
        n_cancha = config_formacion.get(pos, 0)
        if n_cancha == 0:
            continue
        candidatas = [p for p in convocadas if p.posicion == pos]
        # Las anclas primero, después por prioridad
        candidatas.sort(key=lambda p: (1 if p.id in anclas_ids else 0, p.prioridad), reverse=True)
        seleccionadas = candidatas[:n_cancha]
        base = slot_bases[pos]
        for i, sel in enumerate(seleccionadas):
            titulares_t1.append((sel.id, base + i))

    # Replicar T1 idéntico en todos los turnos (cascada)
    plan = {}
    for turno_n in range(1, cantidad_turnos + 1):
        plan[turno_n] = list(titulares_t1)  # copia

    return plan


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

    # Calcular el promedio teórico de capacidad si pudiéramos siempre
    # tener en cancha a las 11 mejores. Lo usamos como referencia para no bajar
    # mucho el promedio cuando hacemos cambios.
    convocadas_sorted = sorted(convocadas, key=lambda p: p.capacidad, reverse=True)
    top_11_caps = [p.capacidad for p in convocadas_sorted[:11]]
    promedio_objetivo = sum(top_11_caps) / 11 if top_11_caps else 3.0

    for turno_n in range(1, cantidad_turnos + 1):
        plan[turno_n] = []
        ya_en_turno = set()

        # Tracker del promedio actual del turno (para decidir balanceo)
        caps_en_turno = []  # capacidades de las jugadoras ya asignadas a este turno

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
            ids_seleccionadas_pos = set()  # IDs ya elegidos para esta posición en este turno

            # Iteramos sobre las candidatas en orden de prioridad
            i_cand = 0
            while len(seleccionadas) < n_cancha and i_cand < len(candidatas):
                cand = candidatas[i_cand]
                i_cand += 1

                if cand.id in ids_seleccionadas_pos:
                    continue

                pendiente = turnos_objetivo[cand.id] - turnos_asignados[cand.id]
                if pendiente <= 0:
                    continue

                # Promedio si elegimos a esta candidata
                cap_actual_total = sum(caps_en_turno) + sum(s.capacidad for s in seleccionadas)
                n_actual = len(caps_en_turno) + len(seleccionadas)
                nueva_cap_total = cap_actual_total + cand.capacidad
                nuevo_promedio = nueva_cap_total / (n_actual + 1) if (n_actual + 1) > 0 else 0

                # Buscar alternativa si la candidata baja mucho el promedio
                mejor_alt = None
                for alt in candidatas:
                    if alt.id == cand.id:
                        continue
                    if alt.id in ids_seleccionadas_pos:
                        continue
                    if alt.id in ya_en_turno:
                        continue
                    alt_pend = turnos_objetivo[alt.id] - turnos_asignados[alt.id]
                    if alt_pend <= 0:
                        continue
                    if abs(alt.prioridad - cand.prioridad) > 0.5:
                        continue
                    cand_pend = pendiente
                    if alt_pend < max(1, cand_pend - 1):
                        continue
                    if alt.capacidad > cand.capacidad:
                        if mejor_alt is None or alt.capacidad > mejor_alt.capacidad:
                            mejor_alt = alt

                diferencia_promedio = promedio_objetivo - nuevo_promedio
                if mejor_alt is not None and diferencia_promedio > 0.3:
                    seleccionadas.append(mejor_alt)
                    ids_seleccionadas_pos.add(mejor_alt.id)
                else:
                    seleccionadas.append(cand)
                    ids_seleccionadas_pos.add(cand.id)

            # Si quedaron slots libres, llenar con cualquiera (sin importar pendiente)
            if len(seleccionadas) < n_cancha:
                for cand in candidatas:
                    if cand.id in ids_seleccionadas_pos:
                        continue
                    if cand.id in ya_en_turno:
                        continue
                    if len(seleccionadas) >= n_cancha:
                        break
                    seleccionadas.append(cand)
                    ids_seleccionadas_pos.add(cand.id)

            base = slot_bases[pos]
            for i, sel in enumerate(seleccionadas):
                slot = base + i
                plan[turno_n].append((sel.id, slot))
                ya_en_turno.add(sel.id)
                turnos_asignados[sel.id] += 1
                caps_en_turno.append(sel.capacidad)

    return plan
