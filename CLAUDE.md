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

- **Una capa de efecto cubre el vídeo entero**: "Ruido negro", de 0 al final,
  sin trocear, con la velocidad a 0,3 (el valor de fábrica del efecto es
  0,33). Sale de `catorce_auto`, donde el usuario la puso a mano.

Al cambiar el estilo, tocar `config.py`, no la lógica.

### La capa de efecto

`EstiloEfecto` en `config.py` la enciende y la apaga. Va en el **EDL**, no
solo en el escritor, por lo mismo que las transiciones y los sonidos: también
son del catálogo de CapCut y también están ahí. Lo que sí es cierto es que
`render.py` no puede aplicarla —es un efecto propietario— y la ignora, igual
que ignora las transiciones.

En la timeline es **una pista propia** con un único segmento; no cuelga de
ningún bloque de vídeo. Va detrás de los rótulos y delante del audio, que es
el orden en el que CapCut las deja al añadirla a mano. Su segmento no lleva
`extra_material_refs` —en el proyecto original venían vacías— y su
`source_timerange` es `null`: un efecto no lee de ningún archivo.

El `path` del material apunta a la caché de efectos de CapCut y **no se
limpia**, igual que los efectos de sonido. Aquí vale la misma regla: los
identificadores de biblioteca solo estorban cuando el material apunta a un
archivo del disco del usuario, que era el caso del audio.

### La cabecera de entrada

"Bordes de fuego" resultó no ser un capricho de aquel vídeo. Mirando los seis
últimos proyectos, en **los seis** hay lo mismo puesto a mano en el segundo
cero: la plantilla `红蓝多行新闻动画planets` durante tres segundos con el efecto
de fuego encima. Es la cabecera de "última hora" con la que arranca el canal.

La plantilla tiene cuatro líneas y **tres son siempre las mismas** —BREAKING
NEWS / REPORT FROM ORIENTE AVANZA / NEWS—; solo cambia la segunda, que es el
titular del vídeo. Esos textos fijos **no están en `config.py`**: salen del
prototipo, que es de donde hay que sacarlos si algún día cambian. `EstiloIntro`
solo dice cuál de los cuatro huecos es el variable, y `Rotulo.hueco` es lo que
permite tocar esa línea dejando las otras tal cual.

El titular lo escribe Claude con la marca `[INTRO: ...]`, y **no vale el primer
`[TXT: ...]`**: se comprobó en seis proyectos y son textos distintos, porque
este resume el vídeo entero y aquel un momento suyo. Sin la marca no se monta
cabecera, así que los guiones de antes siguen igual.

Rótulo y efecto se generan juntos y duran lo mismo, porque son una sola cosa.
Y las pistas de efecto van **una por efecto**: el proyecto del que se copió
tenía dos pistas con un segmento cada una, no una pista con dos.

**Ojo con `plantillas/prototipos_9.2.8.json`: ya no sale de un único
proyecto.** Todo viene de "0817" menos `segmentos.efecto`,
`materiales.efecto` y `catalogo_efectos`, que se extrajeron de `catorce_auto`
y se fusionaron encima. Los dos son CapCut 9.2.8, que es lo que hace segura la
mezcla. Al regenerar el archivo entero desde un solo proyecto se perdería el
efecto si ese proyecto no lo lleva.

## De qué hacer el próximo vídeo

`ideas.py` + `ui_ideas.py`. Claude busca en internet según unas reglas del
usuario, propone temas con su cifra y su fuente, y se lleva la cuenta de lo
que ya se ha hecho para que no lo repita.

**Lo ya hecho no se apunta a mano.** Sale de dos sitios que se suman:

- `MasterTube\ideas.json`, con todo lo propuesto alguna vez y su estado
  (`propuesta`, `elegida`, `hecha`, `descartada`). Una idea descartada no
  vuelve a ofrecerse, y ese es medio motivo de que exista el archivo.
- Las carpetas de vídeo, de donde se lee la marca `[INTRO: ...]` o, si no la
  lleva, la primera frase del guion —que en este canal es siempre el dato que
  engancha—. Eso hace que los seis vídeos anteriores a todo esto cuenten sin
  tener que teclear nada.

