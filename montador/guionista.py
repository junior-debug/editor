"""
Generacion del guion con Claude.

Dos backends, igual que el EDL tiene dos salidas:

  cli  el ejecutable de Claude Code que el usuario ya tiene instalado y
       autenticado. Se invoca por subproceso, como ffmpeg. Sin API key ni
       dependencias nuevas: es el camino por defecto.
  api  el SDK oficial de Anthropic. Respaldo para cuando no haya CLI. Se
       importa dentro de la funcion, asi que solo hace falta instalarlo si
       de verdad se usa.

Y dos formas de escribir:

  Conversacion  el guion se negocia por turnos, que es como trabaja el
                usuario: Claude propone tres hooks, el elige, Claude sigue al
                paso siguiente, y asi hasta la ultima parte. Es lo que usa la
                ventana.
  generar()     de un tiron, sin preguntar nada. Sirve para perfiles que solo
                son reglas de estilo, sin mecanica por pasos.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

# ritmo de locucion en español; sirve para traducir minutos de video a
# palabras de guion. Subirlo hace guiones mas largos para la misma duracion.
PALABRAS_POR_MINUTO = 150

MODELO_API = "claude-opus-5"

# el CLI puede tardar bastante en una parte larga; mejor esperar que cortar
ESPERA_MAXIMA_S = 600

# Lo unico que se le deja tocar al CLI. Sin esto no busca: en modo -p no hay
# nadie que acepte el dialogo de permisos, asi que las llamadas se rechazan
# solas. Y se le abren estas dos y nada mas: no tiene por que leer ni escribir
# archivos en la carpeta del video.
HERRAMIENTAS_WEB = ["WebSearch", "WebFetch"]

# El permiso solo no basta. Con las herramientas concedidas pero sin encargo,
# Claude escribe de memoria igualmente. Esto no es estilo ni formato, asi que
# no va en ninguno de los dos contratos: va aparte, y solo con el backend del
# CLI, que es el unico que tiene herramientas.
INVESTIGAR = """\
Tienes búsqueda web y quiero que la uses antes de escribir. Comprueba las \
cifras, las fechas y los nombres propios que vayas a soltar, y si el tema \
sigue vivo busca el dato más reciente en vez de tirar de lo que recuerdes.

Las fuentes no se locutan: no las metas dentro del guion. Si te apetece \
citarlas, hazlo fuera, hablando conmigo. Y si un dato no has podido \
confirmarlo, dímelo en una línea aparte en vez de colarlo como si nada.
"""

# Marcas con las que Claude separa lo que se locuta de lo que nos dice a
# nosotros. Sin ellas no se puede conversar y armar el guion a la vez: las
# tres opciones de hook y los "¿seguimos?" acabarian dentro del mp3.
MARCA_INICIO = "---GUION---"
MARCA_FIN = "---FIN---"


# Lo que el montador necesita para poder leer el guion despues. No es estilo:
# es el formato de salida, y por eso se anade siempre, mande lo que mande el
# perfil. Las reglas del usuario deciden COMO se escribe; esto, en QUE forma
# sale.
CONTRATO_FORMATO = """\
Formato de la respuesta, por encima de cualquier otra indicación:
- Texto plano. Sin markdown: ni almohadillas, ni asteriscos, ni viñetas, ni \
títulos, ni negritas.
- Solo lo que se va a locutar. Sin indicaciones de cámara, sin notas de \
producción, sin encabezados de parte y sin numerar los bloques.
- Rótulos: marca entre uno y dos por parte escribiendo en su propia línea \
[TXT: TEXTO DEL RÓTULO], justo antes del párrafo que ilustran. Máximo seis \
palabras, en mayúsculas. Esa marca es la única sintaxis especial permitida.
"""

# El mismo contrato, pero para cuando hay conversacion de por medio. Aqui no
# se puede exigir "solo el texto del guion": las reglas del usuario piden
# justo lo contrario, que pregunte y espere. Asi que en vez de prohibirle
# hablar, se le pide que separe lo que habla de lo que se locuta.
CONTRATO_CONVERSACION = f"""\
Formato de tus respuestas, por encima de cualquier otra indicación:

