"""
Narracion con la API de ai33.pro (OpenSpeaker).

El flujo es asincrono, como el resto de sus APIs de generacion:

    POST /v3/text-to-speech   (multipart)  -> {success, task_id}
    GET  /v1/task/{task_id}                -> status doing -> done
    y al terminar, metadata.audio_url con el mp3

Se habla con urllib de la libreria estandar: una peticion multipart y un
sondeo no justifican una dependencia nueva.

La clave NO va en el codigo: se lee de MasterTube\\ai33.key o de la variable
de entorno AI33_API_KEY. El repositorio es git y una clave dentro de un commit
no se borra facilmente.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from . import proyecto as proy
from .edl import MARCA_TXT

BASE = "https://api.ai33.pro"

# Narrador v2 (fishaudio), la voz del canal. Se puede cambiar por --voz con
# cualquier id de GET /v3/voices?provider=...
VOZ_POR_DEFECTO = "fishaudio_35199d5438854f5d9157c500479ab684"
NOMBRE_VOZ = "Narrador v2"
VELOCIDAD_POR_DEFECTO = 1.0

ARCHIVO_CLAVE = "ai33.key"

# la API admite hasta 1.000.000 de caracteres por peticion, asi que un guion
# entero entra de una vez y no hay que trocear ni concatenar con ffmpeg
LIMITE_CARACTERES = 1_000_000

SONDEO_S = 3
ESPERA_MAXIMA_S = 900

NAVEGADOR = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


class SinClave(RuntimeError):
    pass


# --------------------------------------------------------------------------
# Credenciales
# --------------------------------------------------------------------------

def ruta_clave() -> Path:
    return proy.raiz() / ARCHIVO_CLAVE


def clave() -> str:
    manual = os.environ.get("AI33_API_KEY")
    if manual:
        return manual.strip()

    ruta = ruta_clave()
    if ruta.exists():
        texto = ruta.read_text(encoding="utf-8").strip()
        if texto:
            return texto

    raise SinClave(
        f"No encuentro la clave de ai33.pro.\n"
        f"  Pegala en {ruta}\n"
        f"  o define la variable de entorno AI33_API_KEY.")


# --------------------------------------------------------------------------
# Peticiones
# --------------------------------------------------------------------------

def _multipart(campos: dict) -> tuple[bytes, str]:
    """La API v3 espera FormData, no JSON."""
    limite = "----montador" + uuid.uuid4().hex
    partes = []
    for nombre, valor in campos.items():
        partes.append(
            f"--{limite}\r\n"
            f'Content-Disposition: form-data; name="{nombre}"\r\n\r\n'
            f"{valor}\r\n")
    partes.append(f"--{limite}--\r\n")
    cuerpo = "".join(partes).encode("utf-8")
    return cuerpo, f"multipart/form-data; boundary={limite}"


def _peticion(ruta: str, campos: dict | None = None, metodo: str = "GET",
              reintentos: int = 3) -> dict:
    cuerpo, tipo = (_multipart(campos) if campos else (None, ""))
    peticion = urllib.request.Request(BASE + ruta, data=cuerpo, method=metodo)
    peticion.add_header("xi-api-key", clave())
    if tipo:
        peticion.add_header("Content-Type", tipo)

    try:
        with urllib.request.urlopen(peticion, timeout=120) as respuesta:
            return json.loads(respuesta.read().decode("utf-8"))

    except urllib.error.HTTPError as exc:
        detalle = exc.read().decode("utf-8", "replace")

        # 429 y 503 son temporales: la propia API pide reintentar
        if exc.code in (429, 503) and reintentos > 0:
            espera = int(exc.headers.get("Retry-After") or 5)
            time.sleep(espera)
            return _peticion(ruta, campos, metodo, reintentos - 1)

        raise RuntimeError(_mensaje_error(exc.code, detalle))

    except urllib.error.URLError as exc:
        raise RuntimeError(f"No se ha podido conectar con ai33.pro: {exc.reason}")


def _mensaje_error(codigo: int, detalle: str) -> str:
    try:
        datos = json.loads(detalle)
        texto = datos.get("message") or detalle
    except ValueError:
        texto = detalle[:300]

    if codigo == 401:
        return f"ai33.pro rechaza la clave, o no quedan creditos: {texto}"
    return f"ai33.pro ha devuelto {codigo}: {texto}"


def creditos() -> int:
    return int(_peticion("/v1/credits").get("credits", 0))


# --------------------------------------------------------------------------
# Texto
# --------------------------------------------------------------------------

def texto_locutable(guion: str) -> str:
    """
    Quita las marcas [TXT: ...] del guion.

    Son indicaciones de rotulo para el montador, no texto para leer: si se
    mandan tal cual, el narrador dice "TXT dos puntos" en mitad de la frase.
    """
    limpio = MARCA_TXT.sub("", guion)
    lineas = [l.strip() for l in limpio.splitlines()]
    return "\n".join(l for l in lineas if l).strip()


# --------------------------------------------------------------------------
# Narracion
# --------------------------------------------------------------------------

def crear_tarea(texto: str, voz: str = "", velocidad: float = 0.0,
                nombre: str = "") -> str:
    if not texto.strip():
        raise RuntimeError("No hay texto que narrar.")
    if len(texto) > LIMITE_CARACTERES:
        raise RuntimeError(
            f"El guion tiene {len(texto)} caracteres y el limite es "
            f"{LIMITE_CARACTERES}.")

    campos = {
        "text": texto,
        "voice_id": voz or VOZ_POR_DEFECTO,
        "speed": str(velocidad or VELOCIDAD_POR_DEFECTO),
        "with_transcript": "false",
    }
    if nombre:
        campos["file_name"] = nombre

    respuesta = _peticion("/v3/text-to-speech", campos, metodo="POST")
    tarea = respuesta.get("task_id")
    if not tarea:
        raise RuntimeError(f"ai33.pro no ha devuelto task_id: {respuesta}")
    return tarea


def esperar_tarea(tarea: str, avance=None) -> str:
    """Sondea hasta que termina y devuelve la URL del mp3."""
    limite = time.time() + ESPERA_MAXIMA_S

    while time.time() < limite:
        time.sleep(SONDEO_S)
        estado = _peticion(f"/v1/task/{tarea}")
        situacion = estado.get("status")

        if avance:
            avance(int(estado.get("progress") or 0), situacion)

        if situacion == "done":
            url = (estado.get("metadata") or {}).get("audio_url")
            if not url:
                raise RuntimeError(
                    f"La tarea ha terminado sin audio: {estado}")
            return url

        if situacion in ("error", "failed", "cancelled"):
            raise RuntimeError(
                f"ai33.pro no ha podido generar la voz: "
                f"{estado.get('error_message') or situacion}")

    raise RuntimeError(
        f"La narracion sigue sin estar lista despues de "
        f"{ESPERA_MAXIMA_S // 60} minutos.")


def descargar(url: str, destino: Path) -> Path:
    """
    Baja el mp3 y lo deja en la carpeta del video.

    Un narracion.mp3 anterior se conserva, pero dentro de 'anteriores': el
    montaje exige un unico audio suelto en la carpeta, asi que dejarlo al lado
    con otro nombre bloquearia el montaje en vez de proteger nada.
    """
    destino = Path(destino)
    if destino.exists():
        viejas = destino.parent / "anteriores"
        viejas.mkdir(exist_ok=True)
        marca = time.strftime("%Y%m%d-%H%M%S")
        destino.replace(viejas / f"{destino.stem}_{marca}{destino.suffix}")

    # el CDN rechaza el User-Agent que urllib pone por defecto
    peticion = urllib.request.Request(url, headers={"User-Agent": NAVEGADOR})
    with urllib.request.urlopen(peticion, timeout=300) as respuesta:
        destino.write_bytes(respuesta.read())
    return destino


def narrar(guion: str, carpeta: Path, voz: str = "", velocidad: float = 0.0,
           avance=None) -> Path:
    """
    Guion -> narracion.mp3 en la carpeta del video.

    'avance' se llama como avance(porcentaje, situacion) durante el sondeo.
    """
    carpeta = Path(carpeta)
    texto = texto_locutable(guion)

    tarea = crear_tarea(texto, voz, velocidad, nombre=carpeta.name)
    url = esperar_tarea(tarea, avance)
    return descargar(url, carpeta / "narracion.mp3")
