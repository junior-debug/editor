"""
Extrae prototipos de un draft_content.json real de CapCut y los guarda en
plantillas/prototipos_<version>.json.

El generador NO construye los objetos JSON de CapCut desde cero: clona estos
prototipos y sustituye solo los campos que cambian (id, path, timeranges).
Es la unica forma robusta de sobrevivir a un formato no documentado.

Uso:
    python herramientas/extraer_prototipos.py <draft_content.json> [salida.json]
"""
import json
import sys
from pathlib import Path


def indexar(materiales):
    idx = {}
    for categoria, lista in materiales.items():
        if isinstance(lista, list):
            for obj in lista:
                if isinstance(obj, dict) and "id" in obj:
                    idx[obj["id"]] = (categoria, obj)
    return idx


def vaciar_documento(doc):
    """Copia el nivel superior sin tracks ni materiales."""
    base = {k: v for k, v in doc.items() if k not in ("tracks", "materials")}
    base["tracks"] = []
    base["materials"] = {k: ([] if isinstance(v, list) else v)
                         for k, v in doc["materials"].items()}
    base["duration"] = 0
    return base


def primer_segmento(doc, tipo_pista, con=None, sin=None, materiales_idx=None):
    for pista in doc["tracks"]:
        if pista["type"] != tipo_pista:
            continue
        for seg in pista["segments"]:
            cats = {materiales_idx[r][0] for r in seg["extra_material_refs"]
                    if r in materiales_idx}
            if con and not con <= cats:
                continue
            if sin and sin & cats:
                continue
            return seg, pista
    return None, None


def main():
    origen = Path(sys.argv[1])
    doc = json.loads(origen.read_text(encoding="utf-8"))
    idx = indexar(doc["materials"])
    M = doc["materials"]

    proto = {
        "version_capcut": doc.get("new_version") or doc.get("version"),
        "plataforma": doc.get("platform"),
        "documento_base": vaciar_documento(doc),
        "segmentos": {},
        "materiales": {},
        "auxiliares": {},
        "catalogo_transiciones": [],
        "catalogo_sonidos": [],
    }

    # --- segmento de video sin transicion (el caso general) ---
    seg_v, _ = primer_segmento(doc, "video", sin={"transitions"}, materiales_idx=idx)
    proto["segmentos"]["video"] = seg_v
    proto["materiales"]["video"] = idx[seg_v["material_id"]][1]

    # auxiliares que cuelgan de un segmento de video
    for ref in seg_v["extra_material_refs"]:
        cat, obj = idx[ref]
        proto["auxiliares"][cat] = obj

    # --- segmento de audio ---
    seg_a = None
    for pista in doc["tracks"]:
        if pista["type"] == "audio" and len(pista["segments"]) > 3:
            seg_a = pista["segments"][0]
            break
    if seg_a is None:
        for pista in doc["tracks"]:
            if pista["type"] == "audio":
                seg_a = pista["segments"][0]
                break
    proto["segmentos"]["audio"] = seg_a
    proto["materiales"]["audio"] = idx[seg_a["material_id"]][1]

    # Material de audio LOCAL (la narracion), distinto del sfx de libreria.
    # Sin esto la narracion heredaba effect_id/app_id de un efecto de sonido
    # de CapCut apuntando a un mp3 del disco: un material hibrido que hace
    # que CapCut lo trate como recurso Pro y bloquee la exportacion.
    for a in M.get("audios", []):
        if a.get("type") in ("extract_music", "music") and \
                a.get("category_name") == "local":
            proto["materiales"]["audio_local"] = a
            break
    for ref in seg_a["extra_material_refs"]:
        cat, obj = idx[ref]
        proto["auxiliares"].setdefault("audio_" + cat, obj)

    # --- rotulos ---
    # Los rotulos de junior no son textos planos: son plantillas de texto de
    # CapCut (text_templates) con uno o varios huecos de texto dentro. Se
    # extrae cada uno como un "bundle" autocontenido: el segmento, la
    # plantilla, los materiales de texto que cuelgan de ella y los auxiliares.
    # El generador clona el bundle, regenera los ids manteniendo las
    # referencias internas, y sustituye el contenido de los huecos.
    proto["rotulos"] = []
    textos = {t["id"]: t for t in M.get("texts", [])}
    for pista in doc["tracks"]:
        if pista["type"] != "text":
            continue
        for seg_t in pista["segments"]:
            cat, mat = idx.get(seg_t["material_id"], (None, None))
            if cat != "text_templates":
                continue
            huecos = []
            for r in mat.get("text_info_resources", []):
                tm = textos.get(r.get("text_material_id"))
                if not tm:
                    continue
                try:
                    contenido = json.loads(tm.get("content") or "")["text"]
                except (ValueError, TypeError, KeyError):
                    contenido = tm.get("content") or ""
                huecos.append({
                    "text_material_id": tm["id"],
                    "texto_actual": contenido,
                })
            aux = {}
            for ref in seg_t["extra_material_refs"]:
                c2, o2 = idx.get(ref, (None, None))
                if c2:
                    aux.setdefault(c2, []).append(o2)
            proto["rotulos"].append({
                "nombre": mat.get("name"),
                "effect_id": mat.get("effect_id"),
                "n_huecos": len(huecos),
                "duracion_us": seg_t["target_timerange"]["duration"],
                "segmento": seg_t,
                "plantilla": mat,
                "materiales_texto": [textos[h["text_material_id"]]
                                     for h in huecos],
                "huecos": huecos,
                "auxiliares": aux,
            })

    # --- catalogo de transiciones (deduplicado por effect_id) ---
    vistos = {}
    for t in M.get("transitions", []):
        clave = t["effect_id"]
        if clave not in vistos:
            vistos[clave] = dict(t)
            vistos[clave]["_usos"] = 0
        vistos[clave]["_usos"] += 1
    proto["catalogo_transiciones"] = sorted(
        vistos.values(), key=lambda x: -x["_usos"])

    # --- catalogo de sonidos (los que no son la narracion) ---
    vistos_a = {}
    for a in M.get("audios", []):
        if a.get("type") in ("extract_music",):
            continue
        clave = a.get("name")
        if clave not in vistos_a:
            vistos_a[clave] = dict(a)
            vistos_a[clave]["_usos"] = 0
        vistos_a[clave]["_usos"] += 1
    proto["catalogo_sonidos"] = sorted(
        vistos_a.values(), key=lambda x: -x["_usos"])

    salida = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(
        "plantillas/prototipos.json")
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(json.dumps(proto, ensure_ascii=False, indent=1),
                      encoding="utf-8")

    print(f"Prototipos escritos en {salida}")
    print(f"  version CapCut : {proto['version_capcut']}")
    print(f"  segmentos      : {sorted(proto['segmentos'])}")
    print(f"  auxiliares     : {sorted(proto['auxiliares'])}")
    print(f"  transiciones   : {len(proto['catalogo_transiciones'])}")
    print(f"  sonidos        : {len(proto['catalogo_sonidos'])}")
    print(f"  rotulos        : {len(proto['rotulos'])}")


if __name__ == "__main__":
    main()