Las reglas son del usuario y viven en `MasterTube\perfiles-ideas`, con el
mismo patrón que los perfiles de guion y por el mismo motivo: son contenido
suyo, no código. Hay varias y se eligen en un desplegable, porque el día que
abra un segundo canal sus reglas serán otras.

El encargo lleva **el orden explícito de buscar** (`BUSCA EN INTERNET antes de
responder`), y hace falta: con las herramientas concedidas pero sin el encargo,
Claude escribe de memoria. Es la misma lección que el guionista. En la prueba
real tardó **seis minutos** y devolvió cinco temas con sus fuentes; por eso la
llamada va en un hilo con barra y con un aviso que dice que tarda.

Vuelven en un bloque `---IDEAS---` … `---FIN---`, una por línea con cuatro
campos separados por barras: titular, el dato, por qué ahora, la fuente. El
lector es tolerante como el de las búsquedas —si faltan las marcas pero las
líneas traen sus barras, se leen igual—, porque perder seis temas bien
buscados por un delimitador ausente sería absurdo teniéndolos delante.

El botón está en la **ventana de proyecto** y no en la del guion, porque es el
paso de antes: primero se decide el tema y después se crea la carpeta. Al
elegir una idea no se inventa el nombre de la carpeta —las de junior van por
ordinales, "video quince", no por tema—: se deja el titular a la vista y él la
nombra. Cuando la carpeta se crea, la idea queda `hecha` y anotada con ella.

## Por dónde se entra: la ventana de proyecto

`ui_proyecto.py` es lo primero que sale al abrir el montador sin `--clips`.
Antes esto se preguntaba por consola y no tenía sentido: el resto del trabajo
—guion, voz, clips, montaje— ya pasa entero en una ventana.

Lista los vídeos de MasterTube **del último tocado al primero**, porque lo
normal es seguir con el de ayer, y de cada uno enseña lo que ya tiene hecho:
cuántas partes, cuántos clips, si hay guion y si hay voz. Por consola había
que ir mirando carpeta por carpeta.

`es_proyecto()` separa los vídeos del material de trabajo: en MasterTube
conviven con `perfiles`, `reuniones`, `nicho`… Se reconoce **por lo que hay
dentro** —alguna `parteN`, un guion o un audio— y no por el nombre, que cada
uno pone el que quiere. La casilla "ver todas" enseña el resto, y si el filtro
no deja nada se enseña todo igualmente: entonces el que se equivoca es el
filtro, no el usuario.

Son **dos `Tk()` seguidos y nunca a la vez** —esta ventana se destruye antes
de que exista la del guion—, porque tkinter no lleva bien dos raíces vivas.

Un nombre que ya existe no pisa nada: abre la carpeta que hay, que es lo que
se quería. Y `preparar()` (el camino de `montar.bat`) usa la misma ventana,
con la consola de respaldo por si algún día no hay escritorio donde abrirla.

**Al elegir una carpeta a la que le falta material se abre sola la ventana del
guion**, en lugar de listar por consola lo que hay que dejar dentro. No es un
atajo: esa ventana es el sitio donde se resuelve lo que falta —escribe el
guion, genera la voz, baja los clips a sus `parteN` y monta—. Explicarlo por
consola teniendo la herramienta a un clic era dejar el trabajo a medias. Al
cerrarla se vuelve a mirar la carpeta: si ya está completa el montaje sigue
sin preguntar nada, y si no, queda el bucle de consola de siempre.

Con una carpeta ya completa no se abre nada y se monta directo.

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

### Qué clips buscar

Al terminar el guion, `PEDIR_CLIPS` pide en la **misma conversación** las
búsquedas para ilustrarlo. En la misma a propósito: ahí Claude ya tiene el
guion entero delante, con sus cifras y sus rótulos, y no hay que volver a
contárselo.

Vuelven en un bloque `---CLIPS---` … `---FIN---` con una cabecera `PARTE N`
por sección. Es el mismo truco que el guion y por el mismo motivo: separar lo
que es dato de lo que es charla. `extraer_busquedas()` lo lee y `atajos()` ni
se entera, porque su marca lleva la palabra CLIPS y no GUION.

El lector es deliberadamente tolerante: acepta `INTRO Y PARTE 1` —que es como
las agrupa el usuario a mano—, quita viñetas, numeración y comillas, y si
Claude se dejó las marcas pero puso las cabeceras, lee igual. Perder la lista
entera por un delimitador ausente sería absurdo teniendo el contenido delante.

