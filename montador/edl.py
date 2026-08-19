"""
Construccion del EDL (Edit Decision List).

El EDL es la fuente de verdad del montaje: una lista de decisiones en JSON,
independiente de CapCut. De el salen tanto el borrador de CapCut como el
render directo con FFmpeg. Si CapCut cambia su formato, esto sigue valiendo.
"""
from __future__ import annotations

import json
import random
import re
import subprocess
from dataclasses import dataclass, field, asdict
from pathlib import Path

from .config import Estilo, ESTILO

EXTENSIONES_VIDEO = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}


# --------------------------------------------------------------------------
# Estructuras
# --------------------------------------------------------------------------

@dataclass
class Bloque:
    """Un corte en la pista principal."""
    indice: int
    inicio_s: float          # posicion en la timeline
    duracion_s: float
    clip: str                # ruta absoluta del archivo fuente
    clip_inicio_s: float     # punto de entrada dentro del archivo
    transicion: str | None = None       # effect_id
    transicion_nombre: str | None = None
    transicion_duracion_s: float = 0.0


@dataclass
class Sonido:
    inicio_s: float
    duracion_s: float
    nombre: str
    bloque: int


@dataclass
class Rotulo:
    inicio_s: float
    duracion_s: float
    textos: list[str]
    plantilla: str


@dataclass
class EDL:
    duracion_s: float
    fps: float
    ancho: int
    alto: int
    narracion: str
    bloques: list[Bloque] = field(default_factory=list)
    sonidos: list[Sonido] = field(default_factory=list)
    rotulos: list[Rotulo] = field(default_factory=list)

    def guardar(self, ruta: Path) -> None:
        Path(ruta).write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=1),
            encoding="utf-8")

    @classmethod
    def cargar(cls, ruta: Path) -> "EDL":
        d = json.loads(Path(ruta).read_text(encoding="utf-8"))
        return cls(
            duracion_s=d["duracion_s"], fps=d["fps"],
            ancho=d["ancho"], alto=d["alto"], narracion=d["narracion"],
            bloques=[Bloque(**b) for b in d["bloques"]],
            sonidos=[Sonido(**s) for s in d["sonidos"]],
            rotulos=[Rotulo(**r) for r in d["rotulos"]],
        )

    def resumen(self) -> str:
        d = [b.duracion_s for b in self.bloques]
        con_t = sum(1 for b in self.bloques if b.transicion)
        clips = {b.clip for b in self.bloques}
        return (
            f"{len(self.bloques)} cortes en {self.duracion_s:.1f} s\n"
            f"  duracion media  : {sum(d)/len(d):.2f} s "
            f"(min {min(d):.2f} / max {max(d):.2f})\n"
            f"  clips distintos : {len(clips)}\n"
            f"  transiciones    : {con_t} ({100*con_t/len(self.bloques):.0f} %"
            f", una cada {len(self.bloques)/max(con_t,1):.1f} cortes)\n"
            f"  sonidos         : {len(self.sonidos)} "
            f"(uno cada {self.duracion_s/max(len(self.sonidos),1):.1f} s)\n"
            f"  rotulos         : {len(self.rotulos)}"
        )


# --------------------------------------------------------------------------
# Material
# --------------------------------------------------------------------------

def edl_duracion_util(bloques: list["Bloque"]) -> float:
    """Instante en que termina el ultimo corte."""
    if not bloques:
        return 0.0
    ultimo = bloques[-1]
    return ultimo.inicio_s + ultimo.duracion_s


def duracion_video(ruta: Path) -> float:
    salida = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(ruta)],
        capture_output=True, text=True, check=True)
    return float(salida.stdout.strip())


def dimensiones_video(ruta: Path) -> tuple[int, int]:
    salida = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height",
         "-of", "csv=s=x:p=0", str(ruta)],
        capture_output=True, text=True, check=True)
    w, h = salida.stdout.strip().split("x")
    return int(w), int(h)


def descubrir_partes(raiz: Path) -> list[list[Path]]:
    """
    Devuelve los clips agrupados por carpeta parteN, en orden.
    Si no hay carpetas parteN, todos los videos van a una sola parte.
    """
    carpetas = sorted(
        [d for d in raiz.iterdir()
         if d.is_dir() and re.fullmatch(r"parte\s*\d+", d.name, re.I)],
        key=lambda d: int(re.search(r"\d+", d.name).group()))

    if not carpetas:
        clips = sorted(p for p in raiz.iterdir()
                       if p.suffix.lower() in EXTENSIONES_VIDEO)
        return [clips] if clips else []

    partes = []
    for c in carpetas:
        clips = sorted(p for p in c.iterdir()
                       if p.suffix.lower() in EXTENSIONES_VIDEO)
        if clips:
            partes.append(clips)
    return partes


