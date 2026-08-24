"""
De que hacer el proximo video.

Claude busca en internet segun unas reglas del usuario, propone temas, y aqui
se lleva la cuenta de los que ya se han hecho para que no los repita.

**Lo ya hecho no hay que apuntarlo a mano.** Sale de dos sitios que se suman:

- `ideas.json`, donde queda todo lo que se ha propuesto alguna vez, con su
  estado. Sirve para no volver a ofrecer algo que ya se descarto.
- las carpetas de video de MasterTube, de donde se lee la marca [INTRO: ...]
  o la primera frase del guion. Eso cubre los videos hechos antes de que
  existiera este modulo, que si no serian invisibles.

Las reglas son del usuario y viven fuera del repositorio, en
`MasterTube\\perfiles-ideas`, por lo mismo que los perfiles de guion: son
contenido suyo, no codigo. Y por lo mismo hay varias y se eligen en un
desplegable — el dia que abra un segundo canal, sus reglas son otras.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict, field
from datetime import date
from pathlib import Path

from . import proyecto as proy
from .edl import MARCA_INTRO

ARCHIVO = "ideas.json"
CARPETA_REGLAS = "perfiles-ideas"
FABRICA = "oriente-avanza"

# Estados por los que pasa una idea. 'hecha' la pone el montador solo cuando
# se crea la carpeta del video; las otras dos las pone el usuario.
PROPUESTA, ELEGIDA, HECHA, DESCARTADA = ("propuesta", "elegida", "hecha",
                                         "descartada")

REGLAS_FABRICA = """\
Buscas temas para los próximos vídeos del canal de YouTube "Oriente Avanza",
en español de España. El canal trata tecnología, megaestructuras y geopolítica
entre Asia y Occidente.

Qué es un buen tema para este canal:
- Tiene una cifra concreta que sostiene el vídeo entero y se puede decir en
  voz alta: un precio, un récord, unas unidades vendidas, unos metros.
- Es reciente. Algo de las últimas dos o tres semanas, o algo antiguo que
  acaba de cambiar de estado: una fábrica que abre, una cifra que se supera.
- Tiene un contraste: Asia contra Occidente, lo que se creía contra lo que
  resulta ser, el precio de aquí contra el de allí.
- Se puede ilustrar. Si no hay imágenes del asunto, no hay vídeo.

Qué NO sirve:
- Rumores, filtraciones y "se espera que". Hechos con fuente o nada.
- Temas sin cifra, que acaban siendo un vídeo de opinión.
- Lo que ya se ha contado en el canal, salvo que haya pasado algo nuevo de
  verdad; en ese caso dilo tú.
