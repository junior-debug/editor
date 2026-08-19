"""
Repara la narracion de un borrador de CapCut ya existente.

Para que sirve
--------------
El escritor antiguo construia el material de la narracion clonando un efecto
de sonido de la biblioteca de CapCut: le cambiaba la ruta a tu MP3 pero se
quedaba con los identificadores del recurso original (effect_id, app_id,
category_name "Favoritos") y lo declaraba como 'extract_music'. CapCut lee
ese material como un recurso gestionado por el y saca la pasarela de Pro
("Extraer audio"), que bloquea la exportacion.

Esto lo arregla EN EL SITIO, sin regenerar el montaje: conserva todos tus
cortes, transiciones, sonidos y retoques.

Uso
---
    python herramientas/reparar_audio.py "<carpeta del borrador>"
    python herramientas/reparar_audio.py "<...>\\draft_content.json"

Sin argumentos, busca en la carpeta de borradores de CapCut y lista los
proyectos afectados.

IMPORTANTE: cierra CapCut antes de ejecutarlo. CapCut mantiene el borrador
en memoria y al cerrarse lo reescribe, deshaciendo la reparacion.
"""
import json
import os
import shutil
import sys
from pathlib import Path

# los recursos de la biblioteca de CapCut viven bajo su carpeta de cache;
# cualquier audio fuera de ahi es un archivo tuyo
MARCA_CACHE = ("capcut/user data/cache", "capcut\\user data\\cache",
               "jianyingpro/user data/cache")

CAMPOS_TEXTO = ("effect_id", "resource_id", "third_resource_id", "pgc_id",
                "pgc_name", "search_id", "request_id", "text_id", "video_id",
                "formula_id", "aigc_history_id", "aigc_item_id",
                "category_id")
CAMPOS_NUM = ("app_id", "team_id", "source_platform")


def es_audio_local(material: dict) -> bool:
    ruta = (material.get("path") or "").replace("\\", "/").lower()
    if not ruta:
        return False
    return not any(m.replace("\\", "/") in ruta for m in MARCA_CACHE)


def reparar_material(m: dict) -> list[str]:
    cambios = []

    if m.get("type") == "extract_music":
        m["type"] = "music"
        cambios.append("type: extract_music -> music")

    if m.get("category_name") != "local":
        cambios.append(f"category_name: {m.get('category_name')!r} -> 'local'")
        m["category_name"] = "local"

    for k in CAMPOS_TEXTO:
        if m.get(k):
            cambios.append(f"{k}: {m[k]!r} -> ''")
            m[k] = ""
    for k in CAMPOS_NUM:
        if m.get(k):
            cambios.append(f"{k}: {m[k]!r} -> 0")
            m[k] = 0

    return cambios


def reparar_borrador(ruta: Path) -> bool:
    archivo = ruta / "draft_content.json" if ruta.is_dir() else ruta
    if not archivo.exists():
        print(f"  no existe {archivo}")
        return False

    doc = json.loads(archivo.read_text(encoding="utf-8"))
    audios = doc.get("materials", {}).get("audios", [])

    total = []
    for m in audios:
        if not es_audio_local(m):
            continue
        cambios = reparar_material(m)
        if cambios:
            total.append((m.get("name") or m.get("path"), cambios))

    if not total:
        print(f"  {archivo.parent.name}: nada que reparar")
        return False

    copia = archivo.with_suffix(".json.bak")
    if not copia.exists():
        shutil.copy2(archivo, copia)
    archivo.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    print(f"  {archivo.parent.name}: reparado")
    for nombre, cambios in total:
        print(f"     {nombre}")
        for c in cambios:
            print(f"        {c}")
    print(f"     copia de seguridad: {copia.name}")
    return True


def carpeta_borradores() -> Path | None:
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return None
    p = Path(local) / "CapCut/User Data/Projects/com.lveditor.draft"
    return p if p.exists() else None


def main():
    if len(sys.argv) > 1:
        objetivo = Path(sys.argv[1])
        if not objetivo.exists():
            print(f"No existe: {objetivo}")
            return 1
        print("Reparando:")
        reparar_borrador(objetivo)
        print()
        print("Abre CapCut y prueba a exportar.")
        return 0

    raiz = carpeta_borradores()
    if raiz is None:
        print(__doc__)
        print("No se ha encontrado la carpeta de borradores de CapCut.")
        print("Pasa la ruta del proyecto como argumento.")
        return 1

    print(f"Borradores en {raiz}\n")
    afectados = []
    for d in sorted(raiz.iterdir()):
        archivo = d / "draft_content.json"
        if not (d.is_dir() and archivo.exists()):
            continue
        try:
            doc = json.loads(archivo.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        for m in doc.get("materials", {}).get("audios", []):
            if es_audio_local(m) and (m.get("type") == "extract_music"
                                      or m.get("effect_id")):
                afectados.append(d)
                break

    if not afectados:
        print("Ningun borrador afectado.")
        return 0

    print("Borradores con la narracion mal declarada:")
    for d in afectados:
        print(f"   {d.name}")
    print()
    print("Para repararlos (con CapCut CERRADO):")
    for d in afectados:
        print(f'   python herramientas/reparar_audio.py "{d}"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
