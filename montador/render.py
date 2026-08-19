"""
Render directo con FFmpeg.

Es la segunda salida del EDL y cumple dos funciones:

  1. Borrador rapido (--borrador, 480p ultrafast) para revisar el montaje en
     segundos sin abrir CapCut.
  2. Seguro de vida: si una actualizacion de CapCut rompe el formato de
     borrador, la logica de montaje sigue sirviendo y se renderiza por aqui.

No reproduce las transiciones de CapCut (son efectos propietarios); usa un
fundido corto en su lugar. Para el montaje final, CapCut.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from .edl import EDL


def resolver_sonido(nombre: str, carpeta_sfx: Path | None) -> Path | None:
    """
    Los sonidos del EDL se identifican por su nombre en la libreria de CapCut,
    que aqui no existe. Si se pasa una carpeta local, se busca un archivo cuyo
    nombre empiece igual (sin la coletilla numerica de CapCut).
    """
    p = Path(nombre)
    if p.exists():
        return p
    if not carpeta_sfx or not carpeta_sfx.exists():
        return None
    base = nombre.split("(")[0].strip().lower()
    for f in sorted(carpeta_sfx.iterdir()):
        if f.is_file() and f.stem.lower().startswith(base[:12]):
            return f
    return None


def render_ffmpeg(edl: EDL, salida: Path, borrador: bool = False,
                  carpeta_sfx: Path | None = None) -> Path:
    alto = 480 if borrador else edl.alto
    ancho = int(edl.ancho * alto / edl.alto) // 2 * 2
    preset = "ultrafast" if borrador else "medium"
    crf = "30" if borrador else "20"

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        trozos = []

        for b in edl.bloques:
            trozo = tmp / f"{b.indice:04d}.mp4"
            cmd = [
                "ffmpeg", "-v", "error", "-y",
                "-ss", str(b.clip_inicio_s), "-t", str(b.duracion_s),
                "-i", b.clip,
                "-vf", f"scale={ancho}:{alto}:force_original_aspect_ratio="
                       f"increase,crop={ancho}:{alto},fps={edl.fps}",
                "-an",
                "-c:v", "libx264", "-preset", preset, "-crf", crf,
                str(trozo),
            ]
            subprocess.run(cmd, check=True)
            trozos.append(trozo)

        lista = tmp / "lista.txt"
        lista.write_text("".join(f"file '{t}'\n" for t in trozos),
                         encoding="utf-8")

        video_mudo = tmp / "video.mp4"
        subprocess.run([
            "ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0",
            "-i", str(lista), "-c", "copy", str(video_mudo)], check=True)

        # mezcla: narracion + efectos
        entradas = ["-i", str(video_mudo), "-i", edl.narracion]
        filtros = ["[1:a]volume=1.0[narr]"]
        mezcla = "[narr]"

        sonidos_disponibles = []
        for s in edl.sonidos:
            ruta = resolver_sonido(s.nombre, carpeta_sfx)
            if ruta:
                sonidos_disponibles.append((s, ruta))
        if edl.sonidos and not sonidos_disponibles:
            print(f"  aviso: ninguno de los {len(edl.sonidos)} efectos de "
                  f"sonido se ha podido resolver a un archivo local; el "
                  f"render sale sin ellos (en CapCut si estaran). Usa --sfx "
                  f"para apuntar a una carpeta con los wav.")

        for i, (s, ruta) in enumerate(sonidos_disponibles):
            entradas += ["-i", str(ruta)]
            filtros.append(
                f"[{i+2}:a]adelay={int(s.inicio_s*1000)}|"
                f"{int(s.inicio_s*1000)},volume=0.8[s{i}]")
            mezcla += f"[s{i}]"

        if sonidos_disponibles:
            filtros.append(
                f"{mezcla}amix=inputs={len(sonidos_disponibles)+1}:"
                f"duration=first:normalize=0[out]")
            mapa_audio = "[out]"
        else:
            mapa_audio = "[narr]"

        subprocess.run([
            "ffmpeg", "-v", "error", "-y", *entradas,
            "-filter_complex", ";".join(filtros),
            "-map", "0:v", "-map", mapa_audio,
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest", str(salida)], check=True)

    print(f"Render escrito en {salida}")
    return salida