- Estás hablando conmigo en una ventana, no entregando un documento. Puedes \
preguntarme, ofrecerme opciones y pararte a esperar mi respuesta: eso es \
exactamente lo que quiero de ti.
- Texto plano siempre. Sin markdown: ni almohadillas, ni asteriscos, ni \
negritas, ni viñetas.
- Todo lo que sea texto definitivo para locutar va envuelto entre estas dos \
marcas, cada una en su propia línea:

{MARCA_INICIO}
(aquí el texto tal y como se va a leer en voz alta)
{MARCA_FIN}

- Dentro de las marcas no va nada que no se lea en voz alta: ni encabezados \
de parte, ni números de párrafo, ni notas. Fuera van las opciones, las \
preguntas y todo lo que me digas a mí.
- Envuelve solo lo que ya es definitivo y va al guion final, en el orden en \
que se va a locutar. Lo que sea un borrador, una opción para que elija o un \
paso intermedio que luego vas a reescribir, déjalo fuera de las marcas.
- Si en una misma respuesta hay varias partes de guion, envuelve cada una en \
su propio bloque.
- Rótulos: entre uno y dos por bloque, en su propia línea dentro del bloque, \
escritos [TXT: TEXTO DEL RÓTULO], máximo seis palabras y en mayúsculas.
- Cuando empieces una parte nueva, abre el bloque con su marca en una línea \
suelta: [PARTE 2: El muro arancelario]. El número es el de la parte y el \
título es corto, de tres a cinco palabras, como para un capítulo de YouTube. \
La intro no lleva marca. Con ella sé en qué segundo entra cada parte, así que \
va donde de verdad empieza, delante de su primer párrafo.

Esas dos, [TXT: ...] y [PARTE n: ...], son la única sintaxis especial \
permitida dentro del guion, y ninguna de las dos se lee en voz alta.
"""

# Lo que se le pide al terminar el guion: que diga que buscar para ilustrarlo.
# Va en la misma conversacion a proposito — ahi tiene el guion entero delante,
# con sus cifras y sus rotulos, y no hay que volver a contarselo.
PEDIR_CLIPS = """\
Ya está el guion. Ahora dime qué vídeos busco para ilustrarlo.

Para cada parte, entre seis y diez búsquedas: lo que yo escribiría tal cual \
en el buscador para encontrar el plano. No me describas lo que se ve —"plano \
aéreo de un cohete" no me sirve—, dame la búsqueda: nombres propios, siglas, \
el término en el idioma del país cuando ayude a encontrar el material \
original, y el año si es de una fecha concreta.

Ordena cada parte de lo más específico a lo más genérico: primero lo que \
solo vale para este vídeo, y al final dos o tres de relleno que sirvan para \
cualquier plano de apoyo de esa parte.

Devuélvelo en un bloque con esta forma exacta:

---CLIPS---
PARTE 1
la primera búsqueda
la segunda búsqueda

PARTE 2
la primera búsqueda de la parte 2
---FIN---

Dentro del bloque, una búsqueda por línea y nada más: sin numerar, sin \
guiones delante, sin comillas y sin explicar para qué sirve cada una. Fuera \
del bloque dime lo que quieras.
"""

# Lo que se pide para publicar. Tambien en la misma conversacion, y por lo
# mismo: el titulo sale del gancho del guion y la descripcion de lo que se
# cuenta dentro, incluidas las fuentes que ya consulto al escribirlo.
PEDIR_PUBLICACION = """\
Ya está el guion. Ahora dame con qué lo publico en YouTube.

