"""
Alineacion de la narracion.

Transcribe el audio con timestamps por palabra y deriva la lista de pausas
naturales. Los cortes se desplazan a esas pausas: asi caen donde el narrador
respira y el montaje no suena a cronometro.

faster-whisper es opcional. Si no esta instalado se puede trabajar con un
transcript ya generado (--transcripcion) o sin alineacion (cadencia fija).
"""
from __future__ import annotations

import difflib
import json
import re
import subprocess
import unicodedata
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Palabra:
    inicio: float
    fin: float
    texto: str


@dataclass
class Alineacion:
    duracion_s: float
    palabras: list[Palabra]

    @property
    def pausas(self) -> list[float]:
        """Instantes aprovechables para cortar, ordenados."""
        return self._pausas

    def calcular_pausas(self, minima_s: float) -> list[float]:
        p = []
        for a, b in zip(self.palabras, self.palabras[1:]):
            hueco = b.inicio - a.fin
            if hueco >= minima_s:
                # el corte va en mitad del silencio
                p.append(round(a.fin + hueco / 2, 3))
        self._pausas = p
        return p

    def guardar(self, ruta: Path) -> None:
        ruta.write_text(json.dumps({
            "duracion_s": self.duracion_s,
            "palabras": [{"inicio": w.inicio, "fin": w.fin, "texto": w.texto}
                         for w in self.palabras],
        }, ensure_ascii=False, indent=1), encoding="utf-8")

    @classmethod
    def cargar(cls, ruta: Path) -> "Alineacion":
        d = json.loads(Path(ruta).read_text(encoding="utf-8"))
        return cls(
            duracion_s=d["duracion_s"],
            palabras=[Palabra(**w) for w in d["palabras"]],
        )


# --------------------------------------------------------------------------
# Cruzar el guion con lo que de verdad se oye
# --------------------------------------------------------------------------
#
# La transcripcion sabe CUANDO suena cada palabra; el guion sabe QUE se dijo y
# donde van sus marcas. Cruzarlos da la posicion real de cada rotulo, en vez
# de estimarla por proporcion de caracteres.
#
# No son el mismo texto: Whisper se come palabras, escribe "35" donde el guion
# pone "35%", y a veces oye otra cosa. Por eso se alinean como dos secuencias
# -anclando los tramos que coinciden e interpolando los huecos- y no palabra
# por palabra, que se desincronizaria en el primer fallo.

_RE_TOKEN = re.compile(r"[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+")

# Por debajo de esto la alineacion no es de fiar y quien llame hara bien en
# quedarse con su estimacion. Con material real se pasa del 90 %.
FIABILIDAD_MINIMA = 0.55


def _normalizar(palabra: str) -> str:
    """Minusculas y sin tildes: Whisper no siempre las pone donde el guion."""
    plana = unicodedata.normalize("NFKD", palabra.lower())
    return "".join(c for c in plana if not unicodedata.combining(c))


def tokenizar(texto: str) -> list[str]:
    """Las palabras de un texto, normalizadas, sin puntuacion ni marcas."""
    return [_normalizar(m.group()) for m in _RE_TOKEN.finditer(texto)]


@dataclass
class MapaGuion:
    """En que segundo se dice cada palabra del guion."""
    tiempos: list[float]
    ancladas: int          # cuantas salieron de una coincidencia real
    duracion_s: float

    @property
    def fiabilidad(self) -> float:
        return self.ancladas / max(len(self.tiempos), 1)

    def segundo_de(self, indice_palabra: int) -> float:
        """El segundo de una palabra, por su numero de orden en el guion."""
        if not self.tiempos:
            return 0.0
        i = min(max(indice_palabra, 0), len(self.tiempos) - 1)
        return round(self.tiempos[i], 3)


def alinear_guion(texto: str, palabras: list[Palabra],
                  duracion_s: float) -> MapaGuion:
    """
    Cruza el texto locutado con las palabras transcritas.

    'texto' tiene que ser el que se narro, ya sin las marcas [TXT: ...]: es lo
    que el narrador leyo y por tanto lo unico que puede coincidir con lo que
    se oye.
    """
    guion = tokenizar(texto)
    oidas = [_normalizar(p.texto) for p in palabras]
    tiempos: list[float | None] = [None] * len(guion)

    if not guion or not oidas:
        return MapaGuion([], 0, duracion_s)

    # autojunk=False es imprescindible: con listas largas, difflib descarta
    # como "ruido" los elementos que se repiten mucho, y en un texto en
    # español eso son 'de', 'la', 'que'... justo las que mas anclan.
    comparador = difflib.SequenceMatcher(None, guion, oidas, autojunk=False)

    ancladas = 0
    for i, j, n in comparador.get_matching_blocks():
        for k in range(n):
            tiempos[i + k] = palabras[j + k].inicio
            ancladas += 1

    conocidos = [i for i, t in enumerate(tiempos) if t is not None]
    if not conocidos:
        # ni una coincidencia: se reparte a ojo, que es lo que se hacia antes
        return MapaGuion(
            [duracion_s * i / len(guion) for i in range(len(guion))],
            0, duracion_s)

    # huecos interiores: lo que Whisper no reconocio se reparte entre las dos
    # anclas que lo rodean. Dentro de un hueco de tres o cuatro palabras el
    # error es de decimas, y los huecos largos son raros.
    for a, b in zip(conocidos, conocidos[1:]):
        if b - a > 1:
            ta, tb = tiempos[a], tiempos[b]
            for k in range(a + 1, b):
                tiempos[k] = ta + (tb - ta) * (k - a) / (b - a)

    # extremos: antes de la primera ancla se estira hasta cero, y despues de
    # la ultima hasta el final del audio
    primero, ultimo = conocidos[0], conocidos[-1]
    for i in range(primero):
        tiempos[i] = tiempos[primero] * i / primero if primero else 0.0
    cola = len(guion) - 1 - ultimo
    for i in range(ultimo + 1, len(guion)):
        avance = (i - ultimo) / cola if cola else 1.0
        tiempos[i] = tiempos[ultimo] + (duracion_s - tiempos[ultimo]) * avance

    return MapaGuion([float(t) for t in tiempos], ancladas, duracion_s)


