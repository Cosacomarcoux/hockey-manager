# Módulo de Rotación Semiautomática

Lógica pura para gestionar rotaciones de jugadoras durante un partido de hockey.
Diseñado para integrarse con tu app actual sin tocar la base de datos directamente.

---

## 🧱 Arquitectura

```
rotacion_module/
├── __init__.py           # Exports públicos
├── player.py             # Clase Player (modelo de datos)
├── priority.py           # Algoritmo de prioridad y reparto de minutos
├── rotation_systems.py   # Modos: Células, Bloques, Anclas
├── match_controller.py   # MatchController (corazón del módulo)
└── tests.py              # 17 tests que validan toda la lógica
```

**Separación de capas:**
- `Player`: datos puros (sin lógica)
- `priority`: algoritmo matemático (funciones puras)
- `rotation_systems`: configuración de modos
- `MatchController`: orquesta todo en runtime

---

## 📐 El algoritmo de prioridad

```
P = (C × K) + (A × (1 − K))

donde:
  C = capacidad / 5         (0.2 a 1.0)
  A = asistencia / 100      (0.0 a 1.0)
  K = factor de competitividad (0.6 a 0.9)
```

| K     | Modo         | Qué prioriza                            |
|-------|--------------|-----------------------------------------|
| 0.9   | Competitivo  | Capacidad casi únicamente               |
| 0.7   | Balanceado   | Mix capacidad + asistencia (default)    |
| 0.6   | Formativo    | Asistencia gana peso                    |

**Nota matemática importante:** Por cómo está construida la fórmula, incluso con K=0.6 la capacidad pesa más que la asistencia *a igual diferencia de input*. Para que la asistencia "venza" a la capacidad necesitás una diferencia muy grande (ej. cap=2 vs cap=5 con asistencia 100% vs 20%). Si querés un modo "puramente formativo" donde la asistencia siempre gane, habría que ajustar la fórmula. Avisame si querés esa variante.

---

## 🏑 Reparto de minutos por posición

Total de minutos-jugadora del partido (60 min × 11 en cancha) = **660 min**.

Se reparten dentro de cada grupo de posición proporcional a P:

```python
minutos_teoricos[jugadora] = (P[jugadora] / suma_P_grupo) × (N_cancha × 60)
```

Donde `N_cancha` depende de la formación:
- 4-3-3: Arq=1, Def=4, Vol=3, Del=3
- 4-4-2: Arq=1, Def=4, Vol=4, Del=2
- 3-5-2: Arq=1, Def=3, Vol=5, Del=2
- 5-3-2: Arq=1, Def=5, Vol=3, Del=2
- 4-2-3-1: Arq=1, Def=4, Vol=5, Del=1

---

## 🔁 Modos de rotación

### Modo LIBRE (default)
Sugiere cambios individuales según prioridad. Para cada jugadora con alerta CAMBIO,
busca en el banco la candidata de su misma posición con mayor déficit.

### Modo CÉLULAS
Definís grupos de 2-4 jugadoras que rotan juntas. Cuando alguna del grupo activa
el umbral, se sugiere cambiar el grupo entero.

```python
config.celulas = [
    Celula(nombre="Pareja delantera", jugadoras_ids=[11, 12]),
    Celula(nombre="Defensa derecha", jugadoras_ids=[2, 3]),
]
```

### Modo BLOQUES
Cambia toda una línea (ej. todas las defensoras) cada X minutos.

```python
config.bloques = [
    Bloque(nombre="Línea def", posicion="Defensora", intervalo_minutos=5.0),
    Bloque(nombre="Línea del", posicion="Delantera", intervalo_minutos=4.0),
]
```

### Anclas
Compatible con cualquier modo. Las jugadoras ancla NUNCA reciben alerta de
cambio (excepto por lesión).

```python
config.anclas_ids = {1, 2}   # Arquera y Ana defensora son intocables
```

---

## ⏱ Estados de alerta

Cada jugadora EN_CANCHA tiene una `alerta_actual`:

| Estado        | Cuándo                                        | Qué hacer        |
|---------------|-----------------------------------------------|------------------|
| `NINGUNA`     | bloque_actual < (umbral - pre_alerta)         | Nada             |
| `PRE_ALERTA`  | bloque_actual ≥ (umbral - 1 min)              | Que entre en calor la suplente |
| `CAMBIO`      | bloque_actual ≥ umbral                        | Sugerir cambio   |
| `LESIONADA`   | failsafe activado                             | Cambio inmediato |

---

## 🚨 Failsafe (lesión / tarjeta)

```python
sugerencia_urgente = mc.marcar_lesionada(player_id)
# → SugerenciaCambio con urgencia=LESIONADA y reemplazo recomendado

# Después de confirmar el cambio, recalcular el reparto:
mc.recalcular_minutos_post_lesion()
# → Los minutos teóricos que iba a jugar la lesionada se reparten
#   entre las demás de su misma posición.
```

Mientras haya lesionadas en cancha, `obtener_sugerencias()` devuelve SOLO
emergencias (las normales quedan postergadas).

---

## 🚀 Uso completo

```python
from rotacion_module import (
    Player, Posicion, Estado,
    ConfiguracionRotacion, ModoRotacion, Celula, Bloque,
    MatchController,
)

# 1. Armar el plantel
players = [
    Player(id=1, nombre="Belen", apellido="A",
           capacidad=5, asistencia=90, posicion=Posicion.ARQUERA),
    Player(id=2, nombre="Ana", apellido="D1",
           capacidad=5, asistencia=95, posicion=Posicion.DEFENSORA),
    # ... resto del plantel
]

# 2. Configurar el partido
config = ConfiguracionRotacion(
    modo=ModoRotacion.LIBRE,
    umbral_cambio_minutos=5.0,
    tiempo_pre_alerta_minutos=1.0,
    anclas_ids={1, 2},   # arquera y Ana son anclas
)

# 3. Crear el controller
mc = MatchController(players, config, K=0.7, formacion="4-3-3")
mc.asignar_titulares_automaticos()  # opcional

# 4. Loop del partido (en tu app, esto se sincroniza con el cronómetro real)
while not mc.partido_finalizado:
    mc.tick(0.5)   # avanza 30 segundos

    # Ver sugerencias actuales
    for sugerencia in mc.obtener_sugerencias():
        print(sugerencia)

        # Si el entrenador acepta:
        if entrenador_acepta_en_la_app(sugerencia):
            if sugerencia.es_grupal:
                mc.confirmar_cambio_grupal(
                    [p.id for p in sugerencia.grupo_sale],
                    [p.id for p in sugerencia.grupo_entra],
                )
            else:
                mc.confirmar_cambio(sugerencia.sale.id, sugerencia.entra.id)

    # Caso failsafe
    if alguien_se_lesiono(...):
        sug = mc.marcar_lesionada(jugadora_lesionada_id)
        # mostrar sug urgente al entrenador
        # cuando confirme: mc.confirmar_cambio(...) + mc.recalcular_minutos_post_lesion()

mc.finalizar_partido()
```

---

## 🧪 Correr los tests

```bash
cd <directorio-padre>
python -m rotacion_module.tests
```

Salida esperada: `RESULTADO: 17/17 tests pasaron`

---

## 🔧 Próximos pasos para integrar con tu app Flask

Cuando estés listo, la integración consistirá en:

1. **Crear un adaptador** que mapee `Jugadora` (modelo Flask/SQLAlchemy) a `Player`.
2. **Persistir el estado** del controller en la base de datos (tabla nueva `rotacion_state`).
3. **Conectar el tick** con tu cronómetro existente del partido en vivo.
4. **Agregar UI** en la pantalla de partido para mostrar sugerencias y confirmarlas.

Esto es la **Fase B**. Por ahora, lo que tenés es una lógica probada
y funcionando que podés ejercitar con casos de prueba.
