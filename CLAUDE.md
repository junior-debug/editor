# montador-capcut — contexto para Claude Code

Lee esto antes de tocar nada. Resume de dónde viene el proyecto, qué está
resuelto, qué no, y las convenciones que sigue.

## Qué es

Genera un **borrador de CapCut ya montado** (`draft_content.json` +
`draft_meta_info.json`) a partir de tres entradas: el audio de la narración,
el guion, y carpetas de clips `parte1`…`parteN`.

No es un editor de vídeo. Automatiza la fase mecánica del montaje —cortar a
~4,7 s, ordenar, poner transiciones, colocar sonidos, meter rótulos— y deja
el retoque creativo dentro de CapCut, que es donde el usuario ya trabaja.

Usuario: junior, canal de YouTube "Oriente Avanza" (tecnología,
megaestructuras, geopolítica Asia–Occidente). Windows 11, CapCut 9.2.8 de
escritorio, Python 3.14, GPU NVIDIA con CUDA funcionando.

## Decisión de diseño central

**El EDL es la fuente de verdad.** `edl.py` produce un JSON plano que no sabe
nada de CapCut. De él salen dos backends: el escritor de borradores y un
render directo con FFmpeg.

Esto no es sobreingeniería. El formato de borrador de CapCut es ingeniería
inversa no oficial: ByteDance no lo documenta ni se compromete a mantenerlo.
Si una actualización lo rompe, la lógica de montaje sigue intacta.

**El escritor no construye JSON desde cero.** Clona prototipos extraídos de un
proyecto real del usuario (`plantillas/prototipos_9.2.8.json`) y sustituye
solo lo que cambia. Todo campo que no entendemos se conserva tal cual venía
de CapCut. Si vas a añadir un tipo de elemento nuevo, extrae primero su
prototipo de un proyecto real; no lo inventes.

## El estilo, y de dónde salen los números

`config.py` está calibrado sobre un montaje real del usuario (proyecto
"0817": 167 cortes, 776 s). El análisis completo está en
`analisis-estilo-montaje.md`. Los hallazgos que importan:

- Cortes: media 4,65 s, mediana 4,67 s, 81 % entre 4 y 6 s.
- **La selección de clips es determinista.** 167 cortes salieron de 11
  archivos, por rotación con un cursor de lectura propio por archivo. Las
  carpetas `parteN` entran de forma acumulativa sin sacar a las anteriores.
  No hace falta matching semántico ni IA para elegir plano — si alguien
  propone embeddings CLIP para esto, es trabajo desperdiciado.
- Transiciones en el 32 % de los cortes, una cada ~3,1.
- **Los sonidos NO van en cortes con transición**: 53 de 55 caen en cortes
  secos. La transición larga ya es el acento visual; el corte seco lleva el
  golpe. Se alternan, no se suman.
- Los sonidos se anticipan al corte hasta 0,87 s; ~45 % caen en el frame
  exacto.

Al cambiar el estilo, tocar `config.py`, no la lógica.

## El guion lo escribe Claude, hablando

`guionista.py` no escupe el guion de un tirón: lo negocia por turnos, porque
así es como trabaja el usuario. Claude propone tres hooks y se para; el
usuario elige; Claude pasa al paso siguiente; y así hasta la última parte.
`Conversacion` es la clase que lleva ese hilo, y `ui_guion.py` la envuelve en
un chat.

**Las reglas de estilo son del usuario, no del código.** Vienen de sus
proyectos de claude.ai, y como las instrucciones de un proyecto de claude.ai
no se pueden leer desde fuera —no hay API para eso—, se copian una vez a
`MasterTube\perfiles\<nombre>.txt` y de ahí las lee `perfiles.py`. La ventana
las ofrece en un desplegable y trae un editor para pegarlas sin salir de la
aplicación. Si alguien retoma esto buscando "conectar con el proyecto de
Claude": no se puede, y el puente manual de una sola vez es la solución, no
un parche.

Las reglas de hoy (`oriente-avanza`) no son solo estilo: son un **protocolo**.
Fase A, la intro en cinco pasos, uno por mensaje. Fase B, cinco partes, una
por mensaje, seis párrafos cada una salvo la quinta. Por eso el montador no
puede limitarse a pedir texto — tiene que dejar hablar a Claude y esperar.

### Los dos contratos de formato

El prompt se compone en dos capas y el orden importa: primero las reglas del
perfil (o `ESTILO_POR_DEFECTO`), después el contrato, **siempre al final**,
porque lo último que se lee es lo que mejor se respeta. El perfil manda en el
estilo; el contrato solo impone el formato que el montador necesita.

Hay dos contratos porque hay dos modos, y confundirlos rompe el otro:

- `CONTRATO_FORMATO` — el del modo de un tirón. Exige *solo el texto del
  guion, sin comentarios tuyos*.
- `CONTRATO_CONVERSACION` — el del chat. Ahí no se puede exigir eso: sería
  prohibir justo lo que las reglas del usuario piden, que pregunte y espere.
  En vez de callarlo, se le pide que **separe**: lo que se locuta va envuelto
  entre `---GUION---` y `---FIN---`, y todo lo demás —opciones, preguntas,
  avisos— va fuera.

Ese delimitador es lo que sostiene la ventana entera. Sin él no se puede
conversar y armar el guion a la vez, y las tres opciones de hook acabarían
dentro del mp3. `extraer_guion()` lo lee y devuelve `(bloques, charla)`: los
bloques se acumulan en la pestaña Guion, la charla se pinta en el chat.

El contrato dice además que **solo se envuelve lo definitivo**. Importa: la
intro del PASO 5 no es guion final —la Parte 1 la despliega en prosa—, así que
se queda fuera de las marcas y no entra dos veces.

`atajos()` mira lo que Claude acaba de decir y saca los botones: si ofrece
opciones etiquetadas, salen `A` `B` `C` y un "Otra vuelta"; si pregunta por
una parte, sale `Parte N`; si pregunta cualquier otra cosa, `Adelante`. Se
deduce del texto, no de las reglas, **a propósito**: así la ventana no sabe
que existen "5 pasos" ni "5 partes" y sigue sirviendo si el usuario reescribe
su perfil mañana.

### Los backends

- **CLI** (`claude -p`), el de por defecto. Usa la instalación de Claude Code
  que el usuario ya tiene autenticada: sin API key y sin dependencias. Se
  ejecuta con `cwd` en la carpeta del vídeo **a propósito**: desde la carpeta
  del montador, Claude Code cargaría este CLAUDE.md y escribiría el guion con
  todo este contexto encima.

  El hilo se mantiene con `--resume <session_id>`, no reenviando la
  conversación en cada prompt. Por eso la salida se pide en `--output-format
  json`: el `session_id` sale de ahí. Comprobado que el turno siguiente se
  sirve de caché.
- **API** (SDK `anthropic`, modelo `claude-opus-5`), respaldo. Ahí el
  historial sí se lleva a mano en `Conversacion.mensajes`. Se importa dentro
  de la función, así que solo hay que instalarlo si se usa de verdad.

Las reglas van en el **primer mensaje**, no en un system prompt: es lo que ya
estaba comprobado que funciona, y de ahí en adelante siguen delante de Claude
porque la sesión entera se conserva.

### Investiga antes de escribir

El CLI se lanza con `--allowedTools WebSearch WebFetch`. Hacen falta **las dos
cosas**, y es un error fácil de cometer dejarse una:

- Sin el permiso, las llamadas se rechazan solas. En modo `-p` no hay nadie
  que acepte el diálogo, así que Claude contesta que no tiene la herramienta
  concedida.
- Sin el encargo (`INVESTIGAR`), no busca aunque pueda. Comprobado: en la
  primera conversación real, con las herramientas ya disponibles, no tocó ni
  una y escribió de memoria.

`INVESTIGAR` no es estilo ni formato, así que no va en ninguno de los dos
contratos: va aparte, entre las reglas y el contrato, y **solo con el backend
del CLI** — el respaldo por API no lleva herramientas y allí el encargo sería
pedirle algo que no puede hacer.

Se le abren esas dos herramientas y ninguna más. No tiene por qué leer ni
escribir archivos en la carpeta del vídeo, y se ejecuta dentro de ella.

Que las fuentes **no entren en el guion** lo dice el propio encargo: se citan
fuera, hablando, que es donde no se locutan. Si un día aparecen URLs dentro de
un bloque `---GUION---`, se arregla ahí y no con un filtro después.

Para comprobar si de verdad buscó no sirve `usage.server_tool_use` de la
respuesta: el `WebSearch` del CLI no es herramienta de servidor y ese contador
sale siempre a cero. Lo que vale es contar los bloques `tool_use` de la
transcripción que Claude Code deja en
`~\.claude\projects\<ruta-codificada>\<sesion>.jsonl`.

### El modo de un tirón sigue ahí

`generar()` y `guion --auto "<tema>"` escriben el guion entero sin preguntar
nada, con `CONTRATO_FORMATO`. Es para perfiles que solo son reglas de estilo,
sin mecánica por pasos. Con un perfil como el de hoy no sirve: se saltaría los
pasos.

El guion sale en texto plano y con las marcas `[TXT: ...]` que `edl.py` ya
sabe leer: no hay ningún paso de limpieza entre una cosa y la otra, y no
debería hacer falta añadirlo — si aparece markdown en la salida, se arregla
en el prompt, no con un filtro después.

