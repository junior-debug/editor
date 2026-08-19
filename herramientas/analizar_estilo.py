"""
Analiza cualquier draft_content.json de CapCut y saca las metricas de estilo.

Dos usos:
  1. Sobre un proyecto tuyo montado a mano: recalibrar montador/config.py.
  2. Sobre un borrador generado: comprobar que reproduce tu estilo.

Uso:
    python herramientas/analizar_estilo.py <draft_content.json> [otro.json]

Con dos argumentos compara ambos lado a lado.
"""
import json
import statistics as st
import sys
from collections import Counter
from pathlib import Path


def analizar(ruta: Path) -> dict:
    d = json.loads(ruta.read_text(encoding="utf-8"))
    M, T = d["materials"], d["tracks"]
    trans = {t["id"]: t for t in M.get("transitions", [])}
    audios = {a["id"]: a for a in M.get("audios", [])}

    pista_video = max((t for t in T if t["type"] == "video"),
                      key=lambda t: len(t["segments"]))
    segs = pista_video["segments"]
    durs = [s["target_timerange"]["duration"] / 1e6 for s in segs]

    con_trans = [s for s in segs
                 if any(r in trans for r in s["extra_material_refs"])]
    idx_trans = [i for i, s in enumerate(segs)
                 if any(r in trans for r in s["extra_material_refs"])]
    huecos = [idx_trans[i + 1] - idx_trans[i] for i in range(len(idx_trans) - 1)]

    # pista de efectos = la de audio con mas segmentos
    pistas_audio = [t for t in T if t["type"] == "audio"]
    pista_sfx = max(pistas_audio, key=lambda t: len(t["segments"])) \
        if pistas_audio else {"segments": []}
    sfx = pista_sfx["segments"] if len(pista_sfx["segments"]) > 1 else []

    inicios = [s["target_timerange"]["start"] / 1e6 for s in segs]
    sfx_en_trans = 0
    desfases = []
    for s in sfx:
        t0 = s["target_timerange"]["start"] / 1e6
        j = min(range(len(inicios)), key=lambda k: abs(inicios[k] - t0))
        desfases.append(round(t0 - inicios[j], 3))
        if any(r in trans for r in segs[j]["extra_material_refs"]):
            sfx_en_trans += 1

    sep_sfx = [round(sfx[i + 1]["target_timerange"]["start"] / 1e6
                     - sfx[i]["target_timerange"]["start"] / 1e6, 2)
               for i in range(len(sfx) - 1)]

    # clips distintos por ruta
    videos = {v["id"]: v for v in M.get("videos", [])}
    rutas = [videos.get(s["material_id"], {}).get("path", "?") for s in segs]

    return {
        "archivo": ruta.name,
        "duracion_s": round(d["duration"] / 1e6, 1),
        "n_cortes": len(segs),
        "corte_media": round(st.mean(durs), 2),
        "corte_mediana": round(st.median(durs), 2),
        "corte_min": round(min(durs), 2),
        "corte_max": round(max(durs), 2),
        "clips_distintos": len(set(rutas)),
        "n_transiciones": len(con_trans),
        "pct_transiciones": round(100 * len(con_trans) / len(segs)),
        "trans_cada_n_cortes": round(st.mean(huecos), 2) if huecos else 0,
        "transiciones_top": Counter(
            trans[r]["name"] for s in segs for r in s["extra_material_refs"]
            if r in trans).most_common(5),
        "n_sfx": len(sfx),
        "sfx_cada_s": round(st.mean(sep_sfx), 1) if sep_sfx else 0,
        "sfx_en_cortes_con_transicion": sfx_en_trans,
        "sfx_en_frame_exacto": sum(1 for x in desfases if abs(x) < 0.05),
        "sfx_top": Counter(
            audios[s["material_id"]]["name"] for s in sfx
            if s["material_id"] in audios).most_common(5),
        "n_rotulos": sum(len(t["segments"]) for t in T if t["type"] == "text"),
    }


CAMPOS = [
    ("duracion_s", "duracion (s)"),
    ("n_cortes", "cortes"),
    ("corte_media", "corte medio (s)"),
    ("corte_mediana", "corte mediana (s)"),
    ("corte_min", "corte min (s)"),
    ("corte_max", "corte max (s)"),
    ("clips_distintos", "clips distintos"),
    ("n_transiciones", "transiciones"),
    ("pct_transiciones", "% cortes con transicion"),
    ("trans_cada_n_cortes", "transicion cada N cortes"),
    ("n_sfx", "efectos de sonido"),
    ("sfx_cada_s", "sonido cada (s)"),
    ("sfx_en_cortes_con_transicion", "sonidos sobre transicion"),
    ("sfx_en_frame_exacto", "sonidos en el frame exacto"),
    ("n_rotulos", "rotulos"),
]


def main():
    informes = [analizar(Path(a)) for a in sys.argv[1:]]
    if not informes:
        print(__doc__)
        return

    ancho = max(len(e) for _, e in CAMPOS) + 2
    cab = "".join(f"{i['archivo'][:22]:>24}" for i in informes)
    print(" " * ancho + cab)
    print("-" * (ancho + 24 * len(informes)))
    for clave, etiqueta in CAMPOS:
        fila = "".join(f"{str(i[clave]):>24}" for i in informes)
        print(f"{etiqueta:<{ancho}}{fila}")

    for i in informes:
        print()
        print(f"[{i['archivo']}] transiciones:")
        for n, c in i["transiciones_top"]:
            print(f"    {c:>3} x {n}")
        print(f"[{i['archivo']}] sonidos:")
        for n, c in i["sfx_top"]:
            print(f"    {c:>3} x {n}")


if __name__ == "__main__":
    main()