def duracion_audio(ruta: Path) -> float:
    """Duracion en segundos via ffprobe."""
    salida = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(ruta)],
        capture_output=True, text=True, check=True)
    return float(salida.stdout.strip())


def _registrar_dlls_cuda() -> list[str]:
    """
    En Windows, 'pip install nvidia-cublas-cu12 nvidia-cudnn-cu12' deja las
    DLL dentro de site-packages\\nvidia\\...\\bin, pero NADIE anade esa ruta al
    buscador de DLL del proceso. Por eso ctranslate2 sigue diciendo
    'cublas64_12.dll is not found' aunque el paquete este instalado.

    Aqui se registran esas carpetas a mano antes de tocar el modelo.
    """
    import os
    import sys

    if not sys.platform.startswith("win"):
        return []

    registradas = []
    try:
        import nvidia
        raices = [Path(p) for p in nvidia.__path__]
    except ImportError:
        raices = []

    for raiz in raices:
        for binario in sorted(raiz.glob("*/bin")):
            if not binario.is_dir():
                continue
            try:
                os.add_dll_directory(str(binario))
                registradas.append(str(binario))
            except OSError:
                pass
            # algunos entornos solo miran el PATH
            os.environ["PATH"] = str(binario) + os.pathsep + \
                os.environ.get("PATH", "")

    return registradas


def _cargar_modelo(modelo: str, dispositivo: str, computo: str | None):
    """
    Carga el modelo, cayendo a CPU si la GPU no esta usable.

    device='auto' detecta la tarjeta NVIDIA pero NO comprueba que esten las
    librerias de CUDA (cuBLAS, cuDNN). Si faltan, revienta con
    'cublas64_12.dll is not found'. Aqui se captura y se sigue por CPU:
    mas lento, pero funciona en cualquier maquina.
    """
    if dispositivo in ("auto", "cuda"):
        _registrar_dlls_cuda()

    from faster_whisper import WhisperModel

    intentos = []
    if dispositivo in ("auto", "cuda"):
        intentos.append(("cuda", computo or "float16"))
    if dispositivo in ("auto", "cpu"):
        intentos.append(("cpu", computo or "int8"))

    ultimo_error = None
    for dev, cmp_ in intentos:
        try:
            m = WhisperModel(modelo, device=dev, compute_type=cmp_)
            if dev == "cpu" and dispositivo == "auto" and len(intentos) > 1:
                print(f"  (GPU no usable: {type(ultimo_error).__name__}: "
                      f"{ultimo_error}) -> se sigue por CPU")
            return m
        except Exception as exc:            # noqa: BLE001
            ultimo_error = exc
            continue

    raise RuntimeError(
        f"No se ha podido cargar el modelo de whisper ni en GPU ni en CPU.\n"
        f"Ultimo error: {ultimo_error}\n"
        f"Prueba con --dispositivo cpu --computo int8")


def transcribir(ruta_audio: Path, modelo: str = "medium",
                idioma: str = "es", dispositivo: str = "auto",
                computo: str | None = None) -> Alineacion:
    """
    Transcribe con faster-whisper y devuelve la alineacion palabra a palabra.

    Modelos: tiny / base / small / medium / large-v3. Para espanol, 'medium'
    da timestamps suficientemente buenos y corre en CPU decente en unos
    minutos para 13 min de audio. Con GPU, 'large-v3'.
    """
    try:
        import faster_whisper  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper no esta instalado.\n"
            "  pip install faster-whisper\n"
            "O bien pasa una transcripcion ya hecha con --transcripcion."
        ) from exc

    modelo_w = _cargar_modelo(modelo, dispositivo, computo)
    segmentos, _info = modelo_w.transcribe(
        str(ruta_audio), language=idioma, word_timestamps=True,
        vad_filter=True)

    palabras: list[Palabra] = []
    for seg in segmentos:
        for w in (seg.words or []):
            palabras.append(Palabra(
                inicio=round(w.start, 3),
                fin=round(w.end, 3),
                texto=w.word.strip(),
            ))

    return Alineacion(duracion_s=duracion_audio(ruta_audio), palabras=palabras)
