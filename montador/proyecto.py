"""
Carpeta de trabajo de cada video, dentro de MasterTube.

Un video = una carpeta con la narracion suelta, el guion y los clips
repartidos en parte1...parteN. Aqui se crea, se abre en el Explorador y se
comprueba que esta completa ANTES de lanzar whisper: transcribir tarda
minutos y seria una espera tirada para acabar fallando porque faltaba el mp3.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from .edl import EXTENSIONES_VIDEO

EXTENSIONES_AUDIO = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}

PARTES_POR_DEFECTO = 4

# caracteres que Windows no admite en un nombre de carpeta
PROHIBIDOS = '<>:"/\\|?*'

ES_PARTE = re.compile(r"parte\s*\d+", re.I)

# Cualquier .txt suelto en la raiz puede acabar tomandose por el guion, asi
# que lo demas que escribimos ahi va excluido por nombre. La lista esta aqui
# y no repetida en cada sitio porque cuando lo estaba se quedo sin actualizar:
# 'busquedas' faltaba en la deteccion de 'montador voz'.
NO_SON_GUION = ("trans", "busquedas", "publicacion", "guion_anterior")


# --------------------------------------------------------------------------
# Localizacion
# --------------------------------------------------------------------------

def raiz() -> Path:
    """
    Carpeta MasterTube del escritorio.

    Se puede mover con la variable de entorno MASTERTUBE. Con OneDrive el
    escritorio real cuelga de la carpeta de OneDrive y no del perfil, asi que
    se prueban las dos y gana la que ya exista.
    """
    manual = os.environ.get("MASTERTUBE")
    if manual:
        return Path(manual)

    perfil = Path(os.environ.get("USERPROFILE") or Path.home())
    escritorios = [perfil / "Desktop"]
    onedrive = os.environ.get("OneDrive")
    if onedrive:
        escritorios.append(Path(onedrive) / "Desktop")

    for d in escritorios:
        if (d / "MasterTube").exists():
            return d / "MasterTube"
    for d in escritorios:
        if d.exists():
            return d / "MasterTube"
    return escritorios[0] / "MasterTube"


def sanear(nombre: str) -> str:
    """Nombre de carpeta valido en Windows, que no admite acabar en . ni en espacio."""
    limpio = "".join(c for c in nombre.strip() if c not in PROHIBIDOS)
    return limpio.rstrip(" .")


def carpeta(nombre: str) -> Path:
    return raiz() / sanear(nombre)


def partes_de(destino: Path) -> list[Path]:
    return sorted(
        [d for d in destino.iterdir()
         if d.is_dir() and ES_PARTE.fullmatch(d.name)],
        key=lambda d: int(re.search(r"\d+", d.name).group()))


def guardar_busquedas(destino: Path,
                      busquedas: dict[int, list[str]]) -> list[Path]:
    """
    Escribe las busquedas dentro de la parteN que les toca.

    Van en la subcarpeta y no sueltas en la raiz por una razon practica: el
    dia que abras parte3 para llenarla, la lista esta ahi mismo. Y por una
    tecnica: en la raiz, un .txt de mas puede acabar tomandose por el guion,
    mientras que dentro de parteN solo cuentan los videos.

    Si el guion tiene mas partes que carpetas, las que sobran se suman al
    final de la ultima: mejor tenerlas de mas en un sitio raro que perderlas.
    """
    if not busquedas:
        return []

    carpetas = partes_de(destino)
    reparto: dict[Path, list[int]] = {}

    for numero in sorted(busquedas):
        if carpetas:
            cual = carpetas[min(numero, len(carpetas)) - 1]
        else:
            # sin parteN no hay donde meterlas; a la raiz, con un nombre que
            # la deteccion del guion sabe esquivar
            cual = destino
        reparto.setdefault(cual, []).append(numero)

    escritos = []
    for carpeta, numeros in reparto.items():
        trozo = {n: busquedas[n] for n in numeros}
        ruta = carpeta / "busquedas.txt"
        ruta.write_text(_texto_busquedas(trozo) + "\n", encoding="utf-8")
        escritos.append(ruta)
    return escritos


def guardar_publicacion(destino: Path, texto: str) -> Path:
    """
    Escribe los titulos y la descripcion en la raiz de la carpeta.

    Aqui si van sueltos y no dentro de una parteN: no ilustran nada, son del
    video entero. El nombre queda excluido de la deteccion del guion en los
    dos sitios donde se busca un .txt en la raiz; sin eso, un dia sin
    guion.txt se acabaria narrando la descripcion de YouTube.
    """
    ruta = destino / "publicacion.txt"
    ruta.write_text(texto.strip() + "\n", encoding="utf-8")
    return ruta


def _texto_busquedas(busquedas: dict[int, list[str]]) -> str:
    # importacion perezosa: guionista importa este modulo indirectamente
    from .guionista import texto_busquedas
    return texto_busquedas(busquedas)


def nombre_proyecto(destino: Path) -> str:
    """Nombre del borrador en CapCut: el de la carpeta, sin espacios, + _auto."""
    return destino.name.replace(" ", "_") + "_auto"


# --------------------------------------------------------------------------
# Creacion
# --------------------------------------------------------------------------

def crear(nombre: str, partes: int = PARTES_POR_DEFECTO) -> Path:
    destino = carpeta(nombre)
    destino.mkdir(parents=True, exist_ok=True)
    for i in range(1, partes + 1):
        (destino / f"parte{i}").mkdir(exist_ok=True)
    return destino


def abrir_en_explorador(destino: Path) -> None:
    """Comodidad: deja la carpeta abierta para soltar los archivos dentro."""
    try:
        os.startfile(str(destino))          # solo existe en Windows
    except Exception:
        pass


# --------------------------------------------------------------------------
# Comprobacion
# --------------------------------------------------------------------------

def revisar(destino: Path) -> tuple[list[str], list[str]]:
    """
    Devuelve (errores, avisos).

    Errores = no se puede montar. Avisos = se monta, pero peor: sin guion no
    hay rotulos, y una parteN vacia simplemente no aporta clips.
    """
    if not destino.exists():
        return [f"no existe la carpeta {destino}"], []

    errores: list[str] = []
    avisos: list[str] = []

    audios = [p for p in destino.iterdir()
              if p.is_file() and p.suffix.lower() in EXTENSIONES_AUDIO]
    if not audios:
        errores.append("falta la narracion: deja el mp3 suelto en la carpeta")
    elif len(audios) > 1:
        errores.append("hay varios audios sueltos ("
                       + ", ".join(p.name for p in audios)
                       + "): deja solo la narracion")

    guiones = [p for p in destino.iterdir()
               if p.is_file() and p.suffix.lower() == ".txt"
               and p.stem.lower() not in NO_SON_GUION]
    if not guiones:
        avisos.append("no hay guion .txt: el montaje saldra sin rotulos")

    partes = partes_de(destino)
    if not partes:
        # descubrir_partes() acepta los videos sueltos como una unica parte
        sueltos = [p for p in destino.iterdir()
                   if p.is_file() and p.suffix.lower() in EXTENSIONES_VIDEO]
        if not sueltos:
            errores.append(
                "no hay carpetas parte1, parte2, ... ni videos sueltos")
    else:
        vacias = [c.name for c in partes
                  if not any(h.is_file()
                             and h.suffix.lower() in EXTENSIONES_VIDEO
                             for h in c.iterdir())]
        if len(vacias) == len(partes):
            errores.append(
                "las carpetas de partes estan vacias: no hay ningun video")
        elif vacias:
            avisos.append("sin videos, se ignoran: " + ", ".join(vacias))

    return errores, avisos


def _mostrar(errores: list[str], avisos: list[str]) -> None:
    for a in avisos:
        print(f"     aviso : {a}")
    for e in errores:
        print(f"     falta : {e}")


# --------------------------------------------------------------------------
# Flujo interactivo
# --------------------------------------------------------------------------

def _leer(mensaje: str) -> str:
    try:
        return input(mensaje).strip()
    except EOFError:
        raise RuntimeError(
            "No hay consola interactiva. Indica la carpeta con --clips.")


def preguntar_carpeta() -> tuple[Path, bool]:
    """
    Pide el nombre y devuelve (carpeta, recien_creada).

    El segundo valor sirve para no listarle a nadie todo lo que le falta a una
    carpeta que se acaba de crear vacia: eso ya se sabe.
    """
    base = raiz()
    print(f"  MasterTube : {base}")

    if base.exists():
        hechas = [d.name for d in sorted(base.iterdir()) if d.is_dir()]
        if hechas:
            print("  ya hay     : " + ", ".join(hechas[-6:]))
    print()

    while True:
        nombre = sanear(_leer("  Nombre de la carpeta del video: "))
        if nombre:
            break
        print("     escribe un nombre.")

    destino = base / nombre
    if destino.exists():
        print(f"  Ya existe  : {destino}")
        return destino, False

    partes = PARTES_POR_DEFECTO
    respuesta = _leer(f"  Cuantas partes (parte1...parteN)? [{partes}]: ")
    if respuesta:
        try:
            partes = max(1, min(int(respuesta), 30))
        except ValueError:
            print(f"     no es un numero, se usan {partes}.")

    destino = crear(nombre, partes)
    print(f"  Creada     : {destino}")
    print(f"               con parte1 ... parte{partes}")
    return destino, True


def esperar_material(destino: Path) -> None:
    """Abre la carpeta y no sigue hasta que dentro este todo lo necesario."""
    abrir_en_explorador(destino)
    print()
    print("  Deja dentro de esa carpeta:")
    print("     - la narracion (un solo mp3, suelto en la raiz)")
    print("     - el guion en .txt, con las marcas [TXT: ...]")
    print("     - los clips repartidos en parte1, parte2, ...")
    print()
    print("  El guion y la narracion los puede hacer el propio montador:")
    print("     'guion' escribe el guion con Claude, y desde esa misma")
    print("     ventana se genera la voz con ai33.pro.")

    while True:
        print()
        respuesta = _leer(
            "  Enter cuando este listo "
            "('guion' para escribirlo con Claude, 'salir'): ").lower()
        if respuesta in ("salir", "s", "q", "n", "no"):
            raise RuntimeError("Cancelado: la carpeta se queda como esta.")

        if respuesta in ("guion", "g"):
            # perezoso: ui_guion importa este modulo, y arriba seria circular
            from .ui_guion import escribir_guion
            escribir_guion(destino)
            continue

        errores, avisos = revisar(destino)
        _mostrar(errores, avisos)
        if not errores:
            return


def preparar() -> Path:
    """
    Flujo completo: preguntar nombre, crear, esperar a que se llene.

    Si la carpeta ya estaba completa no hace esperar a nadie: monta directo.
    """
    destino, nueva = preguntar_carpeta()
    errores, avisos = revisar(destino)
    if errores:
        if not nueva:
            # a una carpeta recien creada le falta todo; no hace falta decirlo
            print()
            _mostrar(errores, avisos)
        esperar_material(destino)
    else:
        _mostrar([], avisos)
    return destino
