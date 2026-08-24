"""
Escritor de borradores de CapCut.

No construye el JSON desde cero: clona los prototipos extraidos de un proyecto
real (plantillas/prototipos_9.2.8.json) y sustituye solo lo que cambia. Es la
unica estrategia sensata contra un formato no documentado: todo campo que no
entendemos se conserva tal cual venia de CapCut.
"""
from __future__ import annotations

import copy
import json
import shutil
import uuid
from pathlib import Path

from ..edl import EDL, duracion_video, dimensiones_video, tiene_audio

US = 1_000_000  # CapCut trabaja en microsegundos


def nuevo_id() -> str:
    """UUID con el formato que usa CapCut: mayusculas salvo el tercer grupo."""
    g = str(uuid.uuid4()).upper().split("-")
    g[2] = g[2].lower()
    return "-".join(g)


def us(segundos: float) -> int:
    return int(round(segundos * US))


class EscritorCapCut:

    def __init__(self, prototipos: Path):
        self.p = json.loads(Path(prototipos).read_text(encoding="utf-8"))
        self.trans_por_id = {t["effect_id"]: t
                             for t in self.p["catalogo_transiciones"]}
        self.sonidos_por_nombre = {s["name"]: s
                                   for s in self.p["catalogo_sonidos"]}
        self.efectos_por_id = {e["effect_id"]: e
                               for e in self.p.get("catalogo_efectos", [])}
        self.rotulos_por_nombre = {}
        for r in self.p.get("rotulos", []):
            # nos quedamos con el primero de cada plantilla
            self.rotulos_por_nombre.setdefault(r["nombre"], r)

    # -- helpers ---------------------------------------------------------

    def _aux(self, clave: str) -> dict:
        """Clona un material auxiliar del prototipo con id nuevo."""
        obj = copy.deepcopy(self.p["auxiliares"][clave])
        obj["id"] = nuevo_id()
        return obj

    def _registrar_aux(self, M: dict, claves: list[tuple[str, str]]) -> list[str]:
        """
        Crea un juego de auxiliares y los mete en materials.
        claves = [(clave_en_prototipo, categoria_destino), ...]
        Devuelve la lista de ids para extra_material_refs.
        """
        refs = []
        for clave, categoria in claves:
            obj = self._aux(clave)
            M.setdefault(categoria, []).append(obj)
            refs.append(obj["id"])
        return refs

    # -- materiales ------------------------------------------------------

    def _material_video(self, ruta: Path) -> dict:
        m = copy.deepcopy(self.p["materiales"]["video"])
        ancho, alto = dimensiones_video(ruta)
        m.update({
            "id": nuevo_id(),
            "local_material_id": nuevo_id().lower(),
            "path": str(ruta).replace("\\", "/"),
            "material_name": ruta.name,
            "duration": us(duracion_video(ruta)),
            "width": ancho,
            "height": alto,
            "type": "video",
            # lo que traiga el archivo de verdad. Los clips se bajan mudos,
            # y declarar audio que no existe es describirle a CapCut un
            # material que no es el que tiene delante.
            "has_audio": tiene_audio(ruta),
        })
        for k in ("media_path", "intensifies_path", "reverse_path",
                  "reverse_intensifies_path", "cartoon_path"):
            if k in m:
                m[k] = ""
        return m

    def _material_audio_local(self, ruta: Path, duracion_s: float,
                              tipo: str = "music") -> dict:
        """
        Material para un audio importado del disco (la narracion).

        Parte del prototipo de audio LOCAL, no del de un efecto de sonido de
        la libreria: si se hereda 'effect_id'/'app_id' de un sfx de CapCut
        apuntando a un mp3 del disco, sale un material hibrido que CapCut
        interpreta como recurso Pro y bloquea la exportacion.
        """
        base = self.p["materiales"].get("audio_local") \
            or self.p["materiales"]["audio"]
        m = copy.deepcopy(base)
        m.update({
            "id": nuevo_id(),
            "local_material_id": nuevo_id().lower(),
            "path": str(ruta).replace("\\", "/"),
            "name": ruta.name,
            "duration": us(duracion_s),
            "type": tipo,
            "category_name": "local",
            "category_id": "",
            "music_id": nuevo_id().lower(),
            "unique_id": nuevo_id().replace("-", "").lower(),
        })
        # cualquier rastro de recurso de la libreria de CapCut tiene que irse
        for k in ("effect_id", "resource_id", "third_resource_id", "pgc_id",
                  "pgc_name", "search_id", "request_id", "text_id", "video_id",
                  "formula_id", "aigc_history_id", "aigc_item_id"):
            if k in m:
                m[k] = ""
        for k in ("app_id", "team_id", "source_platform", "source_from"):
            if k in m:
                m[k] = 0 if isinstance(m[k], int) else ""
        return m

    def _material_sonido(self, nombre: str) -> dict:
        base = self.sonidos_por_nombre.get(nombre)
        if base is None:
            raise KeyError(
                f"El sonido '{nombre}' no esta en el catalogo de prototipos. "
                f"Disponibles: {sorted(self.sonidos_por_nombre)}")
        m = copy.deepcopy(base)
        m.pop("_usos", None)
        m["id"] = nuevo_id()
        return m

    def _material_efecto(self, efecto) -> dict:
        """
        El efecto de video que cubre toda la timeline.

        Se busca por effect_id en el catalogo y se cae al prototipo si no
        esta. El 'path' apunta a la cache de efectos de CapCut y **no se
        limpia**: es un recurso legitimo de la biblioteca, igual que los
        efectos de sonido. Lo que no se toca es lo que hace que funcione.
        """
        base = self.efectos_por_id.get(efecto.effect_id)
        if base is None:
            base = self.p["materiales"].get("efecto")
        if base is None:
            raise KeyError(
                f"El efecto '{efecto.nombre}' no esta en los prototipos. "
                f"Extraelo de un proyecto real con "
                f"herramientas/extraer_prototipos.py.")

        m = copy.deepcopy(base)
        for k in ("_usos", "_duracion_us"):
            m.pop(k, None)
        m["id"] = nuevo_id()

        if efecto.velocidad is not None:
            for par in m.get("adjust_params", []):
                if par.get("name") == "effects_adjust_speed":
                    par["value"] = efecto.velocidad
        return m

    # -- segmentos -------------------------------------------------------

    def _segmento_video(self, M: dict, bloque, material_id: str,
                        indice_pista: int) -> dict:
        s = copy.deepcopy(self.p["segmentos"]["video"])
        refs = self._registrar_aux(M, [
            ("speeds", "speeds"),
            ("placeholder_infos", "placeholder_infos"),
            ("canvases", "canvases"),
            ("material_animations", "material_animations"),
            ("sound_channel_mappings", "sound_channel_mappings"),
            ("material_colors", "material_colors"),
            ("vocal_separations", "vocal_separations"),
        ])

        if bloque.transicion:
            t = copy.deepcopy(self.trans_por_id[bloque.transicion])
            t.pop("_usos", None)
            t["id"] = nuevo_id()
            M.setdefault("transitions", []).append(t)
            # CapCut espera la transicion entre placeholder y canvas
            refs.insert(2, t["id"])

        s.update({
            "id": nuevo_id(),
            "material_id": material_id,
            "extra_material_refs": refs,
            "source_timerange": {"start": us(bloque.clip_inicio_s),
                                 "duration": us(bloque.duracion_s)},
            "target_timerange": {"start": us(bloque.inicio_s),
                                 "duration": us(bloque.duracion_s)},
            "track_render_index": indice_pista,
            "speed": 1.0,
        })
        # sin recorte ni espejo: el prototipo traia el encuadre de otro clip
        s["clip"] = {
            "scale": {"x": 1.0, "y": 1.0},
            "rotation": 0.0,
            "transform": {"x": 0.0, "y": 0.0},
            "flip": {"vertical": False, "horizontal": False},
            "alpha": 1.0,
        }
        return s

    def _segmento_audio(self, M: dict, material_id: str, inicio_s: float,
                        duracion_s: float, indice_pista: int,
                        origen_s: float = 0.0, volumen: float = 1.0) -> dict:
        s = copy.deepcopy(self.p["segmentos"]["audio"])
        refs = self._registrar_aux(M, [
            ("audio_speeds", "speeds"),
            ("audio_placeholder_infos", "placeholder_infos"),
            ("audio_beats", "beats"),
            ("audio_sound_channel_mappings", "sound_channel_mappings"),
            ("audio_vocal_separations", "vocal_separations"),
        ])
        s.update({
            "id": nuevo_id(),
            "material_id": material_id,
            "extra_material_refs": refs,
            "source_timerange": {"start": us(origen_s),
                                 "duration": us(duracion_s)},
            "target_timerange": {"start": us(inicio_s),
                                 "duration": us(duracion_s)},
            "track_render_index": indice_pista,
            "volume": volumen,
            "last_nonzero_volume": volumen,
        })
        return s

    def _segmento_efecto(self, material_id: str, efecto,
                         indice_pista: int) -> dict:
        """
        El segmento unico de la pista de efecto.

        No lleva extra_material_refs: en el proyecto del que se copio venia
        con la lista vacia, asi que aqui no se registra ningun auxiliar. Y
        source_timerange se queda a None: un efecto no lee de ningun archivo,
        solo ocupa un tramo de la timeline.
        """
        s = copy.deepcopy(self.p["segmentos"]["efecto"])
        s.update({
            "id": nuevo_id(),
            "material_id": material_id,
            "extra_material_refs": [],
            "source_timerange": None,
            "target_timerange": {"start": us(efecto.inicio_s),
                                 "duration": us(efecto.duracion_s)},
            "track_render_index": indice_pista,
        })
        return s

    def _segmento_rotulo(self, M: dict, rotulo, indice_pista: int) -> dict | None:
        base = self.rotulos_por_nombre.get(rotulo.plantilla)
        if base is None:
            base = next(iter(self.rotulos_por_nombre.values()), None)
        if base is None:
            return None

        plantilla = copy.deepcopy(base["plantilla"])
        materiales_texto = copy.deepcopy(base["materiales_texto"])

        # ids nuevos para los materiales de texto, manteniendo el enlace
        mapa = {}
        for mt in materiales_texto:
            viejo = mt["id"]
            mt["id"] = nuevo_id()
            mapa[viejo] = mt["id"]

        for i, mt in enumerate(materiales_texto):
            if i < len(rotulo.textos):
                try:
                    contenido = json.loads(mt["content"])
                    contenido["text"] = rotulo.textos[i]
                    # los estilos van por rangos de caracteres
                    for estilo in contenido.get("styles", []):
                        if "range" in estilo:
                            estilo["range"] = [0, len(rotulo.textos[i])]
                    mt["content"] = json.dumps(contenido, ensure_ascii=False)
                except (ValueError, KeyError):
                    mt["content"] = rotulo.textos[i]
                mt["base_content"] = rotulo.textos[i]

        plantilla["id"] = nuevo_id()
        for r in plantilla.get("text_info_resources", []):
            if r.get("text_material_id") in mapa:
                r["text_material_id"] = mapa[r["text_material_id"]]
            r["id"] = nuevo_id()
            if "attach_info" in r:
                r["attach_info"]["duration"] = us(rotulo.duracion_s)

        M.setdefault("texts", []).extend(materiales_texto)
        M.setdefault("text_templates", []).append(plantilla)

        # auxiliares del rotulo (animaciones, efectos)
        refs = []
        for categoria, objetos in base["auxiliares"].items():
            for o in objetos:
                oc = copy.deepcopy(o)
                oc["id"] = nuevo_id()
                M.setdefault(categoria, []).append(oc)
                refs.append(oc["id"])

        s = copy.deepcopy(base["segmento"])
        s.update({
            "id": nuevo_id(),
            "material_id": plantilla["id"],
            "extra_material_refs": refs,
            "target_timerange": {"start": us(rotulo.inicio_s),
                                 "duration": us(rotulo.duracion_s)},
            "track_render_index": indice_pista,
        })
        return s

    # -- documento -------------------------------------------------------

    def construir(self, edl: EDL, nombre_proyecto: str) -> dict:
        doc = copy.deepcopy(self.p["documento_base"])
        M = doc["materials"]
        for k in list(M):
            if isinstance(M[k], list):
                M[k] = []

        doc["id"] = nuevo_id()
        doc["name"] = ""
        doc["duration"] = us(edl.duracion_s)
        doc["fps"] = edl.fps
        doc["canvas_config"] = {"ratio": "original", "width": edl.ancho,
                                "height": edl.alto, "background": None}

        pistas = []
        idx_pista = 0

        # --- pista 0: video ---
        segmentos_video = []
        cache_material: dict[str, dict] = {}
        for b in edl.bloques:
            # CapCut crea un material por segmento; replicamos ese patron
            mat = self._material_video(Path(b.clip))
            M.setdefault("videos", []).append(mat)
            cache_material[b.clip] = mat
            segmentos_video.append(
                self._segmento_video(M, b, mat["id"], idx_pista))
        pistas.append({"attribute": 0, "flag": 0, "id": nuevo_id(),
                       "is_default_name": True, "name": "",
                       "segments": segmentos_video, "type": "video"})
        idx_pista += 1

        # --- pistas de texto ---
        if edl.rotulos:
            segs_texto = []
            for r in edl.rotulos:
                s = self._segmento_rotulo(M, r, idx_pista)
                if s:
                    segs_texto.append(s)
            if segs_texto:
                pistas.append({"attribute": 0, "flag": 0, "id": nuevo_id(),
                               "is_default_name": True, "name": "",
                               "segments": segs_texto, "type": "text"})
                idx_pista += 1

        # --- pista de efecto ---
        # Detras de los rotulos y delante del audio, que es el orden en que
        # CapCut las deja cuando el efecto se anade a mano.
        if edl.efecto and self.p["segmentos"].get("efecto"):
            mat_e = self._material_efecto(edl.efecto)
            M.setdefault("video_effects", []).append(mat_e)
            pistas.append({
                "attribute": 0, "flag": 0, "id": nuevo_id(),
                "is_default_name": True, "name": "",
                "segments": [self._segmento_efecto(
                    mat_e["id"], edl.efecto, idx_pista)],
                "type": "effect"})
            idx_pista += 1

        # --- pista de narracion ---
        narracion = Path(edl.narracion)
        if narracion.exists():
            from ..alineacion import duracion_audio
            dur = duracion_audio(narracion)
            mat_n = self._material_audio_local(
                narracion, dur, tipo=getattr(self, "tipo_audio", "music"))
            M.setdefault("audios", []).append(mat_n)
            pistas.append({
                "attribute": 0, "flag": 0, "id": nuevo_id(),
                "is_default_name": True, "name": "",
                "segments": [self._segmento_audio(
                    M, mat_n["id"], 0.0, min(dur, edl.duracion_s), idx_pista)],
                "type": "audio"})
            idx_pista += 1

        # --- pista de efectos de sonido ---
        if edl.sonidos:
            segs_sfx = []
            for snd in edl.sonidos:
                mat = self._material_sonido(snd.nombre)
                M.setdefault("audios", []).append(mat)
                segs_sfx.append(self._segmento_audio(
                    M, mat["id"], snd.inicio_s, snd.duracion_s, idx_pista))
            pistas.append({"attribute": 0, "flag": 0, "id": nuevo_id(),
                           "is_default_name": True, "name": "",
                           "segments": segs_sfx, "type": "audio"})
            idx_pista += 1

        doc["tracks"] = pistas
        return doc

    # -- salida ----------------------------------------------------------

    def escribir(self, edl: EDL, carpeta_borradores: Path,
                 nombre_proyecto: str) -> Path:
        destino = Path(carpeta_borradores) / nombre_proyecto
        if destino.exists():
            shutil.rmtree(destino)
        destino.mkdir(parents=True)

        doc = self.construir(edl, nombre_proyecto)
        (destino / "draft_content.json").write_text(
            json.dumps(doc, ensure_ascii=False), encoding="utf-8")

        meta = self._meta(edl, destino, nombre_proyecto, doc)
        (destino / "draft_meta_info.json").write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8")

        return destino

    def _meta(self, edl: EDL, destino: Path, nombre: str, doc: dict) -> dict:
        materiales = []
        vistos = set()

        for v in doc["materials"].get("videos", []):
            if v["path"] in vistos or not v["path"]:
                continue
            vistos.add(v["path"])
            materiales.append({
                "create_time": 0, "duration": v["duration"], "extra_info":
                Path(v["path"]).name, "file_Path": v["path"],
                "height": v["height"], "width": v["width"],
                "id": nuevo_id(), "import_time": 0, "import_time_ms": 0,
                "item_source": 1, "md5": "", "metetype": "video",
                "roughcut_time_range": {"duration": v["duration"], "start": 0},
                "sub_time_range": {"duration": -1, "start": -1}, "type": 0,
            })

        for a in doc["materials"].get("audios", []):
            p = a.get("path") or ""
            if not p or p in vistos:
                continue
            vistos.add(p)
            materiales.append({
                "create_time": 0, "duration": a.get("duration", 0),
                "extra_info": Path(p).name, "file_Path": p,
                "height": 0, "width": 0,
                "id": nuevo_id(), "import_time": 0, "import_time_ms": 0,
                "item_source": 1, "md5": "", "metetype": "music",
                "roughcut_time_range": {"duration": a.get("duration", 0),
                                        "start": 0},
                "sub_time_range": {"duration": -1, "start": -1}, "type": 0,
            })

        return {
            "draft_cover": "draft_cover.jpg",
            "draft_fold_path": str(destino).replace("\\", "/"),
            "draft_id": nuevo_id(),
            "draft_materials": [
                {"type": 0, "value": materiales},
                {"type": 1, "value": []}, {"type": 2, "value": []},
                {"type": 3, "value": []}, {"type": 6, "value": []},
                {"type": 7, "value": []}, {"type": 8, "value": []},
            ],
            "draft_materials_copied_info": [],
            "draft_name": nombre,
            "draft_new_version": "",
            "draft_removable_storage_device": "",
            "draft_root_path": str(destino.parent).replace("/", "\\"),
            "draft_segment_extra_info": [],
            "draft_timeline_materials_size_": 0,
            "draft_type": "",
            "tm_draft_create": 0,
            "tm_draft_modified": 0,
            "tm_draft_removed": 0,
            "tm_duration": us(edl.duracion_s),
        }