"""


# --------------------------------------------------------------------------
# Las reglas
# --------------------------------------------------------------------------

def carpeta_reglas() -> Path:
    return proy.raiz() / CARPETA_REGLAS


def listar_reglas() -> list[str]:
    base = carpeta_reglas()
    if not base.exists():
        return []
    return sorted(p.stem for p in base.iterdir()
                  if p.is_file() and p.suffix.lower() in (".txt", ".md"))


def cargar_reglas(nombre: str) -> str:
    ruta = carpeta_reglas() / (proy.sanear(nombre) + ".txt")
    if ruta.exists():
        return ruta.read_text(encoding="utf-8")
    return ""


def guardar_reglas(nombre: str, texto: str) -> Path:
    base = carpeta_reglas()
    base.mkdir(parents=True, exist_ok=True)
    ruta = base / (proy.sanear(nombre) + ".txt")
    ruta.write_text(texto.strip() + "\n", encoding="utf-8")
    return ruta


def asegurar_reglas() -> str:
    """Deja escritas las reglas de fabrica si no hay ninguna. Devuelve cual."""
    hay = listar_reglas()
    if hay:
        return hay[0]
    guardar_reglas(FABRICA, REGLAS_FABRICA)
    return FABRICA


# --------------------------------------------------------------------------
# Las ideas
# --------------------------------------------------------------------------

@dataclass
class Idea:
    titular: str
    dato: str = ""          # la cifra que sostiene el video
    porque: str = ""        # por que ahora
    fuente: str = ""
    estado: str = PROPUESTA
    fecha: str = field(default_factory=lambda: date.today().isoformat())
    carpeta: str = ""       # la del video, cuando se hace

    def clave(self) -> str:
        """Para reconocer la misma idea aunque cambie el titular."""
        return _normalizar(self.titular)


def _normalizar(texto: str) -> str:
    import unicodedata
    plano = unicodedata.normalize("NFKD", (texto or "").lower())
    plano = "".join(c for c in plano if not unicodedata.combining(c))
    return " ".join(re.findall(r"[a-z0-9]+", plano))


def archivo() -> Path:
    return proy.raiz() / ARCHIVO


def cargar() -> list[Idea]:
    ruta = archivo()
    if not ruta.exists():
        return []
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except ValueError:
        # un json roto no puede tirar por tierra el trabajo del dia: se avisa
        # devolviendo vacio y el guardado siguiente lo deja bien
        return []
    ideas = []
    for d in datos.get("ideas", []):
        conocidos = {k: v for k, v in d.items()
                     if k in Idea.__dataclass_fields__}
        ideas.append(Idea(**conocidos))
    return ideas


def guardar(ideas: list[Idea]) -> Path:
    ruta = archivo()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps({"ideas": [asdict(i) for i in ideas]},
                               ensure_ascii=False, indent=1),
                    encoding="utf-8")
    return ruta


def anadir(nuevas: list[Idea]) -> tuple[list[Idea], int]:
    """
    Suma las nuevas a las que ya habia, sin repetir.

    Devuelve (todas, cuantas_eran_nuevas). Se compara por el titular
    normalizado: Claude propone lo mismo con otras palabras cada dos por tres,
    pero cuando repite de verdad suele repetir el titular casi igual.
    """
    todas = cargar()
    vistas = {i.clave() for i in todas}
    cuantas = 0
    for idea in nuevas:
        if idea.clave() in vistas or not idea.titular.strip():
            continue
        vistas.add(idea.clave())
        todas.append(idea)
        cuantas += 1
    if cuantas:
        guardar(todas)
    return todas, cuantas


def marcar(titular: str, estado: str, carpeta: str = "") -> list[Idea]:
    todas = cargar()
    clave = _normalizar(titular)
    for idea in todas:
        if idea.clave() == clave:
            idea.estado = estado
            if carpeta:
                idea.carpeta = carpeta
    guardar(todas)
    return todas


# --------------------------------------------------------------------------
# Lo que ya se ha hecho
# --------------------------------------------------------------------------

def temas_de_los_videos() -> list[str]:
    """
    De que iba cada video ya montado, leido de su guion.

    Se coge la marca [INTRO: ...] si la lleva -es literalmente el titular del
    video- y si no, la primera frase, que en este canal es siempre el dato que
    engancha. Asi los videos anteriores a este modulo tambien cuentan.
    """
    base = proy.raiz()
    if not base.exists():
        return []

    temas = []
    for carpeta in sorted(base.iterdir()):
        if not carpeta.is_dir() or not proy.es_proyecto(carpeta):
            continue
        guion = carpeta / "guion.txt"
        if not guion.exists():
            continue
        texto = guion.read_text(encoding="utf-8", errors="replace")

        marca = MARCA_INTRO.search(texto)
        if marca:
            temas.append(f"{carpeta.name}: {marca.group(1).strip()}")
            continue
        primera = next((l.strip() for l in texto.splitlines() if l.strip()), "")
        if primera:
            temas.append(f"{carpeta.name}: {primera[:120]}")
    return temas


def ya_tratado() -> str:
    """El bloque de 'esto ya esta hecho' que se le pasa a Claude."""
    lineas = []
    for tema in temas_de_los_videos():
        lineas.append(f"- {tema}")
    for idea in cargar():
        if idea.estado == DESCARTADA:
            lineas.append(f"- (descartada) {idea.titular}")
        elif idea.estado in (ELEGIDA, HECHA):
            lineas.append(f"- {idea.titular}")
        else:
            lineas.append(f"- (ya propuesta) {idea.titular}")
    return "\n".join(lineas)


# --------------------------------------------------------------------------
# El encargo
# --------------------------------------------------------------------------

MARCA_IDEAS_INICIO = "---IDEAS---"
MARCA_IDEAS_FIN = "---FIN---"


def prompt(reglas: str, cuantas: int = 6) -> str:
    """
    Lo que se le manda a Claude. Reglas primero, contrato al final.

    Mismo orden y mismo motivo que en el guionista: lo ultimo que se lee es
    lo que mejor se respeta, y el contrato solo impone el formato.
    """
    hechos = ya_tratado()
    ya = (f"\nEsto ya está hecho, propuesto o descartado. No lo repitas:\n\n"
          f"{hechos}\n" if hechos else "")

    return f"""\
{reglas.strip() or REGLAS_FABRICA}
{ya}
BUSCA EN INTERNET antes de responder. No propongas de memoria: mira qué ha
pasado estas últimas semanas y comprueba las cifras en su fuente. Si una
cifra no la encuentras publicada, no la pongas.