# --------------------------------------------------------------------------
# Guion
# --------------------------------------------------------------------------

MARCA_TXT = re.compile(r"\[TXT:\s*(.+?)\]", re.S)


def extraer_marcas(guion: str) -> list[str]:
    """
    Saca los rotulos marcados en el guion como [TXT: ...].
    Un salto de linea dentro de la marca se respeta como salto en el rotulo.
    """
    return [m.group(1).strip() for m in MARCA_TXT.finditer(guion)]


def posiciones_marcas(guion: str, alineacion, duracion_s: float) -> list[float]:
    """
    Estima en que segundo cae cada marca [TXT: ...] segun su posicion relativa
    en el guion. Aproximacion por proporcion de caracteres: suficiente para
    colocar 5-6 rotulos en un video de 13 minutos, y el retoque fino se hace
    en CapCut.
    """
    limpio = MARCA_TXT.sub("", guion)
    total = max(len(limpio), 1)
    posiciones = []
    desplazamiento = 0
    for m in MARCA_TXT.finditer(guion):
        antes = len(guion[:m.start()]) - desplazamiento
        desplazamiento += len(m.group(0))
        posiciones.append(round(duracion_s * antes / total, 2))
    return posiciones


# --------------------------------------------------------------------------
# Plan de cortes
# --------------------------------------------------------------------------

def plan_de_cortes(duracion_s: float, pausas: list[float],
                   estilo: Estilo) -> list[tuple[float, float]]:
    """
    Devuelve [(inicio, duracion)] cubriendo la narracion entera.

    Se avanza en pasos del tamano objetivo y cada frontera se desplaza a la
    pausa mas cercana dentro de la ventana, siempre que el bloque resultante
    respete minimo y maximo.
    """
    c = estilo.corte
    fronteras = [0.0]
    t = 0.0
    pausas_ord = sorted(pausas)

    while t < duracion_s:
        objetivo = t + c.objetivo_s
        if objetivo >= duracion_s - c.minimo_s:
            break

        candidata = objetivo
        if pausas_ord:
            cercanas = [p for p in pausas_ord
                        if abs(p - objetivo) <= c.ventana_pausa_s
                        and c.minimo_s <= p - t <= c.maximo_s]
            if cercanas:
                candidata = min(cercanas, key=lambda p: abs(p - objetivo))

        candidata = max(t + c.minimo_s, min(candidata, t + c.maximo_s))
        fronteras.append(round(candidata, 3))
        t = candidata

    fronteras.append(round(duracion_s, 3))

    return [(fronteras[i], round(fronteras[i + 1] - fronteras[i], 3))
            for i in range(len(fronteras) - 1)]


# --------------------------------------------------------------------------
# Seleccion de clips: rotacion con cursor propio
# --------------------------------------------------------------------------

class Rotador:
    """
    Reproduce el patron real de junior:

      - las carpetas parteN entran en juego de forma acumulativa
      - se rota entre todos los clips disponibles en ese momento
      - cada clip tiene su propio cursor de lectura, que avanza
      - al agotar un clip, su cursor vuelve al principio
    """

    def __init__(self, partes: list[list[Path]], entradas_s: list[float]):
        self.partes = partes
        self.entradas = entradas_s
        self.duraciones = {p: duracion_video(p)
                           for parte in partes for p in parte}
        self.cursores = {p: 0.0 for p in self.duraciones}
        self.i = 0

    def disponibles(self, t: float) -> list[Path]:
        pool: list[Path] = []
        for parte, entrada in zip(self.partes, self.entradas):
            if t >= entrada:
                pool.extend(parte)
        return pool or list(self.partes[0])

    def siguiente(self, t: float, duracion: float) -> tuple[Path, float]:
        pool = self.disponibles(t)
        clip = pool[self.i % len(pool)]
        self.i += 1

        inicio = self.cursores[clip]
        if inicio + duracion > self.duraciones[clip]:
            inicio = 0.0
        self.cursores[clip] = round(inicio + duracion, 3)
        return clip, round(inicio, 3)


# --------------------------------------------------------------------------
# Construccion
# --------------------------------------------------------------------------