Al guardar, un `guion.txt` anterior distinto se conserva como
`guion_anterior.txt`.

## La narración: ai33.pro (OpenSpeaker)

`voz.py` convierte el guion en `narracion.mp3`. La documentación de la API no
es pública (la página va tras login y el sitio devuelve 403 a cualquier
fetcher); está embebida en el bundle de la SPA, de donde se sacó todo esto:

- Cabecera de autenticación: **`xi-api-key`**, no `Bearer`.
- `POST /v3/text-to-speech`, **multipart/form-data**, no JSON. Campos:
  `text` (hasta 1.000.000 de caracteres), `voice_id`, `speed` (0,5–1,5),
  `with_transcript`, `file_name`, `receive_url`. Devuelve `{success, task_id}`.
- Es **asíncrona**: se sondea `GET /v1/task/{task_id}` hasta `status: "done"`,
  y el mp3 sale en **`metadata.audio_url`**.
- `GET /v3/voices?provider=...` lista las voces; `provider` es obligatorio y
  el `voice_id` lleva el prefijo del proveedor. La voz del canal es
  **Narrador v2** = `fishaudio_35199d5438854f5d9157c500479ab684`.
- `GET /v1/credits` da el saldo. Cuesta ~1 crédito por carácter.
- 429 y 503 son temporales y traen `Retry-After`; se reintenta solo.

Dos cosas que no son evidentes y costaron un rato:

- **El CDN devuelve 403 al User-Agent de urllib.** La descarga del mp3 manda
  uno de navegador. Si algún día deja de bajar el audio pero la tarea sí
  termina, mirar ahí.
- **Las marcas `[TXT: ...]` se quitan antes de narrar.** Si no, el narrador
  lee "TXT dos puntos" en mitad de la frase. Lo hace `texto_locutable()`.

