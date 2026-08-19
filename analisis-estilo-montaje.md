# Análisis del estilo de montaje — proyecto "0817" (noveno vídeo)

Extraído de `draft_content.json` + `draft_meta_info.json`. CapCut 9.2.8, Windows.

---

## 1. Datos base del proyecto

| | |
|---|---|
| Duración del montaje | **776,23 s** (12:56) |
| Duración del proyecto | 1098,07 s (incluye material sin montar aparcado al final) |
| Canvas | 1920×1080, 30 fps |
| Segmentos de vídeo | **167** |
| Clips fuente distintos | **11** |
| Transiciones | 53 |
| Efectos de sonido | 55 |
| Textos | 6 |

**Dato clave:** el montaje dura exactamente lo que la narración (776,23 s en ambos). La pista de vídeo se construye para cubrir la locución, ni un frame más. Eso confirma que la narración es el ancla temporal de todo el proceso.

---

## 2. Duración de los cortes

```
media     4,65 s
mediana   4,67 s
mín       2,40 s
máx       7,07 s
p10-p90   3,80 s – 5,47 s
```

Distribución:

```
2–3 s   ███                                    3
3–4 s   ██████████████████████████            26
4–5 s   ████████████████████████████████████████████████████████████████████████████████████  82
5–6 s   ██████████████████████████████████████████████████████  54
6–7 s   █                                      1
7–8 s   █                                      1
```

El 81% de los cortes cae entre 4 y 6 segundos. No hay cortes de ritmo rápido: es un montaje uniforme, tipo documental.

**Para el generador:** duración objetivo 4,7 s con desviación ±0,8 s, ajustada al punto de respiración más cercano de la narración. Techo duro en 6 s, suelo en 3 s.

---

## 3. El hallazgo importante: la selección de clips es determinista

Esto cambia el diseño del proyecto entero. **167 segmentos salen de solo 11 archivos**, organizados en carpetas `parte1` … `parte4`:

| Archivo | Usos |
|---|---|
| parte1/byd 4.mp4 | 40 |
| parte1/barco2.mp4 | 40 |
| parte2/explorer1.mp4 | 19 |
| parte2/barco3.mp4 | 18 |
| parte2/barco2.mp4 | 18 |
| parte3/barco2.mp4 | 8 |
| parte3/interior1.mp4 | 6 |
| parte1/barco1.mp4 | 5 |
| parte1/byd3.mp4 | 5 |
| parte4/fabrica2.mp4 | 4 |
| parte4/fabrica1.mp4 | 4 |

Y el patrón de uso es **rotación con cursor propio por archivo**:

```
byd4 → barco1 → barco2 → byd3 → byd4 → barco1 → barco2 → byd3 → byd4 → barco2 → ...
```

Cada archivo mantiene su propia cabeza de lectura, que avanza de forma continua:

```
parte1/barco2.mp4:   0,00→5,47   5,47→10,57   10,57→15,77   15,77→21,00   21,00→26,17 ...
```

Verificación de continuidad del cursor:

| Archivo | Saltos continuos |
|---|---|
| parte2/barco3.mp4 | 17 / 17 |
| parte3/barco2.mp4 | 7 / 7 |
| parte2/explorer1.mp4 | 16 / 18 |
| parte2/barco2.mp4 | 15 / 17 |
| parte1/byd 4.mp4 | 21 / 39 |

Las carpetas nuevas **entran en la rotación sin sacar a las anteriores** — el conjunto crece:

```
0 s     → entran los clips de parte1
191 s   → entran los de parte2  (parte1 sigue en rotación)
467 s   → entran los de parte3
611 s   → entran los de parte4
```

`parte1/byd 4.mp4` aparece desde el segundo 0 hasta el 761. No hay correspondencia semántica entre clip y frase.

### Consecuencia

El problema que parecía difícil — *decidir qué clip va con qué frase* — **no existe en este flujo**. No hace falta embeddings, ni CLIP, ni matching semántico, ni IA de ningún tipo para la selección. El algoritmo completo es:

```python
def siguiente_clip(pool, cursores, t):
    pool = [c for c in todos if c.parte_activa_en(t)]   # conjunto acumulativo
    clip = pool[i % len(pool)]                          # rotación
    inicio = cursores[clip]                             # cursor propio
    cursores[clip] += duracion_corte
    return clip, inicio
```

Eso son veinte líneas de Python y reproduce el 100% de las decisiones de selección de este vídeo.

---

## 4. Transiciones

53 transiciones sobre 167 cortes = **32% de los cortes**. Separación media: **una cada 3,1 cortes** (moda exacta: 3).

| Transición | Usos | Duración |
|---|---|---|
| Desenfocar | 9 | 0,47 s |
| Croma de píxeles | 8 | 2,0 s |
| Remolino de gel rosa | 8 | 1,47–2,0 s |
| Mezcla y revelación | 5 | 1,73–2,0 s |
| Combinar | 5 | 0,47 s |
| Barrido gelatinoso | 6 | 1,67–2,0 s |
| Ajuste desplazado | 4 | 1,2–2,0 s |
| Círculo de fuego | 3 | 1,47 s |
| Error de señal | 3 | 1,8–2,0 s |
| Impacto de fuego | 1 | 1,0 s |

