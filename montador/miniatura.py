"""
La miniatura del video, en tres capas.

Sale de mirar las quince que junior ya ha hecho a mano con ChatGPT. Todas
siguen el mismo sistema:

    capa 3   el texto      dos lineas comparando cifras, la de arriba blanca
                           (la referencia occidental) y la de abajo amarilla
                           (lo chino), en mayusculas y con contorno negro
    capa 2   el personaje  el mismo asiatico de traje oscuro y corbata roja,
                           recortado, a un lado
    capa 1   la escena     bandera china roja tratada en grunge, y el sujeto
                           del video -un coche, un robot, un barco- al otro
                           lado

**Por capas y no de una sola pasada**, aunque el modelo sepa escribir: las
miniaturas de este canal viven de las cifras -9,58 contra 9,32- y un modelo
de imagen las escribe mal cada pocas veces. Un decimal cambiado en la
miniatura es una promesa falsa en la portada del video. Compuesto aqui, el
texto sale siempre exacto y siempre igual.

Y el personaje **se genera una vez y se guarda**: es lo que hace que las
miniaturas del canal se reconozcan entre si, y ademas no se paga en cada
video. Se describe en vez de nombrarlo -"un asiatico que se parezca al
presidente chino"-, que es como lo pide junior a mano y como sale sin
tropezar con la politica de parecidos de nadie.

La clave de OpenAI no esta en el repositorio: se lee de MasterTube\\openai.key
o de la variable OPENAI_API_KEY, igual que la de ai33.pro. Ojo, que la API se
paga aparte de ChatGPT Plus: una cuenta con Plus puede tener la API a cero.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import proyecto as proy

API = "https://api.openai.com/v1/images/generations"
MODELO = "gpt-image-2"

# 1280x720 es lo que pide YouTube. Se genera en el tamano ancho que da el
# modelo y se recorta: pedir el 16:9 exacto no es una opcion suya.
ANCHO, ALTO = 1280, 720
TAMANO_API = "1536x1024"

NOMBRE_PERSONAJE = "personaje.png"
NOMBRE_ESCENA = "miniatura_escena.png"
NOMBRE_FINAL = "miniatura.png"


class SinClave(RuntimeError):
    """No hay clave de OpenAI donde buscarla."""


class SinSaldo(RuntimeError):
    """La cuenta de API no tiene saldo o ha topado su limite de gasto."""


# --------------------------------------------------------------------------
# Estilo
# --------------------------------------------------------------------------

@dataclass
class EstiloMiniatura:
    """
    Los numeros del estilo, sacados de las miniaturas ya hechas.

    Nada de esto es invencion: los colores y la estructura salen de las tres
    que se miraron (video catorce, quince y noveno). Al cambiar el estilo,
    tocar aqui.
    """
    fuente: str = "impact.ttf"
    color_arriba: tuple = (255, 255, 255)      # la referencia occidental
    color_abajo: tuple = (255, 214, 0)         # lo chino, en amarillo
    contorno: tuple = (0, 0, 0)
    grosor_contorno: int = 14
    # el texto ocupa poco mas de la mitad del ancho: la otra mitad es para el
    # personaje o para el sujeto del video
    ancho_texto: float = 0.62
    margen: int = 40
    interlineado: float = 1.06
    # de donde a donde puede crecer la letra hasta que las dos lineas quepan
    cuerpo_maximo: int = 150
    cuerpo_minimo: int = 40
    personaje_alto: float = 1.0     # proporcion del alto de la miniatura
    personaje_lado: str = "izquierda"


ESTILO_MINIATURA = EstiloMiniatura()


# --------------------------------------------------------------------------
# La clave
# --------------------------------------------------------------------------

def clave() -> str:
    """
    La clave de OpenAI, de la variable de entorno o de MasterTube.

    Mismo sitio y mismas razones que la de ai33.pro: fuera del repositorio,
    en un archivo .key que .gitignore ya cubre.
    """
    directa = os.environ.get("OPENAI_API_KEY")
    if directa:
        return directa.strip()

    archivo = proy.raiz() / "openai.key"
    if archivo.exists():
        leida = archivo.read_text(encoding="utf-8").strip()
        if leida:
            return leida

    raise SinClave(
        f"No hay clave de OpenAI.\n"
        f"Pegala en {archivo}, o ponla en la variable OPENAI_API_KEY.")


# --------------------------------------------------------------------------
# Generar con la API
# --------------------------------------------------------------------------

def _pedir_imagen(prompt: str, transparente: bool = False,
                  tamano: str = TAMANO_API) -> bytes:
    cuerpo = {"model": MODELO, "prompt": prompt, "size": tamano, "n": 1}
    if transparente:
        # el personaje se pega encima de la escena, asi que tiene que venir
        # sin fondo; recortarlo despues nunca sale limpio en el pelo
        cuerpo["background"] = "transparent"
        cuerpo["output_format"] = "png"

    peticion = urllib.request.Request(
        API, data=json.dumps(cuerpo).encode(),
        headers={"Authorization": f"Bearer {clave()}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(peticion, timeout=600) as respuesta:
            datos = json.load(respuesta)
    except urllib.error.HTTPError as exc:
        detalle = exc.read().decode(errors="replace")
        if "billing_hard_limit" in detalle or "insufficient_quota" in detalle:
            raise SinSaldo(
                "La cuenta de API de OpenAI no tiene saldo. Se paga aparte "
                "de ChatGPT Plus: entra en platform.openai.com, Billing, y "
                "añade credito o sube el limite.") from exc
        raise RuntimeError(f"OpenAI ha devuelto {exc.code}: "
                           f"{detalle[:300]}") from exc

    primero = datos["data"][0]
    if primero.get("b64_json"):
        return base64.b64decode(primero["b64_json"])
    with urllib.request.urlopen(primero["url"], timeout=300) as r:
        return r.read()


def prompt_escena(sujeto: str, ambiente: str = "") -> str:
    """
    El encargo de la capa de fondo.

    Se pide **sin texto y sin personas**: el texto se compone despues con las
    cifras exactas, y la persona es una capa aparte que no cambia entre
    videos. Pedirle al modelo lo que ya tenemos resuelto solo introduce
    variaciones.
    """
    lado = ("derecha" if ESTILO_MINIATURA.personaje_lado == "izquierda"
            else "izquierda")
    return (
        f"Fondo para una miniatura de YouTube, formato apaisado 16:9, estilo "
        f"de prensa sensacionalista de tecnologia.\n\n"
        f"En la mitad {lado} de la imagen, como protagonista: {sujeto}. "
        f"Iluminacion dramatica de estudio, mucho contraste, colores muy "
        f"saturados, aspecto de fotografia retocada y de alta definicion.\n\n"
        f"De fondo, {ambiente or 'una bandera de China ondeando, roja intensa '
                                 'con estrellas amarillas'}, con textura "
        f"grunge rasgada y viñeteado oscuro en los bordes.\n\n"
        f"La otra mitad de la imagen, mas despejada y algo mas oscura, para "
        f"poder poner encima una figura recortada y texto.\n\n"
        f"MUY IMPORTANTE: no escribas ningun texto, ninguna letra y ningun "
        f"numero en la imagen. Tampoco dibujes ninguna persona."
    )


def prompt_personaje() -> str:
    """
    El encargo del personaje. Se usa **una sola vez** y se guarda.

    Se describe en vez de nombrarlo, que es como lo pide junior a mano: asi
    sale sin tropezar con ninguna politica de parecidos, y ademas queda un
    personaje propio del canal en vez de una persona concreta.
    """
    return (
        "Retrato de medio cuerpo, recortado sobre fondo transparente, de un "
        "hombre asiatico de unos setenta anos que recuerde al tipo de un "
        "presidente chino: pelo negro peinado hacia atras, cara ancha, "
        "expresion serena con una sonrisa leve, mirando ligeramente hacia "
        "arriba. Traje oscuro, camisa blanca y corbata roja. Iluminacion de "
        "estudio con mucho contraste, aspecto de fotografia retocada de alta "
        "definicion. Sin fondo, sin texto y sin ningun otro elemento."
    )


def generar_escena(sujeto: str, destino: Path, ambiente: str = "") -> Path:
    """Genera la capa de fondo del video y la guarda."""
    destino = Path(destino)
    destino.write_bytes(_pedir_imagen(prompt_escena(sujeto, ambiente)))
    return destino


def generar_personaje(destino: Path) -> Path:
    """
    Genera el personaje del canal, con fondo transparente.

    Se hace una vez y se reutiliza en todos los videos: es lo que hace que
    las miniaturas se reconozcan entre si, y no tiene sentido pagarlo cada
    vez para que ademas salga distinto.
    """
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(_pedir_imagen(prompt_personaje(), transparente=True,
                                      tamano="1024x1024"))
    return destino


def personaje_del_canal(crear: bool = False) -> Path | None:
    """
    El PNG del personaje, guardado junto a las plantillas de miniatura.

    Vive en MasterTube y no en la carpeta del video porque es del canal
    entero, como los perfiles de guion.
    """
    ruta = proy.raiz() / "miniatura" / NOMBRE_PERSONAJE
    if ruta.exists():
        return ruta
    if crear:
        return generar_personaje(ruta)
    return None


# --------------------------------------------------------------------------
# Componer
# --------------------------------------------------------------------------

def _fuente(cuerpo: int):
    from PIL import ImageFont
    nombre = ESTILO_MINIATURA.fuente
    candidatos = [Path(nombre)]
    ventana = os.environ.get("WINDIR")
    if ventana:
        candidatos.append(Path(ventana) / "Fonts" / nombre)
    for c in candidatos:
        if c.exists():
            return ImageFont.truetype(str(c), cuerpo)
    return ImageFont.load_default(cuerpo)


def _cuerpo_que_cabe(lineas: list[str], ancho_max: int, alto_max: int) -> int:
    """
    El tamano de letra mas grande con el que las dos lineas caben.

    Se busca a la baja en vez de fijar un tamano porque los textos no miden
    lo mismo: 'BOLT: 9,58' y 'ESTE BYD: 25.400 EUROS' no pueden ir igual de
    grandes, y recortar la frase seria peor que encogerla.
    """
    from PIL import ImageDraw, Image
    lienzo = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    for cuerpo in range(ESTILO_MINIATURA.cuerpo_maximo,
                        ESTILO_MINIATURA.cuerpo_minimo - 1, -2):
        fuente = _fuente(cuerpo)
        anchos, altos = [], []
        for linea in lineas:
            caja = lienzo.textbbox((0, 0), linea, font=fuente,
                                   stroke_width=ESTILO_MINIATURA.grosor_contorno)
            anchos.append(caja[2] - caja[0])
            altos.append(caja[3] - caja[1])
        if (max(anchos) <= ancho_max
                and sum(altos) * ESTILO_MINIATURA.interlineado <= alto_max):
            return cuerpo
    return ESTILO_MINIATURA.cuerpo_minimo


def componer(escena: Path, lineas: list[str], destino: Path,
             personaje: Path | None = None) -> Path:
    """
    Junta las tres capas y deja la miniatura lista para subir.

    'lineas' son las dos frases del texto: la primera sale blanca y la
    segunda amarilla, que es la comparacion que hace el canal.
    """
    from PIL import Image, ImageDraw

    fondo = Image.open(escena).convert("RGBA")
    # se recorta al 16:9 por el centro: el modelo entrega 3:2 y estirarlo
    # deformaria justo lo que se ha pedido con detalle
    objetivo = ANCHO / ALTO
    ancho, alto = fondo.size
    if ancho / alto > objetivo:
        nuevo = int(alto * objetivo)
        fondo = fondo.crop(((ancho - nuevo) // 2, 0,
                            (ancho - nuevo) // 2 + nuevo, alto))
    else:
        nuevo = int(ancho / objetivo)
        fondo = fondo.crop((0, (alto - nuevo) // 2,
                            ancho, (alto - nuevo) // 2 + nuevo))
    fondo = fondo.resize((ANCHO, ALTO), Image.LANCZOS)

    if personaje and Path(personaje).exists():
        figura = Image.open(personaje).convert("RGBA")
        altura = int(ALTO * ESTILO_MINIATURA.personaje_alto)
        ancho_fig = int(figura.width * altura / figura.height)
        figura = figura.resize((ancho_fig, altura), Image.LANCZOS)
        x = 0 if ESTILO_MINIATURA.personaje_lado == "izquierda" \
            else ANCHO - ancho_fig
        fondo.alpha_composite(figura, (x, ALTO - altura))

    lineas = [l.strip().upper() for l in lineas if l and l.strip()][:2]
    if lineas:
        _pintar_texto(fondo, lineas)

    destino = Path(destino)
    fondo.convert("RGB").save(destino, "PNG")
    return destino


def _pintar_texto(imagen, lineas: list[str]) -> None:
    from PIL import ImageDraw

    margen = ESTILO_MINIATURA.margen
    ancho_max = int(ANCHO * ESTILO_MINIATURA.ancho_texto) - margen
    alto_max = int(ALTO * 0.55)
    cuerpo = _cuerpo_que_cabe(lineas, ancho_max, alto_max)
    fuente = _fuente(cuerpo)
    lienzo = ImageDraw.Draw(imagen)

    # el texto va del lado contrario al personaje, arriba: es donde lo pone
    # junior y ademas es lo que se ve en el movil sin abrir el video
    izquierda = ESTILO_MINIATURA.personaje_lado != "izquierda"
    colores = [ESTILO_MINIATURA.color_arriba, ESTILO_MINIATURA.color_abajo]

    y = margen
    for i, linea in enumerate(lineas):
        caja = lienzo.textbbox((0, 0), linea, font=fuente,
                               stroke_width=ESTILO_MINIATURA.grosor_contorno)
        ancho_linea = caja[2] - caja[0]
        x = margen if izquierda else ANCHO - margen - ancho_linea
        lienzo.text((x, y), linea, font=fuente,
                    fill=colores[i % len(colores)],
                    stroke_width=ESTILO_MINIATURA.grosor_contorno,
                    stroke_fill=ESTILO_MINIATURA.contorno)
        y += int((caja[3] - caja[1]) * ESTILO_MINIATURA.interlineado)