`guardar_busquedas()` las escribe **dentro de cada `parteN`**, nunca sueltas
en la raíz, y por dos razones:

- Práctica: el día que abras `parte3` para llenarla, la lista está ahí mismo.
- Técnica: en la raíz, cualquier `.txt` que no sea `trans` puede acabar
  tomándose por el guion (`cli.py`, autodetección). Dentro de `parteN` solo
  cuentan las extensiones de vídeo, así que un `.txt` es inofensivo.

Aun así, `busquedas` está excluido por nombre, porque el caso sin carpetas
`parteN` sí escribe en la raíz. Los nombres excluidos son **una sola lista**,
`proyecto.NO_SON_GUION`, y están juntos por escarmiento: cuando la lista
estaba copiada en cada sitio, `busquedas` se quedó sin poner en la detección
de `montador voz`, que es justo el sitio donde se habría narrado. Al añadir
otro archivo a la raíz, basta con meterlo ahí.

Si el guion tiene más partes que carpetas —cinco partes contra cuatro
`parteN`, que es lo normal hoy—, las que sobran se suman al final de la
última. Tenerlas de más en un sitio raro es mejor que perderlas.

Lo que se guarda y lo que se abre en el navegador sale de **lo que haya en la
pestaña**, no de lo que dijo Claude: las búsquedas se retocan, se prueba una,
no da nada y se cambia una palabra.

### Bajar los clips: el portapapeles manda

Era el último paso manual de punta a punta: buscar el vídeo, copiar el enlace,
clic derecho, guardar como, elegir la carpeta, y otra vez. `descargas.py` lo
deja en **copiar el enlace**.

La ventana vigila el portapapeles cada medio segundo. Eliges la `parteN` en un
desplegable, marcas la casilla, y a partir de ahí cada enlace de vídeo que
copias se baja solo a esa carpeta. Se **sondea** en vez de escuchar un evento
porque Windows no avisa del cambio de portapapeles a quien no se registra en
la cadena del sistema, y eso desde tkinter no se hace.

Se eligió esto sobre buscar y descargar en automático porque el usuario ya
revisa los vídeos a ojo y **eso le sirve**: los abre, ve cuál vale, y lo que
sobraba era la mecánica de guardarlo. Lo que se automatiza es lo mecánico, no
el criterio.

`es_enlace()` es el filtro, y su respuesta normal es **callar**: se le pasa
todo lo que cae en el portapapeles durante una tarde. Solo reacciona a lo que
sin duda es un vídeo —exige los once caracteres del identificador de YouTube,
así que un enlace de canal, de lista o de la página de resultados no cuela— y
normaliza a `watch?v=ID` pelado. Eso último hace dos cosas: **quita el
`&list=`**, que sin él se bajaría la lista entera, y deja iguales las seis
formas del mismo vídeo, que es lo que detecta el repetido.

**Los clips bajan mudos y en H.264.** Dos decisiones, cada una por su motivo:

- Sin audio (`bv*`, sin el `+ba`): la narración va por su lado, así que el
  sonido del clip no se usa nunca — y si viene, hay que silenciarlo a mano en
  CapCut clip por clip. De paso pesan menos de la mitad. Cuando YouTube solo
  ofrece el archivo ya mezclado, `_quitar_audio()` lo deja mudo copiando los
  flujos, sin recodificar.
- H.264 primero (`vcodec^=avc1`): pidiendo solo la mejor pista de vídeo,
  YouTube sirve **AV1 o VP9**, que CapCut mueve a tirones o no importa. Si no
  hay H.264 se coge lo que haya, antes que quedarse sin clip.

Por eso `_material_video()` declara `has_audio` mirando el archivo con
ffprobe y no fijo a `True` como antes: describirle a CapCut un material que
no es el que tiene delante no puede acabar bien.

Los archivos van numerados `01_`, `02_` porque `edl.py` lee cada `parteN` con
`sorted()`: **el nombre del archivo es lo que decide el orden de rotación**.
`siguiente_indice()` cuenta lo que ya hay en el disco en vez de llevar la
cuenta en memoria, para que los clips metidos a mano cuenten igual y para que
cerrar la ventana y volver no empiece otra vez por el uno.