Dame {cuantas} temas. Devuélvelos en un bloque con esta forma exacta:

{MARCA_IDEAS_INICIO}
TITULAR | el dato | por qué ahora | la fuente
TITULAR | el dato | por qué ahora | la fuente
{MARCA_IDEAS_FIN}

Uno por línea y los cuatro campos separados por barras verticales. El titular
en mayúsculas y corto, como el de un vídeo. El dato, la cifra concreta que
sostiene el vídeo. El porqué, en una frase: qué ha pasado para que toque
ahora. La fuente, el medio y el enlace.

Fuera del bloque dime lo que quieras: cuál te parece el mejor y por qué, o
qué has descartado al buscar.
"""


_RE_BLOQUE = re.compile(
    r"^[ \t]*-{2,}[ \t]*IDEAS[ \t]*-{2,}[ \t]*$(.*?)"
    r"^[ \t]*-{2,}[ \t]*FIN[ \t]*-{2,}[ \t]*$",
    re.S | re.M | re.I)

_RE_ABRE = re.compile(r"^[ \t]*-{2,}[ \t]*IDEAS[ \t]*-{2,}[ \t]*$",
                      re.M | re.I)


def extraer(respuesta: str) -> tuple[list[Idea], str]:
    """
    Separa (ideas, lo que Claude nos cuenta).

    Tolerante a proposito, como el lector de busquedas: si se deja las marcas
    pero las lineas llevan sus barras, se leen igual. Perder seis temas bien
    buscados por un delimitador ausente seria absurdo teniendolos delante.
    """
    encontrado = _RE_BLOQUE.search(respuesta)
    if encontrado:
        crudo, charla = encontrado.group(1), _RE_BLOQUE.sub("\n", respuesta)
    else:
        abierto = _RE_ABRE.search(respuesta)
        if abierto:
            crudo, charla = respuesta[abierto.end():], respuesta[:abierto.start()]
        else:
            # sin marcas: se leen las lineas que tengan pinta de idea
            crudo, charla = respuesta, ""
            if not any(l.count("|") >= 2 for l in respuesta.splitlines()):
                return [], respuesta

    ideas = []
    for linea in crudo.splitlines():
        linea = linea.strip().lstrip("-*•").strip()
        if linea.count("|") < 2:
            continue
        campos = [c.strip() for c in linea.split("|")]
        titular = campos[0].strip(" .")
        if not titular or titular.upper().startswith("TITULAR"):
            continue
        ideas.append(Idea(
            titular=titular,
            dato=campos[1] if len(campos) > 1 else "",
            porque=campos[2] if len(campos) > 2 else "",
            fuente=" | ".join(campos[3:]) if len(campos) > 3 else "",
        ))
    return ideas, charla.strip()
