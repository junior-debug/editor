"""
Perfiles de guion: las reglas con las que Claude escribe.

Equivalen a las instrucciones de un proyecto de claude.ai, pero en local. Las
de claude.ai no se pueden leer desde fuera —no hay API para los proyectos—,
asi que se pegan una vez aqui y se reutilizan en todos los videos.

Viven en MasterTube\\perfiles como .txt sueltos: un archivo por proyecto, y el
nombre del archivo es el nombre que sale en el desplegable. Estan ahi y no
dentro del repositorio porque son contenido del usuario, no codigo.
"""
from __future__ import annotations

from pathlib import Path

from . import proyecto as proy

# reglas de fabrica: lo que habia escrito a mano en guionista.py antes de que
# hubiera perfiles. Sirve de ejemplo y de punto de partida para editar.
FABRICA = "oriente-avanza"

TEXTO_FABRICA = """\
Escribes el guion de un vídeo del canal de YouTube "Oriente Avanza", en \
español de España. El canal trata tecnología, megaestructuras y geopolítica \
entre Asia y Occidente.

Cómo escribe el canal:
- Es locución para voz en off, no un artículo. Frases cortas, en presente, \
que se puedan leer en voz alta del tirón. Nada de incisos largos.
- Empieza con un dato concreto que enganche, nunca con "en este vídeo vamos \
a ver" ni presentaciones del canal.
- Datos verificables y concretos: cifras, fechas, nombres propios, lugares. \
Si no estás seguro de un dato, escribe el hecho sin la cifra antes que \
inventarla.
- Sin saludos, sin despedidas, sin "suscríbete".
"""


def carpeta() -> Path:
    return proy.raiz() / "perfiles"


def _ruta(nombre: str) -> Path:
    return carpeta() / (proy.sanear(nombre) + ".txt")


def listar() -> list[str]:
    base = carpeta()
    if not base.exists():
        return []
    return sorted(p.stem for p in base.iterdir()
                  if p.is_file() and p.suffix.lower() in (".txt", ".md"))


def cargar(nombre: str) -> str:
    ruta = _ruta(nombre)
    if not ruta.exists():
        alterno = ruta.with_suffix(".md")
        if alterno.exists():
            ruta = alterno
        else:
            raise RuntimeError(f"No hay ningun perfil llamado '{nombre}'")
    return ruta.read_text(encoding="utf-8")


def guardar(nombre: str, texto: str) -> Path:
    nombre = proy.sanear(nombre)
    if not nombre:
        raise RuntimeError("El perfil necesita un nombre.")

    base = carpeta()
    base.mkdir(parents=True, exist_ok=True)
    destino = base / (nombre + ".txt")
    destino.write_text(texto.strip() + "\n", encoding="utf-8")
    return destino


def asegurar() -> list[str]:
    """
    Devuelve los perfiles disponibles, creando el de fabrica si no hay ninguno.

    Asi el desplegable nunca sale vacio la primera vez, y el usuario tiene un
    ejemplo delante de como se escribe uno.
    """
    hay = listar()
    if hay:
        return hay
    guardar(FABRICA, TEXTO_FABRICA)
    return listar()