Las descargas van **de una en una**. No es prudencia: con cuatro a la vez
ninguna termina, el ancho de banda es el mismo, y sobre todo el número del
archivo se calcula mirando la carpeta — dos simultáneas pedirían el mismo y
una pisaría a la otra.

No tocan el semáforo `trabajando`, a propósito: mientras baja un clip se sigue
hablando con Claude y, sobre todo, se siguen copiando enlaces, que es justo lo
que estás haciendo. Sí avisan al montar y al cerrar, porque montar con
descargas a medias sale con menos clips de los que vas a tener.

Antes de bajar se pregunta la duración (`datos()`, un segundo de coste). Del
vídeo se usan cuatro segundos y pico, así que uno de tres horas son varios
gigas para tirar casi enteros — y esos vídeos **salen en las búsquedas**: los
recopilatorios de paisajes duran eso. Se descubrió cayendo en ello: una
descarga de prueba llevaba 1,9 GB cuando se cortó. Pasada la media hora no se
descarta solo, se **pregunta**, porque un recopilatorio largo puede ser justo
el material que quieres; aceptarlo baja con el tope desactivado. Una duración
desconocida (`NA`, que es lo que dan los directos) cuenta como pasada: un
directo no tiene final y bajaría hasta llenar el disco.

**yt-dlp se llama por subproceso, no importando la librería.** Se actualiza
sola sin tocar el montador, y falta hace: YouTube cambia cada pocas semanas y
yt-dlp va detrás — una versión clavada en el código sería una descarga rota
cada dos meses. Además una descarga atascada se mata sin llevarse la ventana.
Se invoca como `<python> -m yt_dlp` y no como `yt-dlp` a secas para usar la
del mismo intérprete y no depender del PATH.

Es la única dependencia y es **opcional**: sin ella el resto funciona igual y
la ventana ofrece instalarla la primera vez que marcas la casilla. Que falte
no da `FileNotFoundError` invocándola así, sino un código de salida y un `No
module named`; se distingue porque ese fallo tiene arreglo de un clic y los
demás no. Actualizar es también la reparación: cuando las descargas fallan de
golpe habiendo funcionado ayer, casi siempre es que YouTube ha cambiado algo.

### Título y descripción

`PEDIR_PUBLICACION` pide ocho títulos y la descripción de YouTube, y también
en la misma conversación: el título sale del gancho del guion y la descripción
de lo que se cuenta dentro, con las fuentes que Claude ya consultó al
escribirlo. Vuelven en un bloque `---PUBLICACION---` … `---FIN---`.

Son ocho títulos y no uno porque el título se elige, no se acepta: el encargo
pide que sean distintos entre sí —uno con la cifra, otro con la pregunta, otro
con el nombre propio—, no ocho maneras de decir lo mismo.

**La descripción tiene una plantilla fija de secciones** y no es decoración:
sale de una descripción real que el usuario dio por buena (el vídeo del BYD
Seal 08), después de que una versión libre no le gustara. El orden es cuerpo
de cuatro o cinco párrafos sin encabezado, `📊 LOS DATOS DEL VÍDEO` con las
cifras una por línea, `⚠️ ACLARACIONES` con los matices que impiden leer mal
un dato —el precio es de otro mercado, la autonomía es de otro ciclo—,
`🔗 FUENTES`, la pregunta con `💬`, la suscripción con `🔔` y una línea de
hashtags. Las aclaraciones se quitan si no hay nada real que matizar, porque
rellenarlas por rellenar es justo lo contrario de para lo que están.

El nombre del canal **no está en el código**: el encargo le dice a Claude que
lo saque de las reglas del perfil, que ya las tiene delante. Codificar aquí
"Oriente Avanza" ataría el montador a un canal, y el reparto es el de siempre
—el perfil pone el estilo, el contrato solo el formato—.

Se le prohíbe el markdown explícitamente. YouTube no lo interpreta: unos
asteriscos de negrita salen como asteriscos en la descripción publicada.

