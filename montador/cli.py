"""
Interfaz de linea de comandos.

    python -m montador montar  --narracion narracion.mp3 \
                               --clips clips/ \
                               --guion guion.txt \
                               --proyecto decimo_video

    python -m montador alinear --narracion narracion.mp3 -o alineacion.json
    python -m montador edl     ...            (solo genera el EDL, no escribe)
    python -m montador render  --edl edl.json -o salida.mp4
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import alineacion as al
from . import edl as edl_mod
from . import proyecto as proy
from .config import ESTILO
from .capcut.escritor import EscritorCapCut

RAIZ = Path(__file__).resolve().parent.parent
PROTOTIPOS = RAIZ / "plantillas" / "prototipos_9.2.8.json"


def borradores_por_defecto() -> Path:
    """Carpeta de borradores de CapCut en Windows."""
    local = os.environ.get("LOCALAPPDATA")
    if local:
        p = Path(local) / "CapCut/User Data/Projects/com.lveditor.draft"
        if p.exists():
            return p
    return Path.cwd() / "borradores"


EXT_AUDIO = proy.EXTENSIONES_AUDIO


def autodetectar(args) -> None:
    """
    Rellena --narracion, --guion y --transcripcion mirando dentro de --clips.

    Evita tener que teclear rutas largas con espacios y tildes, que en
    PowerShell es la principal fuente de errores.
    """
    raiz = Path(args.clips)

    if not getattr(args, "narracion", None):
        audios = [p for p in raiz.iterdir()
                  if p.is_file() and p.suffix.lower() in EXT_AUDIO]
        if len(audios) == 1:
            args.narracion = str(audios[0])
            print(f"  narracion detectada : {audios[0].name}")
        elif not audios:
            raise RuntimeError(
                f"No hay ningun archivo de audio en {raiz}.\n"
                f"Deja ahi la narracion, o indicala con --narracion.")
        else:
            nombres = "\n    ".join(p.name for p in audios)
            raise RuntimeError(
                f"Hay varios audios en {raiz}:\n    {nombres}\n"
                f"Indica cual con --narracion.")

    if not getattr(args, "guion", None):
        candidatos = [p for p in raiz.iterdir()
                      if p.is_file() and p.suffix.lower() == ".txt"
                      and p.stem.lower() not in ("trans", "busquedas")]
        preferido = [p for p in candidatos if p.stem.lower() == "guion"]
        elegido = (preferido or candidatos or [None])[0]
        if elegido:
            args.guion = str(elegido)
            print(f"  guion detectado     : {elegido.name}")

    if not getattr(args, "transcripcion", None):
        trans = raiz / "trans.json"
        if trans.exists():
            args.transcripcion = str(trans)
        elif not getattr(args, "guardar_transcripcion", None):
            # la primera vez se guarda sola, para que la segunda sea instantanea
            args.guardar_transcripcion = str(trans)


def _alinear(args) -> al.Alineacion:
    if args.transcripcion:
        a = al.Alineacion.cargar(Path(args.transcripcion))
        print(f"  alineacion cargada: {len(a.palabras)} palabras")
    else:
        print(f"  transcribiendo con whisper ({args.modelo})...")
        a = al.transcribir(Path(args.narracion), modelo=args.modelo,
                           idioma=args.idioma,
                           dispositivo=args.dispositivo,
                           computo=args.computo)
        print(f"  {len(a.palabras)} palabras")
        if args.guardar_transcripcion:
            a.guardar(Path(args.guardar_transcripcion))
            print(f"  transcripcion guardada en {args.guardar_transcripcion}")
    return a


def _construir_edl(args) -> edl_mod.EDL:
    if not args.clips:
        # sin --clips se pregunta por el nombre y se trabaja dentro de
        # MasterTube: es el camino del doble clic en montar.bat
        args.clips = str(proy.preparar())
        print()
    autodetectar(args)
    a = _alinear(args)
    pausas = a.calcular_pausas(ESTILO.corte.pausa_minima_s)
    print(f"  {len(pausas)} pausas aprovechables")

    guion = ""
    if args.guion:
        guion = Path(args.guion).read_text(encoding="utf-8")

    catalogo = None
    if PROTOTIPOS.exists():
        p = json.loads(PROTOTIPOS.read_text(encoding="utf-8"))
        catalogo = {t["effect_id"]: t for t in p["catalogo_transiciones"]}

    entradas = None
    if args.entradas:
        entradas = [float(x) for x in args.entradas.split(",")]

    e = edl_mod.construir(
        duracion_s=a.duracion_s, pausas=pausas,
        raiz_clips=Path(args.clips), narracion=Path(args.narracion).resolve(),
        guion=guion, entradas_s=entradas, estilo=ESTILO,
        catalogo_transiciones=catalogo)
    return e


def cmd_alinear(args):
    if not args.narracion:
        raise RuntimeError("Indica el audio con --narracion")
    a = _alinear(args)
    a.guardar(Path(args.salida))
    print(f"Alineacion escrita en {args.salida}")


def cmd_edl(args):
    e = _construir_edl(args)
    e.guardar(Path(args.salida))
    print()
    print(e.resumen())
    print()
    print(f"EDL escrito en {args.salida}")


def cmd_montar(args):
    if not args.clips:
        # se adelanta a _construir_edl para que las preguntas salgan antes
        # del "1/3" y no en mitad del proceso
        args.clips = str(proy.preparar())
        print()

    carpeta_video = Path(args.clips)
    if not args.proyecto:
        args.proyecto = proy.nombre_proyecto(carpeta_video)
    if not args.guardar_edl:
        # junto al material: es lo que permite comparar despues el montaje
        # generado con la version retocada a mano
        args.guardar_edl = str(carpeta_video / "edl.json")

    print(f"     carpeta  : {carpeta_video}")
    print(f"     proyecto : {args.proyecto}")
    print()
    print("1/3  alineando narracion")
    e = _construir_edl(args)
    print()
    print("2/3  EDL construido")
    print("     " + e.resumen().replace("\n", "\n     "))
    if args.guardar_edl:
        e.guardar(Path(args.guardar_edl))

    print()
    print("3/3  escribiendo borrador de CapCut")
    escritor = EscritorCapCut(PROTOTIPOS)
    escritor.tipo_audio = args.tipo_audio
    carpeta = Path(args.borradores) if args.borradores \
        else borradores_por_defecto()
    destino = escritor.escribir(e, carpeta, args.proyecto)

    print(f"     {destino}")
    print()
    print("Listo. Abre CapCut y busca el proyecto "
          f"'{args.proyecto}' en la lista de borradores.")


def cmd_guion(args):
    if args.clips:
        carpeta = Path(args.clips)
        if not carpeta.exists():
            raise RuntimeError(f"No existe la carpeta {carpeta}")
    else:
        # aqui no se espera a que la carpeta este llena: el guion es
        # justamente una de las cosas que aun no estan dentro
        carpeta, _ = proy.preguntar_carpeta()

    if args.auto:
        destino = _guion_de_un_tiron(carpeta, args)
    else:
        from .ui_guion import escribir_guion
        destino = escribir_guion(carpeta, args.partes, args.reglas)

    if destino:
        print(f"Guion guardado en {destino}")
    else:
        print("No se ha guardado ningun guion.")


def _guion_de_un_tiron(carpeta, args):
    """
    Escribe el guion entero sin preguntar nada, por consola.

    La ventana conversa, que es como trabaja el usuario. Esto es para cuando
    el perfil son solo reglas de estilo, sin mecanica por pasos, y lo unico
    que se quiere es el texto.
    """
    from . import guionista as gui
    from . import perfiles as perf

    tema = args.auto.strip()
    reglas = perf.cargar(args.reglas) if args.reglas else ""
    partes = args.partes or len(proy.partes_de(carpeta)) or 4

    print(f"  tema   : {tema}")
    print(f"  reglas : {args.reglas or 'las de por defecto'}")
    print(f"  partes : {partes}")
    print()

    escritas = gui.generar(
        tema, args.minutos, partes, trabajo=carpeta, reglas=reglas,
        avance=lambda n, total, texto: print(
            f"  parte {n} de {total}: {len(texto.split())} palabras"))

    return gui.guardar(carpeta, gui.unir(escritas))


def cmd_voz(args):
    from . import voz

    if args.clips:
        carpeta = Path(args.clips)
        if not carpeta.exists():
            raise RuntimeError(f"No existe la carpeta {carpeta}")
    else:
        carpeta, _ = proy.preguntar_carpeta()

    guiones = [p for p in carpeta.iterdir()
               if p.is_file() and p.suffix.lower() == ".txt"
               and p.stem.lower() not in ("trans", "guion_anterior")]
    preferido = [p for p in guiones if p.stem.lower() == "guion"]
    elegido = (preferido or guiones or [None])[0]
    if not elegido:
        raise RuntimeError(f"No hay ningun guion .txt en {carpeta}")

    texto = voz.texto_locutable(elegido.read_text(encoding="utf-8"))
    print(f"  guion    : {elegido.name} ({len(texto)} caracteres)")
    print(f"  voz      : {args.voz or voz.NOMBRE_VOZ}")
    print(f"  creditos : {voz.creditos()}")
    print()

    destino = voz.narrar(
        elegido.read_text(encoding="utf-8"), carpeta,
        voz=args.voz, velocidad=args.velocidad,
        avance=lambda pct, est: print(f"  {est} {pct} %"))

    print()
    print(f"Narracion guardada en {destino}")


def cmd_render(args):
    from .render import render_ffmpeg
    e = edl_mod.EDL.cargar(Path(args.edl))
    render_ffmpeg(e, Path(args.salida), borrador=args.borrador,
                  carpeta_sfx=Path(args.sfx) if args.sfx else None)


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="montador",
        description="Monta un borrador de CapCut a partir de la narracion, "
                    "el guion y las carpetas de clips.")
    sub = ap.add_subparsers(dest="comando", required=True)

    def comunes(p, con_clips=True):
        p.add_argument("--narracion",
                       help="audio de la locucion. Si se omite, se busca el "
                            "unico archivo de audio dentro de --clips")
        if con_clips:
            p.add_argument("--clips",
                           help="carpeta con subcarpetas parte1, parte2, ... "
                                "Si se omite, se pregunta el nombre y se "
                                "trabaja dentro de MasterTube")
            p.add_argument("--guion", help="guion con marcas [TXT: ...]")
            p.add_argument("--entradas",
                           help="segundos en que entra cada parte, "
                                "separados por comas (por defecto, repartidas)")
        p.add_argument("--transcripcion",
                       help="usar una alineacion ya generada en vez de whisper")
        p.add_argument("--guardar-transcripcion",
                       help="guardar la alineacion para reutilizarla")
        p.add_argument("--modelo", default="medium",
                       help="modelo de whisper (tiny/base/small/medium/large-v3)")
        p.add_argument("--idioma", default="es")
        p.add_argument("--dispositivo", default="auto",
                       choices=["auto", "cpu", "cuda"],
                       help="donde corre whisper. 'auto' intenta GPU y cae a "
                            "CPU si faltan las librerias de CUDA")
        p.add_argument("--computo",
                       help="precision de whisper (int8, float16, float32). "
                            "Por defecto int8 en CPU y float16 en GPU")

    p = sub.add_parser("alinear", help="solo transcribir y alinear")
    comunes(p, con_clips=False)
    p.set_defaults(clips=None, guion=None, entradas=None)
    p.add_argument("-o", "--salida", default="alineacion.json")
    p.set_defaults(func=cmd_alinear)

    p = sub.add_parser("edl", help="construir el EDL sin escribir el borrador")
    comunes(p)
    p.add_argument("-o", "--salida", default="edl.json")
    p.set_defaults(func=cmd_edl)

    p = sub.add_parser("montar", help="EDL + borrador de CapCut")
    comunes(p)
    p.add_argument("--proyecto",
                   help="nombre del borrador que veras en CapCut "
                        "(por defecto, el de la carpeta + _auto)")
    p.add_argument("--borradores",
                   help="carpeta de borradores de CapCut "
                        "(por defecto se detecta sola en Windows)")
    p.add_argument("--guardar-edl")
    p.add_argument("--tipo-audio", default="music",
                   choices=["music", "extract_music"],
                   help="como se declara la narracion en el borrador. "
                        "'music' = audio importado (por defecto). Si CapCut "
                        "no carga el audio, prueba 'extract_music'")
    p.set_defaults(func=cmd_montar)

    p = sub.add_parser("guion", help="escribir el guion con Claude")
    p.add_argument("--clips",
                   help="carpeta del video. Si se omite, se pregunta el "
                        "nombre dentro de MasterTube")
    p.add_argument("--partes", type=int, default=0,
                   help="en cuantas partes se escribe (por defecto, tantas "
                        "como carpetas parteN haya)")
    p.add_argument("--reglas", default="",
                   help="perfil de reglas a usar, de MasterTube\\perfiles")
    p.add_argument("--auto", default="", metavar="TEMA",
                   help="escribirlo de un tiron sobre ese tema, sin ventana "
                        "y sin preguntar nada")
    p.add_argument("--minutos", type=float, default=13,
                   help="duracion buscada del video, solo con --auto")
    p.set_defaults(func=cmd_guion)

    p = sub.add_parser("voz", help="narrar el guion con ai33.pro")
    p.add_argument("--clips",
                   help="carpeta del video. Si se omite, se pregunta el "
                        "nombre dentro de MasterTube")
    p.add_argument("--voz", default="",
                   help="id de voz de ai33.pro (por defecto, Narrador v2)")
    p.add_argument("--velocidad", type=float, default=0.0,
                   help="0.5 a 1.5 (por defecto 1.0)")
    p.set_defaults(func=cmd_voz)

    p = sub.add_parser("render", help="renderizar un EDL con ffmpeg")
    p.add_argument("--edl", required=True)
    p.add_argument("-o", "--salida", default="salida.mp4")
    p.add_argument("--borrador", action="store_true",
                   help="480p ultrafast para revisar rapido")
    p.add_argument("--sfx",
                   help="carpeta con los efectos de sonido en local "
                        "(el render de ffmpeg no accede a la libreria "
                        "de CapCut)")
    p.set_defaults(func=cmd_render)

    args = ap.parse_args(argv)
    try:
        args.func(args)
    except RuntimeError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
