# montador-capcut

Genera un **borrador de CapCut ya montado** a partir de tu narración, tu guion y tus carpetas de clips.

No es un editor. Es la fase que te come el tiempo — cortar a 4-5 s, ordenar, poner transiciones, colocar sonidos, meter rótulos — hecha por código. Abres CapCut y encuentras el proyecto montado; el retoque creativo lo haces ahí, con la interfaz que ya dominas.

El estilo está calibrado sobre tu propio montaje (proyecto "0817", 167 cortes, 12:56). No monta "genérico": monta como montas tú. Ver `analisis-estilo-montaje.md`.

---

## Instalación

Requiere Python 3.10+, FFmpeg en el PATH y CapCut de escritorio (Windows).

```bash
pip install faster-whisper
```

FFmpeg: descárgalo de gyan.dev, descomprime y añade la carpeta `bin` al PATH. Comprueba con `ffmpeg -version` y `ffprobe -version`.

`faster-whisper` es lo único que se instala. El resto es librería estándar.

---

## Uso

Organiza el material así:

```
noveno video/
  China fabricaba mas.mp3      <- la narracion (el unico audio)
  guion.txt                    <- con las marcas [TXT: ...]
  parte1/  barco1.mp4  barco2.mp4  byd3.mp4  byd 4.mp4
  parte2/  explorer1.mp4  barco2.mp4  barco3.mp4
  parte3/  interior1.mp4  barco2.mp4
  parte4/  fabrica1.mp4  fabrica2.mp4
```

Otros archivos sueltos en esa carpeta (el MP4 exportado, imagenes) se ignoran: solo se miran las carpetas `parteN`.

Con el material en una sola carpeta (narración, guion y las `parteN` dentro), basta con:

```bash
python -m montador montar --clips "C:\ruta\a\noveno video" --proyecto noveno_auto
```

La narración y el guion se detectan solos dentro de esa carpeta: el único archivo de audio que haya, y el `.txt` (preferiblemente `guion.txt`). La transcripción se guarda como `trans.json` ahí mismo y se reutiliza sola en las siguientes pasadas.

En Windows, más fácil todavía: **arrastra la carpeta del vídeo encima de `montar.bat`**. No hay que escribir nada.

Si quieres indicarlo todo a mano:

```bash
python -m montador montar \
  --narracion "noveno video/narracion.mp3" \
  --clips     "noveno video" \
  --guion     "noveno video/guion.txt" \
  --proyecto  noveno_auto
```

Abre CapCut (ciérralo y vuelve a abrirlo si estaba abierto). El borrador está en la lista.

En Windows la carpeta de borradores se detecta sola (`%LOCALAPPDATA%\CapCut\User Data\Projects\com.lveditor.draft`). Si la tienes en otro sitio, `--borradores "ruta"`.

### Rótulos

Márcalos en el guion mientras escribes:

```
El astillero de Shanghai produjo más tonelaje en un año que toda Europa junta.

[TXT: SE CONFIARON Y CHINA
EMPEZO A CONSTRUIR SUS PROPIOS BARCOS]

Y nadie lo vio venir, porque nadie estaba mirando el mar.
```

Salen con tu plantilla `TITLE EN - WORLD NEWS`, 3,0 s, en su pista. La posición se estima por la proporción de caracteres del guion: te deja el rótulo cerca y lo ajustas en CapCut arrastrándolo.

### Reutilizar la transcripción

Whisper es lo más lento del proceso. Guárdala la primera vez y reutilízala mientras iteras:

```bash
python -m montador montar ... --guardar-transcripcion trans.json
python -m montador montar ... --transcripcion trans.json      # instantáneo
```

### Borrador rápido sin abrir CapCut

```bash
python -m montador edl    ... -o edl.json
python -m montador render --edl edl.json -o borrador.mp4 --borrador
```

480p ultrafast. Sirve para validar el ritmo en segundos. No reproduce las transiciones de CapCut (son efectos propietarios) ni los sonidos de su librería — para eso, `--sfx carpeta/` con los wav en local.

---

## Cómo decide

**Los cortes** salen de la narración, no de un cronómetro. Whisper da timestamps por palabra, de ahí salen las pausas, y cada frontera se desplaza a la pausa más cercana. Objetivo 4,7 s, techo 6, suelo 3.

**Los clips** rotan. Cada archivo tiene su propio cursor de lectura que avanza; las carpetas `parteN` entran de forma acumulativa sin sacar a las anteriores. Es exactamente lo que haces a mano, y por eso no hace falta ninguna IA para elegir plano.

Por defecto las partes entran repartidas a lo largo de la narración. Si quieres marcarlo tú:

```bash
--entradas 0,191,467,611
```

**Las transiciones** caen una cada ~3 cortes (32 % de los cortes), elegidas al azar de tus diez, ponderadas por el uso real que les das.

**Los sonidos** van uno cada ~14 s y **solo en cortes sin transición** — tu regla, extraída de tus datos: 53 de tus 55 efectos caen en cortes secos. La transición larga ya es el acento; el corte seco lleva el golpe. Casi la mitad caen en el frame exacto, el resto se anticipan hasta 0,87 s.

