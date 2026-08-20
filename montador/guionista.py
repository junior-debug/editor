"""
Generacion del guion con Claude.

Dos backends, igual que el EDL tiene dos salidas:

  cli  el ejecutable de Claude Code que el usuario ya tiene instalado y
       autenticado. Se invoca por subproceso, como ffmpeg. Sin API key ni
       dependencias nuevas: es el camino por defecto.
  api  el SDK oficial de Anthropic. Respaldo para cuando no haya CLI. Se
       importa dentro de la funcion, asi que solo hace falta instalarlo si
       de verdad se usa.

El guion se escribe por partes seguidas, no de una tirada: cada parte ve las
anteriores enteras, que es como mantiene el hilo sin repetirse.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

# ritmo de locucion en español; sirve para traducir minutos de video a
# palabras de guion. Subirlo hace guiones mas largos para la misma duracion.
PALABRAS_POR_MINUTO = 150

MODELO_API = "claude-opus-5"

# el CLI puede tardar bastante en una parte larga; mejor esperar que cortar
ESPERA_MAXIMA_S = 600


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


def _pedir_cli(prompt: str, trabajo: Path | None) -> str:
    """
    Lanza 'claude -p' y devuelve el texto.

    Se ejecuta dentro de la carpeta del video a proposito: si corriera en la
    del montador, Claude Code cargaria el CLAUDE.md del proyecto y escribiria
    el guion con ese contexto encima.
    """
    orden = [ruta_cli(), "-p", prompt, "--output-format", "text"]
    salida = subprocess.run(
        orden, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=ESPERA_MAXIMA_S,
        cwd=str(trabajo) if trabajo else None)

    if salida.returncode != 0:
        detalle = (salida.stderr or salida.stdout or "").strip()
        raise RuntimeError(f"El CLI de Claude ha fallado:\n{detalle[:800]}")

    texto = (salida.stdout or "").strip()
    if not texto:
        raise RuntimeError("El CLI de Claude no ha devuelto nada.")
    return texto


def _pedir_api(prompt: str) -> str:
    try:
        import anthropic
    except ModuleNotFoundError:
        raise RuntimeError(
            "El respaldo por API necesita el SDK: pip install anthropic")

    cliente = anthropic.Anthropic()
    comun = dict(model=MODELO_API, max_tokens=64000,
                 messages=[{"role": "user", "content": prompt}])

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


def pedir(prompt: str, backend: str = "", trabajo: Path | None = None) -> str:
    backend = backend or detectar_backend()
    if backend == "cli":
        return _pedir_cli(prompt, trabajo)
    if backend == "api":
        return _pedir_api(prompt)
    raise RuntimeError(f"Backend desconocido: {backend}")


# --------------------------------------------------------------------------
# Prompts
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
# Generacion
# --------------------------------------------------------------------------

def generar(tema: str, minutos: float, partes: int = 4, backend: str = "",
            trabajo: Path | None = None, avance=None,
            reglas: str = "") -> list[str]:
    """
    Devuelve la lista de partes del guion, ya escritas.

    'reglas' son las instrucciones de estilo del perfil elegido; vacio usa las
    de por defecto. 'avance' se llama como avance(numero, total, texto) segun
    van saliendo, para que la ventana pueda ir mostrandolas en vez de quedarse
    muda varios minutos.
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
