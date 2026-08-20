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

**Lo más cómodo: doble clic en `montar.bat`.** Te pregunta el nombre de la carpeta del vídeo y cuántas partes quieres, la crea dentro de `Escritorio\MasterTube`, la abre en el Explorador y espera. Sueltas dentro la narración, el guion y los clips, pulsas Enter, y monta. Si escribes el nombre de una carpeta que ya existe, la usa tal cual; y si ya está completa, no espera a nada.

```
  MasterTube : C:\Users\junio\Desktop\MasterTube
  ya hay     : noveno video, diez video, once video

  Nombre de la carpeta del video: doce video
  Cuantas partes (parte1...parteN)? [4]: 4
  Creada     : C:\Users\junio\Desktop\MasterTube\doce video
               con parte1 ... parte4
```

La carpeta MasterTube se puede mover con la variable de entorno `MASTERTUBE`.

### El guion lo escribe Claude, hablando contigo

Cuando esté esperando material, escribe `guion` en vez de pulsar Enter (o haz doble clic en `guion.bat`). Se abre una ventana de chat: eliges con qué **reglas** escribirlo, escribes de qué va el vídeo, y a partir de ahí lo lleva Claude.

Si tus reglas trabajan por pasos, la conversación va sola: te propone tres hooks y se para, eliges, pasa al contexto, y así hasta la última parte. **No escribe el guion entero de golpe** — te va preguntando, igual que en claude.ai.

La ventana tiene dos pestañas y conviene no confundirlas:

- **Conversación** — lo que Claude te dice: las opciones, las preguntas, sus comentarios.
- **Guion** — solo el texto que se va a locutar. Es lo único que acaba en `guion.txt` y en el mp3.

Claude separa una cosa de otra y la ventana va acumulando en la pestaña Guion cada trozo bueno según llega. Puedes editarlo ahí mismo. **Guardar guion.txt** lo deja en la carpeta del vídeo, y después pulsas Enter en la consola para que el montaje siga.

Debajo del chat aparecen **botones de atajo** con lo que toque responder: si te ofrece tres opciones salen `A` `B` `C` y un `Otra vuelta`; si te pregunta si sigue con la parte siguiente, sale `Parte 2`. Son un atajo, no una jaula: la caja de texto sigue ahí para pedirle lo que quieras («cambia el hook», «esa cifra no me cuadra», «alarga la parte 3»). Enter manda, Shift+Enter hace párrafo.

**Empezar de cero** olvida la conversación pero **no** borra el guion que ya has recogido.

#### Investiga antes de escribir

Claude tiene **buscador** mientras escribe el guion: comprueba las cifras, las fechas y los nombres propios, y si el tema sigue vivo busca el dato reciente en vez de tirar de lo que recuerde. Los turnos en los que busca tardan más — es el precio de que las cifras sean de verdad.

Las fuentes te las cita en la conversación, **no** dentro del guion: ahí no pintan nada porque no se locutan.

Solo se le abren la búsqueda y la lectura de páginas. No toca los archivos de tu carpeta.

Si algún dato no lo ha podido confirmar, te lo dice en una línea aparte en vez de colarlo como si tal cosa.

#### Las reglas: tus proyectos de Claude, en local

Las instrucciones de un proyecto de claude.ai no se pueden leer desde fuera —no hay API para eso—, así que se copian **una vez** y ya se quedan:

1. En la ventana, dale a **Nuevas...**
2. Ponle un nombre (el de tu proyecto, por ejemplo) y pega las instrucciones.
3. **Guardar reglas**.

A partir de ahí las eliges en el desplegable y esas mandan. Se guardan como `.txt` en `MasterTube\perfiles`, así que también puedes crearlas o editarlas ahí a mano. **Ver / editar** abre la que tengas seleccionada.

Van dentro del primer mensaje de la conversación, así que se eligen **antes de escribir el tema**: cambiar el desplegable a media charla no cambia nada, vale para la siguiente.

