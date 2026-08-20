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
escritos [TXT: TEXTO DEL RÓTULO], máximo seis palabras y en mayúsculas. Es \
la única sintaxis especial permitida dentro del guion.
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
        return "\n\n".join([
            self.reglas,
            CONTRATO_CONVERSACION,
            f"Tema del vídeo:\n{tema.strip()}",
        ])

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
                  previas: list[str], reglas: str = "") -> str:
    # el contrato va detras de las reglas del usuario, no delante: lo ultimo
    # que se lee es lo que mejor se respeta, y el formato no es negociable
    partes = [reglas.strip() or ESTILO_POR_DEFECTO, "", CONTRATO_FORMATO, "",
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
            _prompt_parte(tema, por_parte, i, partes, escritas, reglas),
            backend=backend, trabajo=trabajo)
        escritas.append(texto)
        if avance:
            avance(i, partes, texto)
    return escritas


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
