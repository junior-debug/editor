"""
De un enlace copiado a un clip dentro de parteN.

Era el unico paso del flujo que seguia siendo manual de punta a punta: buscar
el video, copiar el enlace, clic derecho, guardar como, elegir la carpeta, y
otra vez desde el principio. Aqui se queda en copiar el enlace; de lo demas se
encarga la ventana vigilando el portapapeles (ver ui_guion.py).

**Se llama a yt-dlp por subproceso, no importando la libreria**, y no es por
pereza:

- se actualiza sola sin tocar el montador, y falta hace: YouTube cambia cada
  pocas semanas y yt-dlp va detras. Una version clavada en el codigo seria una
  descarga rota cada dos meses.
- una descarga que se atasca se mata sin llevarse la ventana por delante.
- es la misma forma en la que ya se llama a ffmpeg y al CLI de Claude.

Es la unica dependencia de este modulo y es **opcional**: sin ella el resto
del montador funciona igual, y la ventana ofrece instalarla cuando falta. Por
eso se invoca como '<python> -m yt_dlp' y no como 'yt-dlp' a secas: asi se usa
la del mismo interprete que corre el montador y no hace falta que el PATH
tenga nada.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from .edl import EXTENSIONES_VIDEO

SIN_CONSOLA = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Calidad tope. 1080p porque es lo que da la linea de tiempo de CapCut, y
# bajar 4K solo llenaria el disco: el montaje mete los clips a escala 1:1.
ALTURA_MAXIMA = 1080

# Media hora. Del video se usan cuatro segundos y pico, asi que uno de tres
# horas son varios gigas para tirar casi enteros -y esos videos existen y
# salen en las busquedas: los recopilatorios de paisajes duran eso-. Pasado
# el tope no se descarta, se pregunta.
DURACION_MAXIMA_S = 30 * 60

# Los once caracteres del identificador de YouTube. Se exige el identificador
# a proposito: asi un enlace de canal, de lista o de la pagina de resultados
# -que es justo lo que se copia sin querer mientras se busca- no cuela.
_RE_YOUTUBE = re.compile(
    r"(?:youtube\.com/(?:watch\?(?:[^\s]*&)?v=|shorts/|live/|embed/|v/)"
    r"|youtu\.be/)([A-Za-z0-9_-]{11})")

# Un enlace directo a un archivo de video, por si algun dia el material sale
# de otro sitio.
_RE_ARCHIVO = re.compile(
    r"^https?://\S+\.(?:mp4|mov|webm|mkv|m4v)(?:\?\S*)?$", re.I)

_RE_PORCENTAJE = re.compile(r"\[download\]\s+([\d.]+)%")

# Donde yt-dlp escribe la ruta final. Con un WHEN delante ('after_move:'),
# --print no implica --simulate, asi que descarga igualmente.
_MARCA_DESTINO = "MONTADOR_ARCHIVO "


class SinYtDlp(RuntimeError):
    """yt-dlp no esta instalado."""


class DemasiadoLargo(RuntimeError):
    """El video pasa del tope de duracion. Se pregunta antes de bajarlo."""

    def __init__(self, titulo: str, duracion_s: float):
        self.titulo = titulo
        self.duracion_s = duracion_s
        super().__init__(f"{titulo} dura {formato_duracion(duracion_s)}")


def formato_duracion(segundos: float) -> str:
    if not segundos:
        return "duracion desconocida"
    horas, resto = divmod(int(segundos), 3600)
    minutos = resto // 60
    return f"{horas} h {minutos:02d} min" if horas else f"{minutos} min"


# --------------------------------------------------------------------------
# Reconocer lo que se copia
# --------------------------------------------------------------------------

def es_enlace(texto: str) -> str:
    """
    Devuelve la URL limpia si lo copiado es un video, o "" si no lo es.

    Callar es la respuesta normal y no un fallo: esto se llama con **todo** lo
    que pasa por el portapapeles, y en una tarde ahi cae de todo. Solo se
    reacciona a lo que sin ninguna duda es un video.
    """
    texto = (texto or "").strip()
    # un parrafo copiado no es un enlace, y de paso evita pasearle el regex a
    # media novela cada medio segundo
    if not texto or len(texto) > 2000:
        return ""

    encontrado = _RE_YOUTUBE.search(texto)
    if encontrado:
        # normalizado y **sin el resto de parametros**: un enlace copiado
        # desde dentro de una lista trae '&list=...' detras, y con el la
        # descarga se llevaria la lista entera. Ademas deja iguales dos formas
        # distintas del mismo video, que es lo que detecta el repetido.
        return f"https://www.youtube.com/watch?v={encontrado.group(1)}"

    if _RE_ARCHIVO.match(texto):
        return texto
    return ""


# --------------------------------------------------------------------------
# La herramienta
# --------------------------------------------------------------------------

def version() -> str:
    """La version de yt-dlp instalada, o "" si no hay ninguna."""
    try:
        salida = subprocess.run(
            [sys.executable, "-m", "yt_dlp", "--version"],
            capture_output=True, text=True, timeout=60,
            creationflags=SIN_CONSOLA)
    except Exception:
        return ""
    return salida.stdout.strip() if salida.returncode == 0 else ""


def disponible() -> bool:
    return bool(version())


def instalar(progreso=None) -> tuple[bool, str]:
    """
    Instala o actualiza yt-dlp con el pip del interprete que nos corre.

    Actualizar tambien vale como reparacion: casi siempre que las descargas
    fallan de golpe habiendo funcionado ayer, es que YouTube ha cambiado algo
    y la version instalada se ha quedado corta.
    """
    orden = [sys.executable, "-m", "pip", "install", "-U", "yt-dlp"]
    return _correr(orden, progreso)


# --------------------------------------------------------------------------
# Descargar
# --------------------------------------------------------------------------

def siguiente_indice(carpeta: Path) -> int:
    """
    El numero que le toca al proximo clip de esa carpeta.

    Van numerados porque edl.py lee cada parteN con sorted(): **el nombre del
    archivo es lo que decide el orden de rotacion**. Se cuenta lo que ya hay
    en el disco en vez de llevar la cuenta en memoria para que los clips
    metidos a mano cuenten igual, y para que cerrar la ventana y volver no
    empiece otra vez por el uno pisando lo de antes.
    """
    if not carpeta.is_dir():
        return 1
    videos = [p for p in carpeta.iterdir()
              if p.is_file() and p.suffix.lower() in EXTENSIONES_VIDEO]
    numerados = [int(m.group(1)) for m in
                 (re.match(r"(\d+)", p.name) for p in videos) if m]
    # el mayor de los dos: con archivos sin numerar delante, seguir por el
    # total evita que el nuevo se cuele al principio del orden
    return max([len(videos)] + numerados) + 1


def datos(url: str) -> tuple[str, float]:
    """
    Titulo y duracion en segundos, sin bajar nada.

    Cuesta un segundo y ahorra gigas: es lo que separa 'este video dura tres
    horas' de enterarse cuando ya van dos.
    """
    orden = [sys.executable, "-m", "yt_dlp", "--no-playlist", "--simulate",
             "--no-warnings", "--print", "%(duration)s|%(title)s", url]
    lineas: list[str] = []
    codigo = _leer_salida(orden, lineas.append)
    if codigo != 0:
        ultima = next((l for l in reversed(lineas) if l.strip()), "")
        if "No module named" in "\n".join(lineas):
            raise SinYtDlp("yt-dlp no esta instalado")
        raise RuntimeError(ultima or f"no se ha podido leer {url}")

    for linea in lineas:
        if "|" in linea:
            crudo, _, titulo = linea.partition("|")
            try:
                return titulo.strip(), float(crudo)
            except ValueError:
                # 'NA': pasa en los directos, que no tienen final. Duracion
                # cero es justo lo que hace que se pregunte antes de bajar.
                return titulo.strip(), 0.0
    return url, 0.0


def descargar(url: str, destino: Path, indice: int | None = None,
              progreso=None, altura_max: int = ALTURA_MAXIMA,
              duracion_maxima: float = DURACION_MAXIMA_S) -> Path:
    """
    Baja un video a 'destino' y devuelve la ruta del archivo.

    'progreso' se llama con (porcentaje, linea) segun avanza; el porcentaje
    vale -1 en las lineas que no lo traen. Lanza RuntimeError con la ultima
    linea de yt-dlp si la descarga no sale, y DemasiadoLargo si pasa del tope
    ('duracion_maxima' a 0 lo desactiva, que es como se acepta uno largo).
    """
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)

    if duracion_maxima:
        titulo, duracion = datos(url)
        if not duracion or duracion > duracion_maxima:
            raise DemasiadoLargo(titulo, duracion)

    if indice is None:
        indice = siguiente_indice(destino)

    # el titulo recortado hace el nombre reconocible de un vistazo en el
    # Explorador, que es donde se descartan los clips que no valen
    plantilla = f"{indice:02d}_%(title).60s.%(ext)s"

    orden = [
        sys.executable, "-m", "yt_dlp",
        # 'watch?v=X&list=Y' se llevaria la lista entera; es_enlace() ya quita
        # ese parametro, pero esto lo cierra tambien para enlaces de otro sitio
        "--no-playlist",
        # sin acentos ni signos: nombre limpio en Windows y, sobre todo, orden
        # alfabetico estable, que es de donde sale el orden del montaje
        "--restrict-filenames",
        "--newline",      # el progreso linea a linea, no reescribiendo una
        "--no-colors",    # los codigos de color ensuciarian el registro
        "--progress",     # --print puede implicar --quiet; esto lo desarma
        "--no-simulate",
        # SIN AUDIO: 'bv*' es solo la pista de video, sin '+ba' detras. La
        # narracion va por su lado, asi que el audio del clip no se usa nunca
        # -y si viene, hay que silenciarlo a mano en CapCut clip por clip-.
        # De paso baja bastante menos peso.
        #
        # Y **H.264 primero** ('avc1'): pidiendo solo la mejor pista de video,
        # YouTube sirve AV1 o VP9, que CapCut mueve a tirones o no importa.
        # H.264 es el que traga sin pensarlo. Si no lo hay, se coge lo que
        # haya antes que quedarse sin clip.
        #
        # Los dos ultimos son el respaldo para cuando no hay pista de video
        # suelta y solo se ofrece el archivo ya mezclado; ese caso lo deja
        # mudo despues _quitar_audio().
        "-f", (f"bv*[height<={altura_max}][vcodec^=avc1]"
               f"/bv*[height<={altura_max}]/bv*"
               f"/b[height<={altura_max}]/b"),
        "--merge-output-format", "mp4",
        # el contenedor, siempre mp4: un .webm suelto en la carpeta es un
        # clip que CapCut puede rechazar al importar
        "--remux-video", "mp4",
        "--print", f"after_move:{_MARCA_DESTINO}%(filepath)s",
        "-P", str(destino),
        "-o", plantilla,
        url,
    ]

    ruta: Path | None = None
    lineas: list[str] = []

    def mirar(linea: str) -> None:
        nonlocal ruta
        if linea.startswith(_MARCA_DESTINO):
            ruta = Path(linea[len(_MARCA_DESTINO):].strip())
            return
        lineas.append(linea)
        if progreso:
            porcentaje = _RE_PORCENTAJE.search(linea)
            progreso(float(porcentaje.group(1)) if porcentaje else -1.0, linea)

    codigo = _leer_salida(orden, mirar)

    if codigo != 0:
        ultima = next((l for l in reversed(lineas) if l.strip()), "")
        # invocado como '-m yt_dlp', que falte no da FileNotFoundError: da un
        # codigo de salida y esta linea. Distinguirlo importa porque tiene
        # arreglo de un clic y el resto de fallos no.
        if "No module named" in "\n".join(lineas):
            raise SinYtDlp("yt-dlp no esta instalado")
        raise RuntimeError(ultima or f"yt-dlp ha salido con el codigo {codigo}")

    if ruta is None or not ruta.exists():
        # respaldo: --print es comodo pero depende de la version de yt-dlp, y
        # perder el archivo recien bajado por no saber como se llama seria
        # absurdo teniendolo delante en la carpeta
        candidatos = [p for p in destino.iterdir()
                      if p.is_file() and p.name.startswith(f"{indice:02d}_")
                      and p.suffix.lower() in EXTENSIONES_VIDEO]
        if not candidatos:
            raise RuntimeError("la descarga ha terminado pero el archivo no "
                               "aparece en la carpeta")
        ruta = max(candidatos, key=lambda p: p.stat().st_mtime)

    return _quitar_audio(ruta, progreso)


def _quitar_audio(ruta: Path, progreso=None) -> Path:
    """
    Deja el clip mudo si ha bajado con sonido.

    Con 'bv*' no deberia pasar casi nunca, pero cuando YouTube solo ofrece el
    archivo ya mezclado, yt-dlp cae al respaldo y trae el audio dentro. Se
    quita copiando los flujos ('-c copy'), sin recodificar: es cuestion de
    segundos y no toca la imagen.

    Si algo falla se devuelve el clip tal cual. Un clip con sonido se arregla
    en CapCut con un clic; perderlo por un fallo de ffmpeg, no.
    """
    from .edl import tiene_audio

    if not tiene_audio(ruta):
        return ruta

    if progreso:
        progreso(-1.0, "quitando el audio del clip")

    mudo = ruta.with_name(ruta.stem + ".mudo" + ruta.suffix)
    try:
        salida = subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(ruta),
             "-c", "copy", "-an", str(mudo)],
            capture_output=True, text=True, creationflags=SIN_CONSOLA)
        if salida.returncode != 0 or not mudo.exists():
            mudo.unlink(missing_ok=True)
            return ruta
        ruta.unlink()
        mudo.rename(ruta)
    except Exception:
        mudo.unlink(missing_ok=True)
        return ruta
    return ruta


# --------------------------------------------------------------------------
# Subprocesos
# --------------------------------------------------------------------------

def _leer_salida(orden: list[str], mirar) -> int:
    """Lanza la orden y le pasa cada linea a 'mirar'. Devuelve el codigo."""
    try:
        proceso = subprocess.Popen(
            orden, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            bufsize=1, creationflags=SIN_CONSOLA)
    except FileNotFoundError as exc:
        raise SinYtDlp(str(exc)) from exc

    for linea in proceso.stdout:
        mirar(linea.rstrip())
    return proceso.wait()


def _correr(orden: list[str], progreso=None) -> tuple[bool, str]:
    lineas: list[str] = []

    def mirar(linea: str) -> None:
        lineas.append(linea)
        if progreso and linea.strip():
            progreso(-1.0, linea)

    codigo = _leer_salida(orden, mirar)
    return codigo == 0, "\n".join(lineas[-12:])