Tus reglas deciden *cómo* se escribe y con qué mecánica. El montador solo añade encima lo que necesita para poder leer el guion después: texto plano y las marcas `[TXT: ...]`. En eso no manda el perfil, porque si el guion sale con markdown o sin marcas, el montaje no puede colocar los rótulos.

La primera vez se crea un perfil de ejemplo, `oriente-avanza`, para que tengas de dónde partir.

Habla con Claude de dos formas:

- **Por el CLI de Claude Code** que ya tienes instalado. Es lo que usa por defecto: no hace falta API key ni instalar nada.
- **Por la API de Anthropic**, como respaldo, si no encuentra el CLI. Para eso sí hacen falta `pip install anthropic` y la variable `ANTHROPIC_API_KEY`.

Si ya había un `guion.txt` en la carpeta, la ventana lo carga al abrirse, y al guardar uno nuevo el anterior se conserva como `guion_anterior.txt`.

#### Si prefieres no hablar

Para reglas que son solo estilo, sin pasos que seguir, está el modo de un tirón: escribe el guion entero por consola, sin ventana y sin preguntar nada.

    python -m montador guion --clips "C:\ruta\al video" --auto "de qué va el vídeo" --minutos 13

Con un perfil por pasos como `oriente-avanza` no sirve: se los saltaría.

### Qué clips buscar, parte por parte

Con el guion terminado, la pestaña **Clips** y el botón **Pedir las busquedas a Claude**. Como está en la misma conversación, ya sabe de qué va cada parte: no hay que explicárselo otra vez.

Devuelve entre seis y diez búsquedas por parte, de lo más específico a lo más genérico — los nombres propios y los términos en el idioma original primero, el relleno al final:

    PARTE 1
    Long March 10B first stage recovery full video
    CZ-10B 长征十号乙 回收
    Long March 10B net capture Linghang Zhe
    China rocket caught in net at sea CGTN

Dos botones y ya:

- **Abrir en el navegador → Parte 1** abre cada búsqueda en su pestaña. Si son más de tres, avisa antes.
- **Guardar en las carpetas parteN** deja un `busquedas.txt` **dentro de cada carpeta**. Así, cuando abras `parte3` para llenarla de clips, la lista está ahí mismo.

El texto es editable: pruebas una búsqueda, no da nada, cambias una palabra. Lo que se guarda y lo que se abre es lo que tengas en pantalla, no lo que dijo Claude.

Si el guion tiene cinco partes y solo creaste cuatro carpetas, las búsquedas de la quinta se suman al `busquedas.txt` de la última.

### Y la voz, en la misma ventana

Con el guion delante, **Generar voz (Narrador v2)** lo manda a ai33.pro y descarga la narración como `narracion.mp3` en la carpeta del vídeo. Te dice cuántos caracteres va a narrar antes de gastar créditos, y la barra va marcando el progreso.

Las marcas `[TXT: ...]` se quitan antes de mandarlo — si no, el narrador las leería en voz alta. En el `guion.txt` se quedan, que es donde hacen falta para los rótulos.

Con eso la carpeta ya tiene guion y narración; solo faltan los clips en sus `parteN` y el montaje puede seguir.

La clave de ai33.pro se lee de `MasterTube\ai33.key` (o de la variable `AI33_API_KEY`), nunca del código. Si quieres otra voz o otra velocidad: `python -m montador voz --voz <id> --velocidad 1.1`; los ids salen de `GET /v3/voices?provider=fishaudio`. Un `narracion.mp3` anterior se guarda en la subcarpeta `anteriores`.

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

`--proyecto` se puede omitir: por defecto es el nombre de la carpeta sin espacios y con `_auto` detrás. El `edl.json` se guarda también en la carpeta del vídeo.

En Windows, si la carpeta ya está hecha: **arrástrala encima de `montar.bat`**. No hay que escribir nada.

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