`extraer_publicacion()` devuelve el bloque **como texto**, sin trocearlo en
títulos y descripción. Es lo que se pega en YouTube tal cual, y trocearlo solo
serviría para volver a juntarlo al guardar. Se guarda con
`guardar_publicacion()` en `publicacion.txt`, en la raíz de la carpeta: no
ilustra ninguna parte, es del vídeo entero. De ahí que su nombre esté en
`NO_SON_GUION`.

Lo que **no** lleva son los capítulos con minutajes, y el encargo se lo dice
con su motivo: Claude sabe el orden de las partes pero no en qué segundo entra
cada una, así que los inventaría, y un minutaje inventado manda al espectador
al sitio equivocado. Los pone el montador al montar, en `capitulos.txt`, que
es cuando ya existe el audio transcrito y se sabe el minutaje de verdad. Se
pegan debajo de la descripción.

### Montar sin salir de la ventana

El botón **"Montar en CapCut"** hace lo que antes había que teclear:
`python -m montador montar --clips <carpeta> --proyecto <nombre>`. Los dos
argumentos ya los sabe la ventana —la carpeta es en la que trabaja y el nombre
sale de `nombre_proyecto()`—, así que no pregunta nada.

Se lanza como **proceso aparte**, no llamando a `cmd_montar()` dentro de la
ventana, y no es por comodidad: Whisper tarda minutos y se lleva mucha
memoria, un fallo suyo se llevaría por delante la conversación entera, y las
líneas de avance que el CLI ya imprime se pintan en la charla sin inventar
otro mecanismo. El hilo lee `stdout` línea a línea y las mete en la misma cola
que usan la voz y las respuestas de Claude.

Antes de arrancar hace tres cosas, y las tres evitan un montaje tirado a la
basura: guarda el `guion.txt` si hay texto en la pestaña —el montaje lee el
archivo, no el widget, y los rótulos saldrían de una versión vieja—, pasa
`revisar()` y no sigue si faltan cosas, y comprueba con `tasklist` si CapCut
está abierto. Lo último es un aviso, no una comprobación fiable: si `tasklist`
falla se deja pasar, porque bloquear el montaje por no saber sería peor.

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

## Cruzar el guion con lo que se oye

`trans.json` sabe **cuándo** suena cada palabra; el guion sabe **qué** se dijo
y dónde van sus marcas. `alinear_guion()` los cruza, y de ahí salen tres cosas
que antes se estimaban a ojo: la posición real de cada rótulo, el segundo en
que entra cada `parteN`, y los capítulos de YouTube.

No son el mismo texto —Whisper se come palabras, escribe `35` donde el guion
pone `35%`, a veces oye otra cosa—, así que se alinean como **dos secuencias**
con `difflib`: se anclan los tramos que coinciden y se interpolan los huecos.
Palabra por palabra se desincronizaría en el primer fallo. Sin dependencias:
`difflib` y `unicodedata` son de la librería estándar.

Dos detalles que no son opcionales:

- **`autojunk=False`.** Con listas largas, `difflib` descarta como ruido los
  elementos que se repiten mucho, y en español eso es `de`, `la`, `que`:
  justo las que más anclan. Con autojunk puesto, la alineación se cae.
- **Se cuenta en palabras, no en caracteres.** El narrador leyó el guion sin
  las marcas y sin las líneas en blanco, así que las posiciones de carácter
  ya no valen; el orden de las palabras sí sobrevive.

`MapaGuion.fiabilidad` dice qué proporción salió de una coincidencia real.
Por debajo de `FIABILIDAD_MINIMA` (55 %) **no se usa** y se vuelve al reparto
por proporción de texto, que es lo que había. Con material real (vídeo
catorce) da 84 %; el `ejemplo/` sintético da 0 % —su transcripción son 428
letras `x`— y por eso el ejemplo no sirve para probar esto, solo el fallback.

### Las dos marcas del guion

`[TXT: ...]` es el rótulo. `[PARTE n: título]` dice dónde empieza cada parte.
Ninguna se locuta: `texto_narrado()` las quita, y es la única función que lo
hace —`voz.py` tira de ella— para que no se desincronicen dos limpiezas.

En la marca de parte manda **el número, no el orden de aparición**: `[PARTE 3]`
dice cuándo entra la carpeta `parte3`. Importa porque la primera marca del
guion suele ser `[PARTE 2]` —delante va la intro, que no lleva marca— y
tomarla por la primera carpeta correría todas las demás. La carpeta `parte1`
entra en cero pase lo que pase: durante la intro hay que enseñar algo.