Ocho títulos. Ocho distintos entre sí, no ocho maneras de decir lo mismo: \
alguno con la cifra que más impresiona, alguno con la pregunta que el vídeo \
responde, alguno con el nombre propio por delante. Que quepan en el móvil sin \
cortarse, así que unos 60 caracteres, y sin mayúsculas gritadas ni signos de \
exclamación. Nada de prometer lo que el guion no cuenta.

Y la descripción, con estas secciones y en este orden:

**El cuerpo**, cuatro o cinco párrafos, sin ningún encabezado delante. El \
primero abre con la comparación o la cifra que sostiene el vídeo, concreta y \
con su número. El segundo cuenta qué es exactamente aquello de lo que se \
habla, con fechas y datos. El tercero dice cuál es el problema de fondo. El \
cuarto da el contexto que lo explica, otra vez con cifras. Y se cierra con \
una sola línea del tipo "Este vídeo explica por qué...". Los dos primeros \
renglones son lo único que se ve sin desplegar: que enganchen solos y que no \
repitan el título palabra por palabra.

**📊 LOS DATOS DEL VÍDEO** — las cifras del guion, una por línea, con la \
etiqueta delante y dos puntos. Sin viñetas ni guiones.

**⚠️ ACLARACIONES** — los matices que impiden que un dato se lea mal: que un \
precio sea de otro mercado, que una autonomía se mida en otro ciclo, que una \
cifra sea del fabricante y no independiente. Pon en el encabezado cuántas son \
("UNA ACLARACIÓN IMPORTANTE", "DOS ACLARACIONES IMPORTANTES"). Si de verdad \
no hay nada que matizar, quita la sección entera; no la rellenes por rellenar.

**🔗 FUENTES** — las que consultaste al escribir el guion, una por línea, con \
el medio delante y lo que aporta detrás separado por una raya.

**💬** — una pregunta que se pueda contestar en un comentario, sacada de la \
tensión del vídeo, y "Te leo en los comentarios."

**🔔** — una línea invitando a suscribirse al canal, con su nombre y su \
temática tal como los conoces por las reglas de arriba.

**#hashtags** — de ocho a diez, en una sola línea, mezclando el nombre propio \
del que va el vídeo, el tema, y el del canal al final.

Dos cosas que importan para todo el bloque:

- **Nada de markdown.** YouTube no lo interpreta: los asteriscos salen como \
asteriscos. Sin negritas, sin cursivas y sin viñetas. Los emoji de los \
encabezados sí van, tal cual los he escrito.
- **Sin capítulos con minutajes.** Sabes el orden de las partes pero no en \
qué segundo entra cada una, y unos minutajes inventados mandan al espectador \
al sitio equivocado. Esa sección se añade después, fuera de aquí.

Devuélvelo en un bloque con esta forma exacta:

---PUBLICACION---
TITULOS
el primer titular
el segundo titular

DESCRIPCION
los párrafos del cuerpo

📊 LOS DATOS DEL VÍDEO

Etiqueta: el dato

⚠️ DOS ACLARACIONES IMPORTANTES
el matiz

🔗 FUENTES
Medio — qué aporta

💬 la pregunta Te leo en los comentarios.

🔔 la línea de suscripción

#unos #cuantos #hashtags
---FIN---

Las dos cabeceras, TITULOS y DESCRIPCION, van tal cual y en su propia línea. \
Los títulos, uno por línea y sin numerar. Fuera del bloque dime lo que \
quieras.
"""

# Reglas de estilo usadas cuando no se pasa ningun perfil. El sitio donde el
# usuario las mantiene es MasterTube\\perfiles; ver perfiles.py.
ESTILO_POR_DEFECTO = """\
Escribes el guion de un vídeo del canal de YouTube "Oriente Avanza", en \
español de España. El canal trata tecnología, megaestructuras y geopolítica \
entre Asia y Occidente.

