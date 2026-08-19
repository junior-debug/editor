"""
Alineacion de la narracion.

Transcribe el audio con timestamps por palabra y deriva la lista de pausas
naturales. Los cortes se desplazan a esas pausas: asi caen donde el narrador
respira y el montaje no suena a cronometro.

faster-whisper es opcional. Si no esta instalado se puede trabajar con un
transcript ya generado (--transcripcion) o sin alineacion (cadencia fija).
"""
from __future__ import annotations

import json
import subprocess
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