def construir(duracion_s: float, pausas: list[float], raiz_clips: Path,
              narracion: Path, guion: str = "",
              entradas_s: list[float] | None = None,
              estilo: Estilo = ESTILO,
              catalogo_transiciones: dict | None = None) -> EDL:

    rnd = random.Random(estilo.semilla)
    partes = descubrir_partes(raiz_clips)
    if not partes:
        raise RuntimeError(f"No hay clips de video en {raiz_clips}")

    if entradas_s is None:
        # por defecto las partes entran repartidas a lo largo de la narracion
        entradas_s = [round(duracion_s * i / len(partes), 2)
                      for i in range(len(partes))]

    rotador = Rotador(partes, entradas_s)
    cortes = plan_de_cortes(duracion_s, pausas, estilo)

    # --- bloques + transiciones ---
    bloques: list[Bloque] = []
    ids_trans = list(estilo.transicion.pesos)
    pesos_trans = [estilo.transicion.pesos[i] for i in ids_trans]
    proxima_trans = estilo.transicion.cada_n_cortes

    for i, (inicio, dur) in enumerate(cortes):
        clip, clip_inicio = rotador.siguiente(inicio, dur)
        b = Bloque(indice=i, inicio_s=inicio, duracion_s=dur,
                   clip=str(clip), clip_inicio_s=clip_inicio)

        if i == proxima_trans:
            eid = rnd.choices(ids_trans, weights=pesos_trans, k=1)[0]
            b.transicion = eid
            if catalogo_transiciones and eid in catalogo_transiciones:
                t = catalogo_transiciones[eid]
                b.transicion_nombre = t["name"]
                b.transicion_duracion_s = round(t["duration"] / 1e6, 3)
            proxima_trans = i + estilo.transicion.cada_n_cortes + \
                rnd.randint(-estilo.transicion.jitter,
                            estilo.transicion.jitter)

        bloques.append(b)

    # --- sonidos: solo en cortes SIN transicion ---
    sonidos: list[Sonido] = []
    nombres = list(estilo.sonido.pesos)
    pesos_snd = [estilo.sonido.pesos[n] for n in nombres]
    siguiente_t = estilo.sonido.cada_s

    # Se eligen los cortes elegibles (sin transicion) mas cercanos al ritmo
    # objetivo. Coger "el primero a partir de", en cambio, introduce un sesgo
    # acumulativo: al descartar 1 de cada 3 cortes el intervalo real se va
    # varios segundos por encima del pretendido.
    elegibles = [b for b in bloques[1:]
                 if not (estilo.sonido.solo_en_cortes_sin_transicion
                         and b.transicion)]
    usados: set[int] = set()

    while siguiente_t < edl_duracion_util(bloques):
        candidatos = [b for b in elegibles if b.indice not in usados]
        if not candidatos:
            break
        b = min(candidatos, key=lambda x: abs(x.inicio_s - siguiente_t))
        usados.add(b.indice)

        if rnd.random() < estilo.sonido.probabilidad_en_frame:
            adelanto = 0.0
        else:
            adelanto = round(rnd.uniform(0.2,
                                         estilo.sonido.anticipacion_maxima_s), 3)

        sonidos.append(Sonido(
            inicio_s=round(max(0.0, b.inicio_s - adelanto), 3),
            duracion_s=1.2,
            nombre=rnd.choices(nombres, weights=pesos_snd, k=1)[0],
            bloque=b.indice,
        ))
        siguiente_t = b.inicio_s + estilo.sonido.cada_s + \
            rnd.uniform(-estilo.sonido.jitter_s, estilo.sonido.jitter_s)

    sonidos.sort(key=lambda s: s.inicio_s)

    # --- rotulos desde las marcas del guion ---
    rotulos: list[Rotulo] = []
    if guion:
        textos = extraer_marcas(guion)
        posiciones = posiciones_marcas(guion, None, duracion_s)
        for texto, pos in zip(textos, posiciones):
            rotulos.append(Rotulo(
                inicio_s=pos,
                duracion_s=estilo.rotulo.duracion_s,
                textos=[texto],
                plantilla=estilo.rotulo.plantilla_por_defecto,
            ))

    return EDL(
        duracion_s=round(duracion_s, 3),
        fps=estilo.fps, ancho=estilo.ancho, alto=estilo.alto,
        narracion=str(narracion),
        bloques=bloques, sonidos=sonidos, rotulos=rotulos,
    )