Las partes del guion y las carpetas no tienen por qué coincidir (hoy son cinco
contra cuatro). Las carpetas sin marca se reparten en el hueco entre las dos
marcas que las rodean, y las entradas se fuerzan crecientes: una que
retrocediera sacaría clips de una parte que aún no ha empezado.

Un guion sin marcas de parte se monta como siempre. Los guiones de antes de
esto no las llevan y siguen funcionando.

### Los capítulos

Salen al **montar**, no cuando Claude escribe la descripción, y no es un
capricho de diseño: el minutaje no existe hasta que hay audio transcrito.
Se escriben en `capitulos.txt`, en la raíz de la carpeta, listos para pegar
debajo de la descripción. Sin títulos en las marcas no se genera nada: una
lista de "Parte 3" no le sirve a nadie.

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
- Los clips entran a escala 1:1, sin recorte ni zoom. Material que no sea
  1920×1080 sale con bandas.
- Subir a YouTube desde el montador: con `publicacion.txt` y `capitulos.txt`
  ya generados, lo que falta es la API y autorizar la cuenta una vez. Subir
  siempre en privado o programado, nunca público directo.
- La miniatura sigue siendo manual, y se queda asi: la API de imagenes de
  OpenAI se paga aparte de ChatGPT Plus y junior prefiere seguir generandolas
  en el navegador, que ya tiene pagado. Se intento (commit fcbcba7) y se
  retiro. Si algun dia se retoma: el sistema son tres capas -escena, el mismo
  personaje recortado siempre, y dos lineas de texto comparando cifras, la de
  arriba blanca y la de abajo amarilla- y el texto conviene componerlo en
  local, porque un modelo de imagen escribe mal las cifras cada pocas veces y
  estas miniaturas viven de ellas.

Resuelto y ya no está aquí: la posición de los rótulos y la entrada de las
partes, que se estimaban a ojo y ahora salen de cruzar el guion con la
transcripción (ver arriba).

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
  (y dos opcionales: `anthropic`, para el respaldo por API del guionista, y
  `yt-dlp`, para bajar los clips); el resto es librería estándar + FFmpeg y el
  CLI de Claude por subproceso.
- CapCut trabaja en **microsegundos**. Usar el helper `us()`.

## Estructura

    montador/
      config.py            el estilo, en números
      proyecto.py          carpeta de trabajo en MasterTube: preguntar nombre,
                           crear parte1..parteN, comprobar que está completa,
                           repartir las busquedas de clips por parteN,
                           guardar titulos y descripcion en publicacion.txt
                           y los capitulos en capitulos.txt
      guionista.py         guion negociado con Claude por turnos (Conversacion)
                           + modo de un tiron para perfiles sin pasos
      perfiles.py          reglas de guion del usuario (MasterTube\perfiles)
      ideas.py             de que hacer el proximo video: Claude busca en
                           internet, y se guarda lo ya hecho para no repetir
      ui_ideas.py          ventana de ideas, con sus reglas y sus estados
      voz.py               guion -> narracion.mp3 con la API de ai33.pro
      descargas.py         enlace copiado -> clip numerado dentro de parteN
                           (yt-dlp por subproceso; dependencia opcional)
      ui_proyecto.py       ventana de entrada: elegir el video o crear uno
                           nuevo con sus parteN, con lo que ya tiene hecho
      ui_guion.py          ventana (tkinter): chat con Claude, atajos, la
                           pestana Guion con lo locutable, la pestana Clips
                           con que buscar para cada parteN y el vigilante del
                           portapapeles que los baja, la pestana Publicacion
                           con los titulos y la descripcion, y el boton que
                           lanza el montaje en un proceso aparte
      alineacion.py        whisper -> palabras -> pausas, y el cruce del guion
                           con lo que se oye (+ registro de DLL de CUDA)
      edl.py               plan de cortes, rotacion de clips, transiciones,
                           sonidos, rotulos, capa de efecto
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

Sin `--clips`, `montar` y `guion` abren la ventana de proyecto y trabajan
dentro de `Escritorio\MasterTube` (se puede mover con la variable de entorno
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