Todo esto vive en `montador/config.py`, con los números de tu proyecto como valores por defecto. Es el sitio previsto para tocar: cambiar `objetivo_s` a 3.5 te da un montaje más nervioso, `cada_n_cortes` a 5 te quita transiciones.

La semilla es fija: el mismo material produce siempre el mismo montaje. Cámbiala si quieres otra combinación de transiciones y sonidos sobre el mismo corte.

---

## Recalibrar el estilo

Si tu montaje evoluciona, no reescribas la config a mano. Monta un vídeo como te salga, y analízalo:

```bash
python herramientas/analizar_estilo.py "ruta/al/draft_content.json"
```

Te da las métricas actuales. Compara dos proyectos pasando dos rutas — útil para ver si el borrador generado se parece a lo que haces a mano:

```bash
python herramientas/analizar_estilo.py tuyo.json generado.json
```

Si cambias de versión de CapCut y algo deja de abrir, regenera los prototipos desde un proyecto nuevo montado a mano:

```bash
python herramientas/extraer_prototipos.py nuevo_draft_content.json plantillas/prototipos_9.2.8.json
```

---

## Arquitectura

```
narracion.mp3 ─┐
guion.txt ─────┼──→ alineacion.py ──→ edl.py ──→ EDL.json ─┬──→ capcut/escritor.py ──→ borrador
clips/ ────────┘                                            └──→ render.py ──────────→ MP4
```

El **EDL es la fuente de verdad**. Es JSON plano, legible, y no sabe nada de CapCut:

```json
{ "indice": 7, "inicio_s": 31.4, "duracion_s": 4.5,
  "clip": "C:/.../parte1/barco2.mp4", "clip_inicio_s": 12.0,
  "transicion": "7671182918861032722", "transicion_nombre": "Remolino de gel rosa" }
```

Esa separación es deliberada. El formato de borrador de CapCut es ingeniería inversa no oficial: ByteDance no lo documenta ni se ha comprometido a mantenerlo. Si una actualización lo rompe, la lógica de montaje —que es donde está el valor— sigue intacta y tiras del render de FFmpeg mientras se arregla el escritor.

Por el mismo motivo el escritor **no construye el JSON desde cero**: clona prototipos extraídos de tu proyecto real y sustituye solo lo que cambia. Todo campo que no entendemos se conserva tal cual venía de CapCut, que es la única defensa razonable contra un formato sin especificación.

```
montador/
  config.py              el estilo, en números
  alineacion.py          whisper → palabras → pausas
  edl.py                 plan de cortes, rotación de clips, transiciones, sonidos
  capcut/escritor.py     EDL → draft_content.json + draft_meta_info.json
  render.py              EDL → MP4 con ffmpeg
  cli.py
herramientas/
  extraer_prototipos.py  draft real → plantillas/prototipos_*.json
  analizar_estilo.py     métricas de estilo de cualquier draft
plantillas/
  prototipos_9.2.8.json  extraído de tu proyecto "0817"
ejemplo/                 material sintético para probar sin tus archivos
```

---

## Limitaciones conocidas

- **Formato no oficial.** Probado contra CapCut 9.2.8 en Windows. Otra versión puede necesitar regenerar los prototipos.
- **Rutas absolutas.** El borrador apunta a tus archivos donde estén. Si mueves las carpetas, se rompe.
- **Los sonidos son de la librería de CapCut.** Se referencian por su caché local. En otro ordenador, o si CapCut limpia caché, habrá que volver a descargarlos desde la app.
- **La posición de los rótulos es aproximada** (proporción de caracteres del guion). Quedan cerca; el ajuste fino, en CapCut.
- **El render de FFmpeg no es el montaje final** — no tiene las transiciones de CapCut. Es para revisar rápido y como plan B.
- Sin recortes ni zoom: los clips entran a escala 1:1. Si tu material no es 1920×1080 lo verás con bandas.

---

## Si algo falla

```bash
python diagnostico.py
```

Dice desde dónde se carga cada módulo, si el parche de whisper está aplicado, qué carpetas de DLL de NVIDIA encuentra, y prueba a arrancar whisper en GPU y en CPU por separado con el error exacto de cada una.

Errores frecuentes:

- **`cublas64_12.dll is not found`** — falta CUDA, o está instalado pero Windows no encuentra las DLL. `pip install nvidia-cublas-cu12 nvidia-cudnn-cu12`; el montador registra esas carpetas solo. Si aun así falla, `--dispositivo cpu`.
- **PowerShell se queja de `El flujo de salida ya está redirigido`** — has pegado texto que incluía el prompt `PS C:\...>`. Pega solo el comando, o usa `montar.bat`.
- **`No hay ningun archivo de audio`** — la narración no está en la carpeta que le pasas a `--clips`.

## Probar sin tocar tu material

El repo trae material sintético:

```bash
python -m montador montar --clips ejemplo/clips --proyecto prueba --borradores ejemplo/borradores
```

Genera 38 cortes en 180 s, con 34 % de transiciones y un sonido cada ~13 s. Compáralo con tu proyecto real:

```bash
python herramientas/analizar_estilo.py tu_draft.json ejemplo/borradores/prueba/draft_content.json
```