Un `narracion.mp3` anterior se mueve a la subcarpeta `anteriores\`, **no** se
renombra al lado: `revisar()` exige un único audio suelto en la carpeta, y un
`narracion_anterior.mp3` al lado bloquearía el montaje.

La clave **no está en el repositorio**: se lee de `MasterTube\ai33.key` o de
la variable de entorno `AI33_API_KEY`. `.gitignore` cubre `*.key`.

## Verificar cambios

`herramientas/analizar_estilo.py` saca métricas de cualquier
`draft_content.json` y compara dos lado a lado. Es la forma de comprobar que
un cambio no ha alejado la salida del estilo del usuario:

    python herramientas/analizar_estilo.py suyo.json generado.json

Contrato mínimo tras tocar `edl.py` o `escritor.py`:

    python -m montador montar --clips ejemplo/clips --proyecto prueba --borradores ejemplo/borradores

y comprobar sobre el JSON generado: claves de nivel superior y de segmento
idénticas a las del original, cero referencias huérfanas en
`extra_material_refs`, pista de vídeo contigua sin huecos, y `duration` igual
al final del último segmento.

## Estado

Funciona de punta a punta. El usuario ha montado varios vídeos con él
(`noveno_auto`, `diez_auto`, `once_auto`).

### Problema abierto: CapCut bloquea la exportación pidiendo Pro

Al exportar un proyecto generado, CapCut saca la pasarela de Pro con una
única función listada: **"Extraer audio"**.

Causa identificada (y corregida en el escritor): el material de la narración
se clonaba de un efecto de sonido de la biblioteca de CapCut, conservando
`effect_id`, `app_id` y `category_name: "Favoritos"` mientras apuntaba a un
MP3 del disco del usuario. Un material híbrido que CapCut no produce jamás.
`_material_audio_local()` ahora parte del prototipo de audio local y limpia
todos los identificadores de biblioteca.

`herramientas/reparar_audio.py` arregla proyectos ya generados sin
regenerarlos.

**Lo que NO está confirmado:** que eso elimine el diálogo. En el último
intento seguía apareciendo, y en el panel de medios del proyecto aparecía un
elemento `Extraído20260819-1` — un medio de audio extraído creado por CapCut.
El workaround manual (borrar el clip de narración y ese elemento del panel,
reimportar el MP3 a mano) estaba pendiente de probar cuando se dejó.

Si retomas esto: la pregunta que lo zanja es si un proyecto montado a mano
por el usuario (`0817`, sin material híbrido) exporta sin pedir Pro. Si
también lo pide, el bloqueo no viene del audio y hay que mirar si alguna
transición del catálogo es Pro.

Ojo con `extract_music`: **es lo que CapCut escribe normalmente** para un
audio importado. No es síntoma de nada. El síntoma es la ruta local con
identificadores de biblioteca.

### Pendiente

- Recalibrar `config.py` comparando un borrador generado con la versión que
  el usuario retoca a mano. El `montar.bat` ya guarda `edl.json` para poder
  hacer la comparación exacta en vez de estadística.
- Posición de los rótulos: hoy se estima por proporción de caracteres del
  guion. Funciona pero es tosco. Alinear el texto del guion con la
  transcripción de Whisper daría la posición real.
- Entrada de las partes: por defecto se reparten uniformemente a lo largo de
  la narración. En el proyecto real fueron 0 / 191 / 467 / 611 s sobre 776.
  Se puede forzar con `--entradas`, pero deducirlo del guion sería mejor.
- Los clips entran a escala 1:1, sin recorte ni zoom. Material que no sea
  1920×1080 sale con bandas.

## Convenciones

- **Todo en español**: nombres de funciones, variables, comentarios,
  docstrings y salida por consola. Sin tildes ni eñes en identificadores;
  sí en cadenas y comentarios.
- Los comentarios explican **por qué**, no qué. Especialmente en el escritor,
  donde muchas decisiones son "porque CapCut lo hace así" y sin la nota
  parecen arbitrarias.
- Semilla fija en `config.py`: el mismo material produce siempre el mismo
  montaje. No introducir aleatoriedad sin semilla.
- Sin dependencias nuevas salvo necesidad real. Hoy solo `faster-whisper`
  (y `anthropic`, opcional, solo para el respaldo por API del guionista); el
  resto es librería estándar + FFmpeg y el CLI de Claude por subproceso.
- CapCut trabaja en **microsegundos**. Usar el helper `us()`.

## Estructura

    montador/
      config.py            el estilo, en números
      proyecto.py          carpeta de trabajo en MasterTube: preguntar nombre,
                           crear parte1..parteN, comprobar que está completa
      guionista.py         guion negociado con Claude por turnos (Conversacion)
                           + modo de un tiron para perfiles sin pasos
      perfiles.py          reglas de guion del usuario (MasterTube\perfiles)
      voz.py               guion -> narracion.mp3 con la API de ai33.pro
      ui_guion.py          ventana (tkinter): chat con Claude, atajos y la
                           pestana Guion donde se acumula lo locutable
      alineacion.py        whisper -> palabras -> pausas (+ registro de DLL de CUDA en Windows)
      edl.py               plan de cortes, rotacion de clips, transiciones, sonidos, rotulos
      capcut/escritor.py   EDL -> draft_content.json + draft_meta_info.json
      render.py            EDL -> MP4 con ffmpeg (borrador rapido y plan B)
      cli.py               montar / guion / voz / edl / alinear / render
                           + autodeteccion de entradas
    herramientas/
      extraer_prototipos.py  draft real -> plantillas/prototipos_*.json
      analizar_estilo.py     metricas de estilo de cualquier draft
      reparar_audio.py       arregla el material hibrido en borradores ya generados
    plantillas/
      prototipos_9.2.8.json  extraido del proyecto "0817"
    ejemplo/                 material sintetico para probar sin tocar material real
    montar.bat               lanzador: doble clic (pregunta el nombre) o
                             arrastrar encima la carpeta del video
    guion.bat                lanzador: solo escribir el guion

## Comandos

    python -m montador montar
    python -m montador montar --clips "C:\ruta\al video" --proyecto nombre
    python -m montador guion  --clips "C:\ruta\al video"
    python -m montador guion  --clips "..." --auto "tema" --minutos 13
    python -m montador voz    --clips "C:\ruta\al video"
    python -m montador edl    --clips ... -o edl.json
    python -m montador render --edl edl.json -o borrador.mp4 --borrador
    python diagnostico.py
    python herramientas/reparar_audio.py

La narración, el guion y `trans.json` se autodetectan dentro de `--clips`.
Whisper es lo lento; `trans.json` se guarda y se reutiliza solo.

Sin `--clips`, `montar` pregunta el nombre de la carpeta y trabaja dentro de
`Escritorio\MasterTube` (se puede mover con la variable de entorno
`MASTERTUBE`): la crea con sus `parteN`, la abre en el Explorador y no sigue
hasta que dentro hay narración y clips. Si ya está completa, no espera. El
nombre del borrador y `edl.json` salen de la carpeta si no se indican.

## Cuidado con

- **CapCut debe estar cerrado** al escribir o reparar un borrador: mantiene
  el proyecto en memoria y al cerrarse lo reescribe.
- Usar siempre un nombre de proyecto nuevo al probar. `escribir()` borra la
  carpeta destino si existe.
- Las rutas dentro del borrador son absolutas: mover las carpetas de clips lo
  rompe.
- Los efectos de sonido se referencian desde la caché de CapCut. Sus
  `effect_id` son legítimos y **no** hay que limpiarlos — solo los del audio
  local.