Dos familias claras: las cortas y neutras (`Desenfocar`, `Combinar`, 0,47 s, `is_overlap: false`) y las largas y vistosas (2,0 s, `is_overlap: true`).

Los `effect_id` son estables y reutilizables — se copian tal cual al JSON generado:

```
Desenfocar            6916426617455645186
Croma de píxeles      7665629734243503378
Combinar              6724845717472416269
Remolino de gel rosa  7671182918861032722
Mezcla y revelación   7667469125362453767
Barrido gelatinoso    7665566915024260360
Ajuste desplazado     7665267554369277191
Círculo de fuego      7647004085459225857
Error de señal        7667095812756868359
Impacto de fuego      7661956939139665173
```

---

## 5. Sonidos

55 efectos, uno cada **14,1 s** de media (mín 4,4 / máx 19,6). Cinco sonidos concentran el 95%:

| Sonido | Usos |
|---|---|
| Glitch sound that matches the sound logo | 11 |
| Click_Mouse_Click_02 | 11 |
| pop! (tapping the mouth with a hand) | 10 |
| Fuwa: short wind noise (swipe) | 10 |
| swish_whoosh (large) | 10 |

**Hallazgo contraintuitivo:** los sonidos **no** van en los cortes con transición. De 55 efectos, 53 caen en cortes sin transición y solo 2 coinciden con una.

Regla implícita: la transición larga ya es un acento visual y no lleva sonido; el corte seco se refuerza con sonido. Se alternan en vez de sumarse.

Colocación respecto al corte: 25 de 55 caen exactamente en el frame del corte (offset < 0,05 s). El resto se anticipa entre 0,2 y 0,87 s — el sonido entra antes para que el impacto aterrice con el cambio de imagen.

---

## 6. Textos

Seis textos en 12:56 — uso escaso y puntual. Dos tipos:

**Rótulos de bloque**, blancos con salto de línea, 3,0 s exactos:

- `SE CONFIARON Y CHINA\nEMPEZO A CONTRUIR SUS PROPIOS BARCOS`
- `China mayor exportador\nde autos`

**Plantilla tipo informativo** (`text_templates`, 3 elementos): `BREAKING NEWS` · `REPORT FROM ORIENTE AVANZA` · `NEWS`, acompañada de un sticker y del sonido de teclado, todo en el segundo 310,03.

Duración fija de 3,0 s en los tres casos. Los textos van en pistas propias (3 y 4), superpuestas al vídeo.

---

## 7. Estructura de pistas

```
track 0  vídeo    167 seg   montaje principal (0 → 776 s)
track 1  vídeo      2 seg   material SIN montar aparcado en 867–1098 s
track 2  sticker    1 seg   gráfico del bloque "BREAKING NEWS"
track 3  texto      1 seg   rótulo
track 4  texto      2 seg   rótulos
track 5  audio      1 seg   sonido de teclado (bloque informativo)
track 6  audio      1 seg   NARRACIÓN completa (0 → 776,23 s)
track 7  audio     55 seg   efectos de sonido
```

La pista 1 es tu zona de descarga: metes el material bruto al final de la timeline y vas cortando trozos hacia la pista 0. El generador no necesita reproducirla, pero conviene saber que existe para no confundirla con contenido montado.

---

## 8. Especificación resultante para el generador

**Entradas**

```
narracion.mp3          ancla temporal — define la duración total
guion.txt              con marcas [TXT: ...] para los rótulos
clips/parte1..N/       carpetas por parte, en orden
sfx/                   los 5 sonidos habituales
```

**Algoritmo**

1. Whisper alinea la narración → timestamps por palabra → lista de pausas.
2. Cortes cada ~4,7 s, desplazados a la pausa más cercana. Techo 6 s, suelo 3 s.
3. Selección de clip: rotación sobre el conjunto acumulativo, cursor propio por archivo.
4. Transición cada 3 cortes, elegida al azar de la tabla ponderada por frecuencia real.
5. Sonido cada ~14 s, **solo en cortes sin transición**, con anticipación de 0 a 0,87 s.
6. Rótulos donde el guion los marque, duración fija 3,0 s, pista propia.
7. Escribir `draft_content.json` + `draft_meta_info.json` en una carpeta nueva de borradores.

**Salida**

Borrador de CapCut listo para abrir. Retoque final dentro de CapCut.

---

## 9. Riesgos

- Formato no oficial: una actualización de CapCut puede romper el esquema. Mitigación: EDL propio como fuente de verdad, con un segundo backend de FFmpeg.
- Las rutas de material son absolutas — mover carpetas rompe el borrador.
- Los `effect_id` de transición y los sonidos de la librería de CapCut dependen de que sigan disponibles en tu cuenta.
