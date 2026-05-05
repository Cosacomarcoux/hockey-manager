"""
planificador_logic.py — Lógica para generar planes de turnos automáticamente.

Funciones puras (sin DB ni Flask). Reciben datos, devuelven datos.
"""
from rotacion_module import Player, Posicion, Estado
from rotacion_module import FORMACIONES


def calcular_turnos_por_jugadora(player: Player, duracion_turno: float) -> int:
    """
    Cuántos turnos le tocan a una jugadora según sus minutos teóricos.
    Redondea al entero más cercano.
    """
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
    Genera un plan automático: para cada turno, qué jugadoras juegan.

    Estrategia:
    1. Calcular cuántos turnos le tocan a cada jugadora (según minutos teóricos).
    2. Las anclas siempre van en TODOS los turnos.
    3. Las demás se reparten para llenar las posiciones restantes.
    4. Iteramos turno por turno: en cada uno, llenamos cada posición con la
       jugadora que más turnos le quedan por asignar (con mayor prioridad).

    Caso especial: si una posición no tiene suficientes jugadoras convocadas
    para llenar sus slots (ej. no hay arquera, o solo hay 3 volantes para una
    formación que pide 5), los slots faltantes se redistribuyen a otras posiciones
    para que SIEMPRE haya 11 jugadoras en cancha.

    Devuelve: {turno_numero: [jugadora_id, ...], ...}
    """
    cantidad_turnos = int(round(60 / duracion_turno))
    if cantidad_turnos <= 0:
        return {}

    config_formacion = dict(FORMACIONES[formacion])  # copia para poder modificar

    # Solo trabajamos con jugadoras convocadas (no con NO_CONVOCADA)
    convocadas = [p for p in players if p.estado != Estado.NO_CONVOCADA]

    # ============================================================
    # AJUSTE: REDISTRIBUIR SLOTS NO CUBIERTOS
    # Para cada posición, comparar cuántas jugadoras hay vs cuántos slots pide
    # la formación. Si hay menos jugadoras que slots, redistribuir el faltante
    # a las posiciones que tengan jugadoras de sobra.
    # ============================================================
    posiciones_orden = [Posicion.ARQUERA, Posicion.DEFENSORA, Posicion.VOLANTE, Posicion.DELANTERA]

    # Contar disponibles por posición
    disponibles = {pos: 0 for pos in posiciones_orden}
    for p in convocadas:
        if p.posicion in disponibles:
            disponibles[p.posicion] += 1

    # Calcular faltantes y sobrantes
    faltantes_total = 0
    for pos in posiciones_orden:
        slots_pedidos = config_formacion.get(pos, 0)
        if disponibles[pos] < slots_pedidos:
            faltante = slots_pedidos - disponibles[pos]
            faltantes_total += faltante
            # Reducir los slots de esta posición a lo que realmente hay
            config_formacion[pos] = disponibles[pos]

    # Redistribuir los slots faltantes a las posiciones que tienen sobrantes
    # Priorizar: defensora > volante > delantera (más útil llenar defensa primero)
    # PERO no a la arquera (no podemos meter más arqueras de las que hay)
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
                # Esta posición puede absorber un slot extra
                config_formacion[pos] = slots_actuales + 1
                slots_a_redistribuir -= 1
                progreso = True
        if not progreso:
            # No se puede redistribuir más (no hay sobrantes)
            break

    # Cuántos turnos le toca jugar a cada una
    turnos_objetivo = {}
    for p in convocadas:
        if p.id in anclas_ids:
            # Anclas: todos los turnos
            turnos_objetivo[p.id] = cantidad_turnos
        else:
            turnos_objetivo[p.id] = calcular_turnos_por_jugadora(p, duracion_turno)

    # Cuántos turnos lleva asignados cada jugadora durante la generación
    turnos_asignados = {p.id: 0 for p in convocadas}

    # Plan resultado
    plan = {}

    # Iteramos turno por turno
    for turno_n in range(1, cantidad_turnos + 1):
        plan[turno_n] = []

        # Para cada posición, cuántas jugadoras van en cancha simultáneamente
        for pos in [Posicion.ARQUERA, Posicion.DEFENSORA, Posicion.VOLANTE, Posicion.DELANTERA]:
            n_cancha = config_formacion.get(pos, 0)
            if n_cancha == 0:
                continue

            # Candidatas para esta posición:
            # - Jugadoras de esta posición principal
            # - Que NO esté ya asignada al turno actual
            # - Ordenadas por prioridad: anclas primero, después por (turnos_pendientes desc, prioridad desc)
            candidatas = [
                p for p in convocadas
                if p.posicion == pos
                and p.id not in plan[turno_n]
            ]

            def prioridad_seleccion(p):
                # 1. Anclas primero (turnos_pendientes alto = cantidad_turnos)
                # 2. Después: cuántos turnos le quedan por jugar
                # 3. Empate: prioridad calculada
                turnos_pendientes = turnos_objetivo[p.id] - turnos_asignados[p.id]
                es_ancla = 1 if p.id in anclas_ids else 0
                return (es_ancla, turnos_pendientes, p.prioridad)

            candidatas.sort(key=prioridad_seleccion, reverse=True)

            # Tomamos las primeras n_cancha que tengan turnos pendientes (>0)
            seleccionadas = []
            for cand in candidatas:
                if len(seleccionadas) >= n_cancha:
                    break
                pendiente = turnos_objetivo[cand.id] - turnos_asignados[cand.id]
                if pendiente > 0:
                    seleccionadas.append(cand)

            # Si no llenamos la posición (no hay suficientes con turnos pendientes),
            # completamos con jugadoras de la misma posición (aunque ya hayan cubierto)
            if len(seleccionadas) < n_cancha:
                for cand in candidatas:
                    if cand in seleccionadas:
                        continue
                    if len(seleccionadas) >= n_cancha:
                        break
                    seleccionadas.append(cand)

            for sel in seleccionadas:
                plan[turno_n].append(sel.id)
                turnos_asignados[sel.id] += 1

    return plan


def validar_swap(
    plan_turno: list,
    formacion: str,
    sale_jugadora,  # objeto Jugadora del modelo Flask
    entra_jugadora,  # objeto Jugadora del modelo Flask
) -> tuple:
    """
    Valida que un swap sea legal. Devuelve (es_valido, mensaje).

    Reglas:
    - La que entra no puede estar ya en el turno
    - La que sale debe estar en el turno
    - Tienen que poder ocupar la misma posición (principal o alternativa)
    """
    if entra_jugadora.id == sale_jugadora.id:
        return False, "No podés intercambiar una jugadora consigo misma"

    if sale_jugadora.id not in plan_turno:
        return False, f"{sale_jugadora.nombre} no está en este turno"

    if entra_jugadora.id in plan_turno:
        return False, f"{entra_jugadora.nombre} ya está en este turno"

    # Verificar compatibilidad de posición
    pos_de_sale = {sale_jugadora.posicion}
    if sale_jugadora.posicion_alt:
        pos_de_sale.add(sale_jugadora.posicion_alt)

    pos_de_entra = {entra_jugadora.posicion}
    if entra_jugadora.posicion_alt:
        pos_de_entra.add(entra_jugadora.posicion_alt)

    # Tiene que haber al menos una posición en común
    if not (pos_de_sale & pos_de_entra):
        return False, (
            f"{entra_jugadora.nombre} ({entra_jugadora.posicion}) no puede ocupar "
            f"la posición de {sale_jugadora.nombre} ({sale_jugadora.posicion})"
        )

    return True, "OK"