Cómo escribe el canal:
- Es locución para voz en off, no un artículo. Frases cortas, en presente, \
que se puedan leer en voz alta del tirón. Nada de incisos largos.
- Empieza con un dato concreto que enganche, nunca con "en este vídeo vamos \
a ver" ni presentaciones del canal.
- Datos verificables y concretos: cifras, fechas, nombres propios, lugares. \
Si no estás seguro de un dato, escribe el hecho sin la cifra antes que \
inventarla.
- Sin saludos, sin despedidas, sin "suscríbete".
"""


class SinBackend(RuntimeError):
    """Ni CLI de Claude ni API key: no hay forma de generar el guion."""


# --------------------------------------------------------------------------
# Backends
# --------------------------------------------------------------------------

def ruta_cli() -> str | None:
    return shutil.which("claude")


def hay_api() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def detectar_backend() -> str:
    if ruta_cli():
        return "cli"
    if hay_api():
        return "api"
    raise SinBackend(
        "No encuentro como hablar con Claude.\n"
        "  - Opcion 1: instala Claude Code (el comando 'claude').\n"
        "  - Opcion 2: define ANTHROPIC_API_KEY e instala el SDK "
        "con 'pip install anthropic'.")


def _lanzar_cli(prompt: str, trabajo: Path | None,
                sesion: str = "") -> tuple[str, str]:
    """
    Lanza 'claude -p' y devuelve (texto, id_de_sesion).

    Se ejecuta dentro de la carpeta del video a proposito: si corriera en la
    del montador, Claude Code cargaria el CLAUDE.md del proyecto y escribiria
    el guion con ese contexto encima.

    Con 'sesion' se continua la conversacion anterior en vez de empezar una
    nueva. Es lo que hace posible el trabajo por turnos: Claude recuerda los
    hooks que propuso y las partes que ya escribio sin que haya que
    reenviarselos, y el turno siguiente se sirve de cache.

    La salida se pide en JSON y no en texto porque es de donde sale el id de
    sesion; de paso trae el aviso de error explicito.
    """
    orden = [ruta_cli(), "-p", prompt, "--output-format", "json"]
    if HERRAMIENTAS_WEB:
        orden += ["--allowedTools", *HERRAMIENTAS_WEB]
    if sesion:
        orden += ["--resume", sesion]

    salida = subprocess.run(
        orden, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=ESPERA_MAXIMA_S,
        cwd=str(trabajo) if trabajo else None)

    if salida.returncode != 0:
        detalle = (salida.stderr or salida.stdout or "").strip()
        raise RuntimeError(f"El CLI de Claude ha fallado:\n{detalle[:800]}")

    try:
        datos = json.loads(salida.stdout or "{}")
    except json.JSONDecodeError:
        # si algun dia deja de devolver JSON, al menos no se pierde el texto
        texto = (salida.stdout or "").strip()
        if not texto:
            raise RuntimeError("El CLI de Claude no ha devuelto nada.")
        return texto, sesion

    if datos.get("is_error"):
        raise RuntimeError(
            "El CLI de Claude ha fallado: "
            + str(datos.get("result") or datos)[:800])

    texto = (datos.get("result") or "").strip()
    if not texto:
        raise RuntimeError("El CLI de Claude no ha devuelto nada.")
    return texto, datos.get("session_id") or sesion


def _pedir_cli(prompt: str, trabajo: Path | None) -> str:
    return _lanzar_cli(prompt, trabajo)[0]


def _lanzar_api(mensajes: list[dict]) -> str:
    try:
        import anthropic
    except ModuleNotFoundError:
        raise RuntimeError(
            "El respaldo por API necesita el SDK: pip install anthropic")

    cliente = anthropic.Anthropic()
    comun = dict(model=MODELO_API, max_tokens=64000, messages=mensajes)

    try:
        # el respaldo de servidor reintenta en otro modelo si este declina;
        # si la beta deja de existir, se pide igual sin ella
        with cliente.beta.messages.stream(
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default", **comun) as flujo:
            mensaje = flujo.get_final_message()
    except anthropic.BadRequestError:
        with cliente.messages.stream(**comun) as flujo:
            mensaje = flujo.get_final_message()

    if mensaje.stop_reason == "refusal":
        raise RuntimeError("Claude ha declinado escribir este guion.")

    return "".join(b.text for b in mensaje.content if b.type == "text").strip()


def _pedir_api(prompt: str) -> str:
    return _lanzar_api([{"role": "user", "content": prompt}])


def pedir(prompt: str, backend: str = "", trabajo: Path | None = None) -> str:
    backend = backend or detectar_backend()
    if backend == "cli":
        return _pedir_cli(prompt, trabajo)
    if backend == "api":
        return _pedir_api(prompt)
    raise RuntimeError(f"Backend desconocido: {backend}")


# --------------------------------------------------------------------------
# Conversacion
# --------------------------------------------------------------------------

class Conversacion:
    """
    El guion negociado por turnos.

    Las reglas del perfil y el contrato de formato van en el primer mensaje,
    no en un system prompt: es lo que ya estaba comprobado que funciona con el
    CLI, y del segundo turno en adelante Claude las sigue teniendo delante
    porque la sesion entera se conserva.
    """

    def __init__(self, reglas: str = "", backend: str = "",
                 trabajo: Path | None = None):
        self.reglas = reglas.strip() or ESTILO_POR_DEFECTO
        self.backend = backend or detectar_backend()
        self.trabajo = trabajo
        self.sesion = ""                 # id del CLI; vacio hasta el 1er turno
        self.mensajes: list[dict] = []   # historial; solo lo usa el backend api
        self.turnos = 0

    def _primer_mensaje(self, tema: str) -> str:
        # el contrato va detras de las reglas del usuario, no delante: lo
        # ultimo que se lee es lo que mejor se respeta, y el formato no es
        # negociable
        capas = [self.reglas]
        if self.backend == "cli":
            # el respaldo por API no lleva herramientas: alli el encargo
            # seria pedirle algo que no puede hacer
            capas.append(INVESTIGAR)
        capas += [CONTRATO_CONVERSACION,
                  f"Tema del vídeo:\n{tema.strip()}"]
        return "\n\n".join(capas)

    def enviar(self, texto: str) -> str:
        """Manda un turno y devuelve la respuesta cruda, con sus marcas."""
        texto = texto.strip()
        if not texto:
            raise RuntimeError("No hay nada que mandar.")

        envio = texto if self.turnos else self._primer_mensaje(texto)

        if self.backend == "cli":
            respuesta, self.sesion = _lanzar_cli(
                envio, self.trabajo, self.sesion)
        elif self.backend == "api":
            self.mensajes.append({"role": "user", "content": envio})
            respuesta = _lanzar_api(self.mensajes)
            self.mensajes.append({"role": "assistant", "content": respuesta})
        else:
            raise RuntimeError(f"Backend desconocido: {self.backend}")

        self.turnos += 1
        return respuesta


# --------------------------------------------------------------------------
# Lectura de la respuesta
# --------------------------------------------------------------------------

# tolerante con el numero de guiones y con los espacios sueltos: la marca la
# escribe un modelo, no un generador, y no merece la pena perder una parte
# entera por un guion de mas
_RE_BLOQUE = re.compile(
    r"^[ \t]*-{2,}[ \t]*GUION[ \t]*-{2,}[ \t]*$(.*?)"
    r"^[ \t]*-{2,}[ \t]*FIN[ \t]*-{2,}[ \t]*$",
    re.S | re.M | re.I)

_RE_ABRE = re.compile(r"^[ \t]*-{2,}[ \t]*GUION[ \t]*-{2,}[ \t]*$",
                      re.M | re.I)
_RE_CIERRA = re.compile(r"^[ \t]*-{2,}[ \t]*FIN[ \t]*-{2,}[ \t]*$",
                        re.M | re.I)


def extraer_guion(respuesta: str) -> tuple[list[str], str]:
    """
    Separa la respuesta en (bloques de guion, lo que Claude nos dice).

    Un bloque abierto y sin cerrar se da por bueno hasta el final: pasa cuando
    la respuesta se corta, y perder una parte entera por una marca que falta
    seria peor que quedarsela.
    """
    bloques = [b.strip() for b in _RE_BLOQUE.findall(respuesta)]
    charla = _RE_BLOQUE.sub("\n", respuesta)

    abierto = _RE_ABRE.search(charla)
    if abierto and not _RE_CIERRA.search(charla[abierto.end():]):
        resto = charla[abierto.end():].strip()
        if resto:
            bloques.append(resto)
        charla = charla[:abierto.start()]

    # las marcas que hayan quedado descolgadas no pintan nada en la charla
    charla = _RE_ABRE.sub("", _RE_CIERRA.sub("", charla))
    return [b for b in bloques if b], charla.strip()


# Las opciones vienen etiquetadas de mil formas: "A) ...", "OPCIÓN 2 — ...",
# "VERSIÓN 1 · ...". Lo unico estable es la letra o el numero al principio de
# la linea, con una etiqueta en mayusculas opcional delante. Sin re.I a
# proposito: la etiqueta tiene que ir en mayusculas para no confundir un
# "Párrafo 1 — ..." con una opcion.
_RE_CLIPS = re.compile(
    r"^[ \t]*-{2,}[ \t]*CLIPS[ \t]*-{2,}[ \t]*$(.*?)"
    r"^[ \t]*-{2,}[ \t]*FIN[ \t]*-{2,}[ \t]*$",
    re.S | re.M | re.I)

# "PARTE 1", "Parte 2:", y tambien "INTRO Y PARTE 1", que es como las agrupa
# el usuario a mano cuando la intro va pegada a la primera parte
_RE_CABECERA = re.compile(
    r"^[ \t]*(?:INTRO[ \t]*(?:Y|\+|/|,)?[ \t]*)?PARTE[ \t]*(\d{1,2})"
    r"[ \t]*:?[ \t]*$",
    re.M | re.I)


def leer_busquedas(texto: str) -> dict[int, list[str]]:
    """
    Convierte "PARTE 1 / busqueda / busqueda / PARTE 2 / ..." en un diccionario.

    Lee el texto plano, sin marcas, para poder aplicarse tambien a lo que el
    usuario haya retocado a mano en la ventana.
    """
    cabeceras = list(_RE_CABECERA.finditer(texto))
    if not cabeceras:
        return {}

    busquedas: dict[int, list[str]] = {}
    for i, cab in enumerate(cabeceras):
        fin = cabeceras[i + 1].start() if i + 1 < len(cabeceras) else len(texto)
        numero = int(cab.group(1))
        lineas = []
        for linea in texto[cab.end():fin].splitlines():
            # se limpian las viñetas y la numeracion por si las cuela igual
            linea = linea.strip().lstrip("-•*").strip()
            linea = re.sub(r"^\d{1,2}[\.\)]\s*", "", linea).strip(' "\'')
            if linea:
                lineas.append(linea)
        if lineas:
            busquedas.setdefault(numero, []).extend(lineas)
    return busquedas


def extraer_busquedas(respuesta: str) -> tuple[dict[int, list[str]], str]:
    """
    Separa la respuesta en (busquedas por parte, lo que Claude nos dice).

    Si se olvido las marcas pero puso las cabeceras, se lee igual: perder la
    lista entera por un delimitador que falta seria absurdo cuando el
    contenido esta ahi delante.
    """
    encontrado = _RE_CLIPS.search(respuesta)
    if encontrado:
        return (leer_busquedas(encontrado.group(1)),
                _RE_CLIPS.sub("\n", respuesta).strip())

    sueltas = leer_busquedas(respuesta)
    return (sueltas, "" if sueltas else respuesta)


_RE_PUBLICACION = re.compile(
    r"^[ \t]*-{2,}[ \t]*PUBLICACI[OÓ]N[ \t]*-{2,}[ \t]*$(.*?)"
    r"^[ \t]*-{2,}[ \t]*FIN[ \t]*-{2,}[ \t]*$",
    re.S | re.M | re.I)

# Sin cerrar: una descripcion larga es justo lo que se corta a mitad
_RE_ABRE_PUBLICACION = re.compile(
    r"^[ \t]*-{2,}[ \t]*PUBLICACI[OÓ]N[ \t]*-{2,}[ \t]*$", re.M | re.I)


def extraer_publicacion(respuesta: str) -> tuple[str, str]:
    """
    Separa la respuesta en (titulos y descripcion, lo que Claude nos dice).

    Vuelve como texto y no troceado en titulos y descripcion a proposito: es
    lo que se pega en YouTube tal cual, y trocearlo aqui solo serviria para
    volver a juntarlo al guardar.
    """
    encontrado = _RE_PUBLICACION.search(respuesta)
    if encontrado:
        return (encontrado.group(1).strip(),
                _RE_PUBLICACION.sub("\n", respuesta).strip())

    # igual que con el guion: un bloque abierto y sin cerrar se da por bueno
    # hasta el final antes que perder la descripcion entera
    abierto = _RE_ABRE_PUBLICACION.search(respuesta)
    if abierto:
        return (respuesta[abierto.end():].strip(),
                respuesta[:abierto.start()].strip())

    return "", respuesta


_RE_OPCION = re.compile(
    r"^[ \t]*(?:(?:[Oo]pci[oó]n|[Vv]ersi[oó]n|[A-ZÁÉÍÓÚÑ]{4,})[ \t]+)?"
    r"([A-Ca-c1-9])[ \t]*(?:[\)\.\:\-–—·]|\()",
    re.M)

_RE_PARTE = re.compile(r"\bparte[ \t]*(\d{1,2})", re.I)


def atajos(charla: str) -> list[tuple[str, str]]:
    """
    Botones que responden por ti lo de siempre: (etiqueta, texto que manda).

    Se deduce de lo que Claude acaba de decir, no de las reglas del perfil:
    asi la ventana no tiene que saber que existen "5 pasos" ni "5 partes", y
    sigue sirviendo si el usuario reescribe sus reglas manana.
    """
    if not charla.strip():
        return []

    botones: list[tuple[str, str]] = []

    # 1. opciones etiquetadas para elegir: "A) ...", "OPCIÓN 2 — ..."
    vistas: list[str] = []
    for etiqueta in _RE_OPCION.findall(charla):
        etiqueta = etiqueta.upper()
        if etiqueta not in vistas:
            vistas.append(etiqueta)

    # Letras y numeros no se mezclan: si aparecen los dos es que uno de los
    # dos es ruido, casi siempre un encabezado tipo "PASO 1" colado entre las
    # opciones de verdad. Gana el grupo mas numeroso.
    letras = [v for v in vistas if v.isalpha()]
    numeros = [v for v in vistas if v.isdigit()]
    elegidas = letras if len(letras) >= len(numeros) else numeros

    if len(elegidas) >= 2:
        for etiqueta in elegidas[:6]:
            botones.append((etiqueta, f"La {etiqueta}."))
        botones.append(("Otra vuelta",
                        "No me convencen. Dame otras opciones distintas."))
        return botones

    # 2. la pregunta final menciona una parte: "¿Arrancamos con la Parte 1?"
    preguntas = [l for l in charla.splitlines() if "?" in l]
    for linea in reversed(preguntas):
        encontrada = _RE_PARTE.search(linea)
        if encontrada:
            numero = encontrada.group(1)
            botones.append((f"Parte {numero}", f"Parte {numero}."))
            break

    # 3. cualquier otra pregunta abierta: basta con decirle que siga
    if not botones and preguntas:
        botones.append(("Adelante", "Adelante, sigue."))

    return botones


# --------------------------------------------------------------------------
# Prompts del modo de un tiron
# --------------------------------------------------------------------------

def _prompt_parte(tema: str, palabras: int, parte: int, total: int,
                  previas: list[str], reglas: str = "",
                  investigar: bool = False) -> str:
    # el contrato va detras de las reglas del usuario, no delante: lo ultimo
    # que se lee es lo que mejor se respeta, y el formato no es negociable
    partes = [reglas.strip() or ESTILO_POR_DEFECTO, ""]
    if investigar:
        partes += [INVESTIGAR, ""]
    partes += [CONTRATO_FORMATO, "",
               f"Tema del vídeo:\n{tema.strip()}", ""]

    if previas:
        escrito = "\n\n".join(previas)
        partes += [
            "Esto es lo que ya llevas escrito del guion:",
            "-----",
            escrito,
            "-----",
            "",
            f"Continúa desde ahí. Escribe la parte {parte} de {total}: "
            "enlaza con la frase anterior, no repitas datos ya dados y no "
            "resumas lo dicho.",
        ]
    else:
        partes.append(
            f"Escribe la parte 1 de {total} del guion: la apertura.")

    if parte == total:
        partes.append(
            "Es la última parte: cierra el tema con una idea de futuro "
            "concreta, sin despedirte del espectador.")

    partes += [
        "",
        f"Extensión: unas {palabras} palabras. Devuelve solamente el texto "
        "del guion, sin comentarios tuyos ni explicaciones de lo que has "
        "hecho.",
    ]
    return "\n".join(partes)


# --------------------------------------------------------------------------
# Generacion de un tiron
# --------------------------------------------------------------------------

def generar(tema: str, minutos: float, partes: int = 4, backend: str = "",
            trabajo: Path | None = None, avance=None,
            reglas: str = "") -> list[str]:
    """
    Devuelve la lista de partes del guion, ya escritas, sin preguntar nada.

    Es el modo antiguo, para perfiles que solo son reglas de estilo. Si el
    perfil trae mecanica por pasos —opciones que elegir, partes que pedir—
    lo que hace falta es Conversacion, no esto.

    'reglas' son las instrucciones de estilo del perfil elegido; vacio usa las
    de por defecto. 'avance' se llama como avance(numero, total, texto) segun
    van saliendo, para que quien llame pueda ir mostrandolas en vez de
    quedarse mudo varios minutos.
    """
    if not tema.strip():
        raise RuntimeError("Falta el tema del video.")

    backend = backend or detectar_backend()
    por_parte = max(120, int(minutos * PALABRAS_POR_MINUTO / max(partes, 1)))

    escritas: list[str] = []
    for i in range(1, partes + 1):
        texto = pedir(
            _prompt_parte(tema, por_parte, i, partes, escritas, reglas,
                          investigar=backend == "cli"),
            backend=backend, trabajo=trabajo)
        escritas.append(texto)
        if avance:
            avance(i, partes, texto)
    return escritas


def texto_busquedas(busquedas: dict[int, list[str]]) -> str:
    """Las busquedas otra vez en texto, tal y como se leen y se guardan."""
    trozos = []
    for numero in sorted(busquedas):
        trozos.append(f"PARTE {numero}\n" + "\n".join(busquedas[numero]))
    return "\n\n".join(trozos)


def unir(partes: list[str]) -> str:
    return "\n\n".join(p.strip() for p in partes if p.strip()) + "\n"


def guardar(carpeta: Path, texto: str, nombre: str = "guion.txt") -> Path:
    """
    Escribe el guion en la carpeta del video.

    Si ya habia uno distinto se conserva como guion_anterior.txt: sobrescribir
    sin mas el trabajo de una tarde seria una forma tonta de perderlo.
    """
    destino = Path(carpeta) / nombre
    if destino.exists():
        previo = destino.read_text(encoding="utf-8")
        if previo.strip() and previo != texto:
            copia = destino.with_name(destino.stem + "_anterior.txt")
            copia.write_text(previo, encoding="utf-8")

    destino.write_text(texto, encoding="utf-8")
    return destino
