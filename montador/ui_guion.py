"""
Ventana para escribir el guion hablando con Claude.

Es un chat, no un formulario, porque las reglas del usuario son un protocolo
de conversacion: Claude propone tres hooks, el elige, Claude pasa al siguiente
paso, y asi hasta la ultima parte. Un boton de "escribir guion" no puede
hacer eso.

Dos cosas conviven en la ventana y no hay que mezclarlas:

  la charla   lo que Claude nos dice: opciones, preguntas, avisos.
  el guion    solo lo que se va a locutar, que es lo unico que acaba en
              guion.txt y en el mp3.

Las separa Claude con las marcas del contrato, y las lee extraer_guion(). Si
no fuera asi, el narrador leeria en voz alta las tres opciones de hook.

Tkinter viene con Python, asi que no anade dependencias. Las llamadas corren
en un hilo aparte y se comunican por cola: desde el hilo de la ventana, esta
se quedaria congelada minutos y Windows la marcaria como "no responde".
"""
from __future__ import annotations

import queue
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, ttk
from urllib.parse import quote_plus

from . import descargas as desc
from . import guionista as gui
from . import perfiles as perf
from . import proyecto as proy
from . import voz

# Busqueda de YouTube. Se deja a la vista para poder cambiarla: hay dias en
# que el material bueno esta en otro sitio.
BUSCADOR = "https://www.youtube.com/results?search_query={}"

# Raiz del repositorio: desde aqui se lanza 'python -m montador montar' en un
# proceso aparte. Ver _montar().
RAIZ = Path(__file__).resolve().parent.parent

# En Windows evita que el proceso hijo abra una consola que parpadee encima de
# la ventana. Fuera de Windows vale 0 y no hace nada.
SIN_CONSOLA = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Cada cuanto se mira el portapapeles. Medio segundo es lo bastante rapido
# para que el clip aparezca "solo" nada mas copiar el enlace, y lo bastante
# lento para no notarse: la comprobacion es leer una cadena y mirarla.
LATIDO_PORTAPAPELES = 500

# Lo que se ofrece como destino cuando la carpeta no tiene parteN. No es un
# caso raro: edl.py ya contempla todos los videos sueltos como una sola parte.
SIN_PARTES = "(la carpeta)"

PISTA_INICIAL = ("Escribe de qué va el vídeo y dale a Enviar. "
                 "A partir de ahí, Claude lleva la conversación.")


class VentanaGuion:
    def __init__(self, carpeta: Path, partes: int = 4, perfil: str = ""):
        self.carpeta = Path(carpeta)
        self.perfil_inicial = perfil
        self.guardado: Path | None = None
        self.cola: queue.Queue = queue.Queue()
        self.trabajando = False
        self.tarea = None
        self.conversacion: gui.Conversacion | None = None
        self.bloques = 0          # trozos de guion recibidos, para el estado

        # Descargas. Van por su cuenta y no tocan 'trabajando' a proposito:
        # mientras baja un clip se sigue hablando con Claude y, sobre todo, se
        # siguen copiando enlaces, que es justo lo que se esta haciendo.
        self.pendientes: queue.Queue = queue.Queue()
        self.bajando = 0          # en curso + en cola, para avisar al montar
        self.ya_bajados: set[str] = set()
        # en el mismo orden en que se atienden: las descargas van de una en
        # una, asi que la que termina es siempre la primera de la lista
        self.urls_en_cola: list[str] = []
        self.ultimo_copiado = ""
        self.linea_registro: int | None = None
        self.hay_pista = True
        self.texto_bajada = ""
        self.vigilancia = None
        self.yt_dlp_listo: bool | None = None   # sin comprobar todavia

        self.raiz = tk.Tk()
        self.raiz.title(f"Guion — {self.carpeta.name}")
        self.raiz.geometry("900x740")
        self.raiz.minsize(700, 520)

        try:
            self.backend = gui.detectar_backend()
        except gui.SinBackend as exc:
            self.backend = ""
            self.raiz.after(100, lambda: messagebox.showerror(
                "Sin conexion con Claude", str(exc)))

        self._construir()
        # el sondeo de la cola queda pendiente: hay que cancelarlo al cerrar o
        # Tk intenta ejecutarlo sobre widgets que ya no existen
        self.tarea = self.raiz.after(120, self._vaciar_cola)
        # el vigilante del portapapeles late siempre y no hace nada mientras
        # la casilla este sin marcar: arrancarlo y pararlo con ella dejaria
        # dos relojes que cancelar en vez de uno
        self.vigilancia = self.raiz.after(LATIDO_PORTAPAPELES,
                                          self._vigilar_portapapeles)
        self.raiz.protocol("WM_DELETE_WINDOW", self.cerrar)

    def cerrar(self) -> None:
        if self.bajando and not messagebox.askyesno(
                "Quedan descargas",
                f"Hay {self.bajando} clip(s) sin terminar de bajar. Si "
                f"cierras ahora se quedan a medias.\n\nCierro igual?"):
            return
        for reloj in ("tarea", "vigilancia"):
            pendiente = getattr(self, reloj, None)
            if pendiente is not None:
                self.raiz.after_cancel(pendiente)
                setattr(self, reloj, None)
        self.raiz.destroy()

    # ----------------------------------------------------------------
    # Montaje de la ventana
    # ----------------------------------------------------------------

    def _construir(self) -> None:
        marco = ttk.Frame(self.raiz, padding=12)
        marco.pack(fill="both", expand=True)
        marco.columnconfigure(0, weight=1)
        marco.rowconfigure(2, weight=1)

        cabecera = ttk.Frame(marco)
        cabecera.grid(row=0, column=0, sticky="ew")
        cabecera.columnconfigure(0, weight=1)
        ttk.Label(cabecera, text=str(self.carpeta),
                  foreground="#555").grid(row=0, column=0, sticky="w")
        etiqueta = {"cli": "Claude Code", "api": "API de Anthropic",
                    "": "sin conexion"}[self.backend]
        ttk.Label(cabecera, text=etiqueta,
                  foreground="#555").grid(row=0, column=1, sticky="e")

        reglas = ttk.Frame(marco)
        reglas.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        reglas.columnconfigure(1, weight=1)

        ttk.Label(reglas, text="Reglas:").grid(row=0, column=0, sticky="w")
        self.perfil = ttk.Combobox(reglas, state="readonly")
        self.perfil.grid(row=0, column=1, sticky="ew", padx=(6, 6))
        ttk.Button(reglas, text="Nuevas...",
                   command=self._nuevo_perfil).grid(row=0, column=2)
        ttk.Button(reglas, text="Ver / editar",
                   command=self._editar_perfil).grid(row=0, column=3,
                                                     padx=(6, 0))
        self._refrescar_perfiles(elegir=self.perfil_inicial)

        # Las reglas se congelan en el primer turno: van dentro del primer
        # mensaje, asi que cambiarlas a mitad no cambiaria nada y solo
        # confundiria.
        self.perfil.bind("<<ComboboxSelected>>", self._al_cambiar_perfil)

        self.pestanas = ttk.Notebook(marco)
        self.pestanas.grid(row=2, column=0, sticky="nsew", pady=(10, 0))

        self.charla = self._panel_texto(self.pestanas, editable=False)
        self.pestanas.add(self.charla.master, text="Conversacion")

        self.guion = self._panel_texto(self.pestanas, editable=True)
        self.pestanas.add(self.guion.master, text="Guion")

        self.pestanas.add(self._panel_clips(self.pestanas), text="Clips")
        self.pestanas.add(self._panel_publicacion(self.pestanas),
                          text="Publicacion")

        self.charla.tag_configure("tu", foreground="#1a4f8a",
                                  font=("Segoe UI", 10, "bold"),
                                  spacing1=10, spacing3=2)
        self.charla.tag_configure("claude", font=("Segoe UI", 10),
                                  spacing3=4)
        self.charla.tag_configure("nota", foreground="#767676",
                                  font=("Segoe UI", 9, "italic"),
                                  spacing1=4, spacing3=8)
        self.guion.bind("<<Modified>>", self._al_editar_guion)

        # barra de atajos: se rellena con lo que Claude acabe de proponer
        self.barra_atajos = ttk.Frame(marco)
        self.barra_atajos.grid(row=3, column=0, sticky="ew", pady=(8, 0))

        entrada = ttk.Frame(marco)
        entrada.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        entrada.columnconfigure(0, weight=1)

        self.mensaje = tk.Text(entrada, height=4, wrap="word", undo=True,
                               font=("Segoe UI", 10))
        self.mensaje.grid(row=0, column=0, sticky="ew")
        self.mensaje.focus_set()
        # Enter manda, Shift+Enter hace parrafo: es lo que espera cualquiera
        # que haya escrito en un chat alguna vez
        self.mensaje.bind("<Return>", self._al_pulsar_enter)
        self.mensaje.bind("<Shift-Return>", lambda e: None)

        lado = ttk.Frame(entrada)
        lado.grid(row=0, column=1, sticky="ns", padx=(8, 0))
        self.boton_enviar = ttk.Button(lado, text="Enviar",
                                       command=self._enviar)
        self.boton_enviar.pack(fill="x")
        self.boton_reiniciar = ttk.Button(lado, text="Empezar de cero",
                                          command=self._reiniciar)
        self.boton_reiniciar.pack(fill="x", pady=(6, 0))

        self.barra = ttk.Progressbar(marco, mode="indeterminate")
        self.barra.grid(row=5, column=0, sticky="ew", pady=(8, 0))

        pie = ttk.Frame(marco)
        pie.grid(row=6, column=0, sticky="ew", pady=(8, 0))
        pie.columnconfigure(0, weight=1)

        self.estado = ttk.Label(pie, text=PISTA_INICIAL)
        self.estado.grid(row=0, column=0, sticky="w")

        self.boton_voz = ttk.Button(pie,
                                    text=f"Generar voz ({voz.NOMBRE_VOZ})",
                                    command=self._generar_voz)
        self.boton_voz.grid(row=0, column=1, sticky="e", padx=(0, 6))

        self.boton_guardar = ttk.Button(pie, text="Guardar guion.txt",
                                        command=self._guardar)
        self.boton_guardar.grid(row=0, column=2, sticky="e")

        self.boton_montar = ttk.Button(pie, text="Montar en CapCut",
                                       command=self._montar)
        self.boton_montar.grid(row=0, column=3, sticky="e", padx=(6, 0))

        existente = self.carpeta / "guion.txt"
        if existente.exists():
            self.guion.insert("1.0", existente.read_text(encoding="utf-8"))
            self._decir("Cargado el guion.txt que ya habia. "
                        "Escribe el tema para empezar otro.")

    def _panel_clips(self, padre) -> ttk.Frame:
        """
        Que buscar para ilustrar cada parte.

        Es texto editable y no una lista cerrada porque las busquedas se
        retocan: se prueba una, no da nada, se cambia una palabra. Lo que se
        guarda y lo que se abre en el navegador sale de lo que haya aqui, no
        de lo que dijo Claude.
        """
        marco = ttk.Frame(padre)
        marco.columnconfigure(0, weight=1)
        marco.rowconfigure(1, weight=1)

        arriba = ttk.Frame(marco, padding=(8, 8, 8, 4))
        arriba.grid(row=0, column=0, sticky="ew")
        arriba.columnconfigure(2, weight=1)

        self.boton_clips = ttk.Button(
            arriba, text="Pedir las busquedas a Claude",
            command=self._pedir_clips)
        self.boton_clips.grid(row=0, column=0)

        ttk.Button(arriba, text="Guardar en las carpetas parteN",
                   command=self._guardar_clips).grid(row=0, column=1,
                                                     padx=(6, 0))

        caja = ttk.Frame(marco)
        caja.grid(row=1, column=0, sticky="nsew", padx=8)
        caja.columnconfigure(0, weight=1)
        caja.rowconfigure(0, weight=1)

        self.clips = tk.Text(caja, wrap="none", undo=True, padx=8, pady=6,
                             font=("Consolas", 10))
        self.clips.grid(row=0, column=0, sticky="nsew")
        barra_v = ttk.Scrollbar(caja, orient="vertical",
                                command=self.clips.yview)
        barra_v.grid(row=0, column=1, sticky="ns")
        barra_h = ttk.Scrollbar(caja, orient="horizontal",
                                command=self.clips.xview)
        barra_h.grid(row=1, column=0, sticky="ew")
        self.clips.configure(yscrollcommand=barra_v.set,
                             xscrollcommand=barra_h.set)

        abajo = ttk.Frame(marco, padding=(8, 6, 8, 2))
        abajo.grid(row=2, column=0, sticky="ew")
        ttk.Label(abajo, text="Abrir en el navegador:").pack(side="left",
                                                             padx=(0, 8))
        self.barra_partes = ttk.Frame(abajo)
        self.barra_partes.pack(side="left")

        # ---- descarga ----
        # Va aqui debajo y no en una pestaña aparte porque es el mismo gesto
        # seguido: se abren las busquedas, se miran los videos, y el que sirve
        # se copia. Cambiar de pestaña en medio romperia justo eso.
        bajar = ttk.Frame(marco, padding=(8, 6, 8, 2))
        bajar.grid(row=3, column=0, sticky="ew")
        bajar.columnconfigure(3, weight=1)

        ttk.Label(bajar, text="Descargar a:").grid(row=0, column=0,
                                                   padx=(0, 6))
        self.parte_destino = tk.StringVar()
        self.combo_parte = ttk.Combobox(bajar, textvariable=self.parte_destino,
                                        state="readonly", width=12)
        self.combo_parte.grid(row=0, column=1)

        self.escuchando = tk.BooleanVar(value=False)
        ttk.Checkbutton(bajar, text="Escuchar el portapapeles",
                        variable=self.escuchando,
                        command=self._cambiar_escucha).grid(row=0, column=2,
                                                            padx=(10, 0))

        self.aviso_bajada = ttk.Label(bajar, text="", foreground="#666")
        self.aviso_bajada.grid(row=0, column=3, sticky="e")

        caja_reg = ttk.Frame(marco)
        caja_reg.grid(row=4, column=0, sticky="ew", padx=8, pady=(2, 8))
        caja_reg.columnconfigure(0, weight=1)

        ttk.Label(caja_reg, text="Descargas", foreground="#666").grid(
            row=0, column=0, sticky="w", pady=(0, 2))

        # alto fijo: es un registro de lo que va cayendo, no el contenido de
        # la pestaña. Lo que manda sigue siendo la lista de busquedas.
        #
        # Sin relieve y con el cursor de flecha **a proposito**: con borde
        # hundido y cursor de texto parece una caja donde escribir, y el
        # usuario intento escribir en ella. No se escribe aqui: se lee.
        self.registro = tk.Text(caja_reg, height=6, wrap="none", padx=8,
                                pady=4, font=("Consolas", 9),
                                state="disabled", background="#f4f4f4",
                                relief="flat", highlightthickness=0,
                                cursor="arrow", foreground="#333")
        self.registro.grid(row=1, column=0, sticky="ew")
        barra_reg = ttk.Scrollbar(caja_reg, orient="vertical",
                                  command=self.registro.yview)
        barra_reg.grid(row=1, column=1, sticky="ns")
        self.registro.configure(yscrollcommand=barra_reg.set)
        self._pista_registro()

        self._refrescar_destinos()
        self._pintar_botones_partes()
        return marco

    def _panel_publicacion(self, padre) -> ttk.Frame:
        """
        Los ocho titulos y la descripcion, para pegarlos en YouTube.

        Editable por lo mismo que los clips: de los ocho titulos se elige uno
        y casi siempre se le cambia una palabra. Lo que se guarda es lo que
        haya aqui, no lo que dijo Claude.
        """
        marco = ttk.Frame(padre)
        marco.columnconfigure(0, weight=1)
        marco.rowconfigure(1, weight=1)

        arriba = ttk.Frame(marco, padding=(8, 8, 8, 4))
        arriba.grid(row=0, column=0, sticky="ew")

        self.boton_publicacion = ttk.Button(
            arriba, text="Pedir titulos y descripcion a Claude",
            command=self._pedir_publicacion)
        self.boton_publicacion.grid(row=0, column=0)

        ttk.Button(arriba, text="Guardar publicacion.txt",
                   command=self._guardar_publicacion).grid(row=0, column=1,
                                                           padx=(6, 0))

        caja = ttk.Frame(marco)
        caja.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        caja.columnconfigure(0, weight=1)
        caja.rowconfigure(0, weight=1)

        # con wrap: la descripcion son parrafos, no lineas sueltas como las
        # busquedas
        self.publicacion = tk.Text(caja, wrap="word", undo=True,
                                   padx=8, pady=6, font=("Segoe UI", 10))
        self.publicacion.grid(row=0, column=0, sticky="nsew")
        barra = ttk.Scrollbar(caja, orient="vertical",
                              command=self.publicacion.yview)
        barra.grid(row=0, column=1, sticky="ns")
        self.publicacion.configure(yscrollcommand=barra.set)
        return marco

    def _panel_texto(self, padre, editable: bool) -> tk.Text:
        caja = ttk.Frame(padre)
        caja.columnconfigure(0, weight=1)
        caja.rowconfigure(0, weight=1)

        texto = tk.Text(caja, wrap="word", undo=True, padx=8, pady=6,
                        font=("Consolas", 10) if editable
                        else ("Segoe UI", 10))
        texto.grid(row=0, column=0, sticky="nsew")
        barra_v = ttk.Scrollbar(caja, orient="vertical", command=texto.yview)
        barra_v.grid(row=0, column=1, sticky="ns")
        texto.configure(yscrollcommand=barra_v.set)
        if not editable:
            # Solo lectura, pero ni muda ni quieta: con state="disabled" no se
            # podria copiar ni moverse por el texto, que es justo lo que se
            # quiere hacer en una transcripcion. Se bloquea la escritura y se
            # dejan pasar los atajos (Ctrl) y las teclas de navegacion.
            texto.bind("<Key>", self._solo_lectura)
        return texto

    NAVEGACION = frozenset((
        "Up", "Down", "Left", "Right", "Prior", "Next", "Home", "End",
        "Shift_L", "Shift_R", "Control_L", "Control_R", "Tab"))

    def _solo_lectura(self, evento):
        if evento.state & 0x4:              # Ctrl: copiar, seleccionar todo
            return None
        if evento.keysym in self.NAVEGACION:
            return None
        return "break"

    # ----------------------------------------------------------------
    # Perfiles de reglas
    # ----------------------------------------------------------------

    def _refrescar_perfiles(self, elegir: str = "") -> None:
        disponibles = perf.asegurar()
        self.perfil.configure(values=disponibles)
        if elegir and elegir in disponibles:
            self.perfil.set(elegir)
        elif not self.perfil.get() and disponibles:
            self.perfil.set(disponibles[0])

    def _al_cambiar_perfil(self, _evento=None) -> None:
        if self.conversacion:
            self._decir("Las reglas ya estan puestas en esta conversacion; "
                        "el cambio vale para la siguiente.")

    def _reglas_elegidas(self) -> str:
        nombre = self.perfil.get()
        return perf.cargar(nombre) if nombre else ""

    def _nuevo_perfil(self) -> None:
        self._editor_perfil("", "")

    def _editar_perfil(self) -> None:
        nombre = self.perfil.get()
        if not nombre:
            self._nuevo_perfil()
            return
        self._editor_perfil(nombre, perf.cargar(nombre))

    def _editor_perfil(self, nombre: str, contenido: str) -> None:
        """
        Ventanita para pegar las instrucciones de un proyecto de claude.ai.

        Es el puente manual que no se puede evitar: los proyectos de claude.ai
        no se leen desde fuera, asi que se copian una vez y se quedan aqui.
        """
        top = tk.Toplevel(self.raiz)
        top.title("Reglas del guion")
        top.geometry("760x600")
        top.transient(self.raiz)
        top.grab_set()

        marco = ttk.Frame(top, padding=12)
        marco.pack(fill="both", expand=True)
        marco.columnconfigure(1, weight=1)
        marco.rowconfigure(2, weight=1)

        ttk.Label(marco, text="Nombre:").grid(row=0, column=0, sticky="w")
        caja_nombre = ttk.Entry(marco)
        caja_nombre.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        caja_nombre.insert(0, nombre)

        ttk.Label(
            marco,
            text="Pega aqui las instrucciones de tu proyecto de Claude:",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(12, 2))

        caja_texto = tk.Text(marco, wrap="word", undo=True)
        caja_texto.grid(row=2, column=0, columnspan=2, sticky="nsew")
        caja_texto.insert("1.0", contenido)
        (caja_nombre if not nombre else caja_texto).focus_set()

        botones = ttk.Frame(marco)
        botones.grid(row=3, column=0, columnspan=2, sticky="e", pady=(10, 0))

        def confirmar():
            texto = caja_texto.get("1.0", "end-1c").strip()
            titulo = caja_nombre.get().strip()
            if not titulo:
                messagebox.showwarning("Falta el nombre",
                                       "Ponle un nombre al perfil.",
                                       parent=top)
                return
            if not texto:
                messagebox.showwarning("Vacio", "No hay reglas que guardar.",
                                       parent=top)
                return
            perf.guardar(titulo, texto)
            top.destroy()
            self._refrescar_perfiles(elegir=proy.sanear(titulo))
            self._decir(f"Reglas '{titulo}' guardadas.")

        ttk.Button(botones, text="Cancelar",
                   command=top.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(botones, text="Guardar reglas",
                   command=confirmar).pack(side="right")

    # ----------------------------------------------------------------
    # Estado
    # ----------------------------------------------------------------

    def _decir(self, mensaje: str) -> None:
        self.estado.configure(text=mensaje)

    def _ocupar(self, *botones) -> None:
        """Tres tareas largas —Claude, la voz, el montaje— y ninguna se solapa."""
        self.trabajando = True
        for boton in botones:
            boton.state(["disabled"])
        self.barra.start(12)

    def _liberar(self) -> None:
        self.trabajando = False
        self.barra.stop()
        for boton in (self.boton_enviar, self.boton_voz, self.boton_montar):
            boton.state(["!disabled"])

    def _resumen_guion(self) -> str:
        texto = self.guion.get("1.0", "end-1c")
        palabras = len(texto.split())
        if not palabras:
            return "El guion esta vacio."
        minutos = palabras / gui.PALABRAS_POR_MINUTO
        rotulos = texto.count("[TXT:")
        return (f"Guion: {palabras} palabras, unos {minutos:.1f} min "
                f"de locucion, {rotulos} rotulos.")

    def _al_editar_guion(self, _evento=None) -> None:
        self.guion.edit_modified(False)
        if not self.trabajando:
            self._decir(self._resumen_guion())

    # ----------------------------------------------------------------
    # Escritura en los paneles
    # ----------------------------------------------------------------

    def _escribir_charla(self, texto: str, marca: str) -> None:
        self.charla.insert("end", texto.rstrip() + "\n", marca)
        self.charla.see("end")

    def _sumar_al_guion(self, bloques: list[str]) -> None:
        for bloque in bloques:
            if self.guion.get("1.0", "end-1c").strip():
                self.guion.insert("end", "\n\n")
            self.guion.insert("end", bloque.strip())
            self.bloques += 1
        self.guion.see("end")
        self.guion.edit_modified(False)

    def _pintar_atajos(self, botones: list[tuple[str, str]]) -> None:
        for hijo in self.barra_atajos.winfo_children():
            hijo.destroy()
        if not botones:
            return
        for etiqueta, envio in botones:
            ttk.Button(
                self.barra_atajos, text=etiqueta,
                command=lambda t=envio: self._enviar(t),
            ).pack(side="left", padx=(0, 6))

    # ----------------------------------------------------------------
    # Conversacion
    # ----------------------------------------------------------------

    def _al_pulsar_enter(self, _evento):
        self._enviar()
        return "break"       # sin esto, Tk mete ademas el salto de linea

    def _enviar(self, texto: str = "") -> None:
        if self.trabajando:
            return
        if not self.backend:
            messagebox.showerror("Sin conexion con Claude",
                                 "No hay ni CLI de Claude ni API key.")
            return

        texto = (texto or self.mensaje.get("1.0", "end-1c")).strip()
        if not texto:
            return

        if self.conversacion is None:
            try:
                reglas = self._reglas_elegidas()
            except RuntimeError as exc:
                messagebox.showerror("Reglas", str(exc))
                return
            self.conversacion = gui.Conversacion(
                reglas=reglas, backend=self.backend, trabajo=self.carpeta)
            self._escribir_charla(
                f"— reglas: {self.perfil.get()} —", "nota")

        self.mensaje.delete("1.0", "end")
        self._pintar_atajos([])
        self._escribir_charla(f"Tú: {texto}", "tu")

        self.trabajando = True
        self.boton_enviar.state(["disabled"])
        self.barra.start(12)
        self._decir("Claude esta escribiendo. Si busca datos, tarda mas.")

        threading.Thread(target=self._trabajar, args=(texto,),
                         daemon=True).start()

    def _trabajar(self, texto: str) -> None:
        """Corre en el hilo secundario: aqui no se toca ningun widget."""
        try:
            respuesta = self.conversacion.enviar(texto)
            self.cola.put(("respuesta", 0, respuesta))
        except Exception as exc:
            self.cola.put(("error", 0, str(exc)))

    def _reiniciar(self) -> None:
        if self.trabajando:
            return
        if self.conversacion and not messagebox.askyesno(
                "Empezar de cero",
                "Se olvida la conversacion con Claude. El guion que ya has "
                "recogido se queda como esta.\n\nSigo?"):
            return
        self.conversacion = None
        self.charla.delete("1.0", "end")
        self._pintar_atajos([])
        self._decir(PISTA_INICIAL)
        self.mensaje.focus_set()

    # ----------------------------------------------------------------
    # Cola
    # ----------------------------------------------------------------

    def _vaciar_cola(self) -> None:
        try:
            while True:
                clase, numero, texto = self.cola.get_nowait()

                if clase == "respuesta":
                    self._recibir(texto)

                elif clase == "voz":
                    self._decir(f"Narrando... {numero} % ({texto})")

                elif clase == "voz-fin":
                    self._liberar()
                    self._decir(f"Narracion guardada en {Path(texto).name}")

                elif clase == "montaje":
                    # las lineas que el CLI ya imprime valen tal cual: estan
                    # escritas para leerlas
                    self._escribir_charla(texto, "nota")
                    self._decir(texto.strip())

                elif clase == "montaje-fin":
                    self._liberar()
                    if numero == 0:
                        self._decir("Borrador montado. Abrelo en CapCut.")
                    else:
                        self._decir("El montaje ha fallado.")
                        messagebox.showerror(
                            "No ha salido",
                            f"El montaje ha terminado con error ({numero}).\n\n"
                            f"Ultima linea:\n{texto}")

                elif clase == "bajada-empieza":
                    self.texto_bajada = texto
                    self._registrar(texto, nueva=True)

                elif clase == "bajada":
                    self._registrar(f"{self.texto_bajada}  {numero:.0f} %",
                                    nueva=False)

                elif clase == "bajada-fin":
                    self._acabar_bajada(bool(numero), texto)

                elif clase == "bajada-larga":
                    self._ofrecer_largo(numero, texto)

                elif clase == "bajada-nota":
                    self._registrar(texto, nueva=True)
                    self.aviso_bajada.configure(text="sin yt-dlp")

                elif clase == "yt-dlp":
                    self._responder_ytdlp(bool(numero), texto)

                elif clase == "error":
                    self._liberar()
                    self._decir("Ha fallado.")
                    messagebox.showerror("No ha salido", texto)
        except queue.Empty:
            pass

        self.tarea = self.raiz.after(120, self._vaciar_cola)

    def _recibir(self, respuesta: str) -> None:
        self.trabajando = False
        self.barra.stop()
        self.boton_enviar.state(["!disabled"])

        # las busquedas se apartan antes: no son guion ni son charla, y en el
        # chat solo estorbarian
        busquedas, respuesta = gui.extraer_busquedas(respuesta)
        if busquedas:
            self._recibir_clips(busquedas)
            cuantas = sum(len(v) for v in busquedas.values())
            self._escribir_charla(
                f"[{cuantas} busquedas en {len(busquedas)} partes "
                f"-> pestaña Clips]", "nota")

        publicacion, respuesta = gui.extraer_publicacion(respuesta)
        if publicacion:
            self._recibir_publicacion(publicacion)
            self._escribir_charla(
                "[titulos y descripcion -> pestaña Publicacion]", "nota")

        bloques, charla = gui.extraer_guion(respuesta)

        if charla:
            self._escribir_charla(charla, "claude")
        if bloques:
            palabras = sum(len(b.split()) for b in bloques)
            cuantos = ("1 trozo" if len(bloques) == 1
                       else f"{len(bloques)} trozos")
            self._escribir_charla(
                f"[{cuantos} de guion, {palabras} palabras -> pestaña Guion]",
                "nota")
            self._sumar_al_guion(bloques)
        elif not charla and not busquedas and not publicacion:
            # respuesta rara: mejor ensenarla cruda que tragarsela
            self._escribir_charla(respuesta, "claude")

        self._pintar_atajos(gui.atajos(charla))
        self._decir(self._resumen_guion())
        self.mensaje.focus_set()

    # ----------------------------------------------------------------
    # Clips
    # ----------------------------------------------------------------

    def _busquedas_actuales(self) -> dict[int, list[str]]:
        return gui.leer_busquedas(self.clips.get("1.0", "end-1c"))

    def _pintar_botones_partes(self) -> None:
        if getattr(self, "combo_parte", None) is not None:
            self._refrescar_destinos()
        for hijo in self.barra_partes.winfo_children():
            hijo.destroy()
        for numero in sorted(self._busquedas_actuales()):
            ttk.Button(self.barra_partes, text=f"Parte {numero}",
                       width=9,
                       command=lambda n=numero: self._abrir_busquedas(n),
                       ).pack(side="left", padx=(0, 4))

    def _pedir_clips(self) -> None:
        if self.trabajando:
            return
        if self.conversacion is None:
            messagebox.showinfo(
                "Todavia no",
                "Las busquedas salen del guion, asi que primero hay que "
                "escribirlo. Empieza la conversacion en la otra pestaña.")
            return
        if self.clips.get("1.0", "end-1c").strip() and not messagebox.askyesno(
                "Ya hay busquedas",
                "Se van a sustituir las que hay ahora. Sigo?"):
            return
        self._enviar(gui.PEDIR_CLIPS)

    def _recibir_clips(self, busquedas: dict[int, list[str]]) -> None:
        self.clips.delete("1.0", "end")
        self.clips.insert("1.0", gui.texto_busquedas(busquedas))
        self._pintar_botones_partes()
        self.pestanas.select(2)

    def _abrir_busquedas(self, numero: int) -> None:
        terminos = self._busquedas_actuales().get(numero, [])
        if not terminos:
            return
        if len(terminos) > 3 and not messagebox.askyesno(
                "Abrir el navegador",
                f"Se van a abrir {len(terminos)} pestañas con las busquedas "
                f"de la parte {numero}.\n\nSigo?"):
            return
        for termino in terminos:
            webbrowser.open_new_tab(BUSCADOR.format(quote_plus(termino)))
        self._decir(f"Abiertas {len(terminos)} busquedas de la parte "
                    f"{numero}.")

    def _guardar_clips(self) -> None:
        busquedas = self._busquedas_actuales()
        if not busquedas:
            messagebox.showwarning(
                "Vacio",
                "No hay busquedas que guardar. Tienen que ir con su cabecera: "
                "una linea 'PARTE 1' y debajo las busquedas, una por linea.")
            return

        escritos = proy.guardar_busquedas(self.carpeta, busquedas)
        cuantas = sum(len(v) for v in busquedas.values())
        donde = ", ".join(sorted(p.parent.name for p in escritos))
        self._decir(f"{cuantas} busquedas guardadas en {donde}.")
        self._pintar_botones_partes()

    # ----------------------------------------------------------------
    # Descargar los clips
    # ----------------------------------------------------------------

    def _refrescar_destinos(self) -> None:
        """
        Las carpetas parteN que hay ahora mismo en el disco.

        Se releen en vez de guardarse porque la carpeta se toca por fuera:
        parte5 puede aparecer mientras la ventana esta abierta.
        """
        carpetas = [c.name for c in proy.partes_de(self.carpeta)]
        # sin parteN, el destino es la carpeta a secas: es el mismo caso que
        # ya contempla edl.py, todos los videos en una sola parte
        valores = carpetas or [SIN_PARTES]
        self.combo_parte.configure(values=valores)
        if self.parte_destino.get() not in valores:
            self.parte_destino.set(valores[0])

    def _carpeta_destino(self) -> Path:
        elegida = self.parte_destino.get()
        return self.carpeta if elegida == SIN_PARTES else self.carpeta / elegida

    def _cambiar_escucha(self) -> None:
        if not self.escuchando.get():
            self._decir("Portapapeles: ya no escucho.")
            self.aviso_bajada.configure(text="")
            return

        # lo que ya estaba copiado no se baja: se apunta como visto para que
        # solo cuente lo que se copie a partir de ahora
        self.ultimo_copiado = self._portapapeles()

        if self.yt_dlp_listo is None:
            self.aviso_bajada.configure(text="comprobando yt-dlp...")
            threading.Thread(target=self._comprobar_ytdlp, daemon=True).start()
        elif not self.yt_dlp_listo:
            self._responder_ytdlp(False, "")
            return

        self._decir(f"Copia el enlace de un video y cae en "
                    f"{self.parte_destino.get()}.")

    def _portapapeles(self) -> str:
        try:
            return self.raiz.clipboard_get()
        except tk.TclError:
            # vacio, o con algo que no es texto (una imagen). Ninguna de las
            # dos cosas es un error: es lo normal a media tarde.
            return ""

    def _vigilar_portapapeles(self) -> None:
        """
        El unico gesto que queda: copiar el enlace.

        Se sondea en vez de escuchar un evento porque Windows no avisa a nadie
        cuando cambia el portapapeles sin registrarse en la cadena del sistema,
        y eso desde tkinter no se puede.
        """
        if self.escuchando.get():
            copiado = self._portapapeles()
            if copiado != self.ultimo_copiado:
                self.ultimo_copiado = copiado
                enlace = desc.es_enlace(copiado)
                if enlace:
                    self._encolar(enlace)
        self.vigilancia = self.raiz.after(LATIDO_PORTAPAPELES,
                                          self._vigilar_portapapeles)

    def _encolar(self, url: str) -> None:
        if url in self.ya_bajados:
            self._decir("Ese ya estaba.")
            return
        if self.yt_dlp_listo is False:
            return

        self._a_la_cola(url, self._carpeta_destino(), forzar=False)

    def _a_la_cola(self, url: str, destino: Path, forzar: bool) -> None:
        self.ya_bajados.add(url)
        self.urls_en_cola.append((url, destino))
        self.bajando += 1
        self.pendientes.put((url, destino, forzar))

        self._arrancar_trabajador()
        self.aviso_bajada.configure(text=f"{self.bajando} en cola")

    def _arrancar_trabajador(self) -> None:
        if getattr(self, "trabajador", None) and self.trabajador.is_alive():
            return
        self.trabajador = threading.Thread(target=self._trabajar_descargas,
                                           daemon=True)
        self.trabajador.start()

    def _trabajar_descargas(self) -> None:
        """
        Hilo secundario: ni un widget desde aqui.

        De una en una y no en paralelo, y no es por prudencia: bajando cuatro
        a la vez ninguna termina, el ancho de banda es el mismo, y ademas el
        numero del archivo se calcula mirando la carpeta —dos descargas
        simultaneas pedirian el mismo numero y una pisaria a la otra.
        """
        while True:
            url, destino, forzar = self.pendientes.get()
            ultimo = [-10.0]

            def avanzar(porcentaje: float, linea: str) -> None:
                # solo de cinco en cinco: cada linea de yt-dlp seria un
                # mensaje, y la cola se llenaria de repintados inutiles
                if porcentaje >= 0 and porcentaje - ultimo[0] >= 5:
                    ultimo[0] = porcentaje
                    self.cola.put(("bajada", porcentaje, ""))

            self.cola.put(("bajada-empieza", 0, f"bajando   {destino.name}"))
            try:
                ruta = desc.descargar(
                    url, destino, progreso=avanzar,
                    # aceptado a mano: se baja largo y todo
                    duracion_maxima=0 if forzar else desc.DURACION_MAXIMA_S)
                self.cola.put(("bajada-fin", 0,
                               f"listo     {destino.name}\\{ruta.name}"))
            except desc.DemasiadoLargo as largo:
                self.cola.put(("bajada-larga", largo.duracion_s, largo.titulo))
            except desc.SinYtDlp:
                self.cola.put(("bajada-fin", 1,
                               "falta yt-dlp: no se ha podido descargar"))
            except Exception as exc:
                # en una sola linea: el registro lleva una por descarga y la
                # reescribe, y un salto aqui le descuadraria la cuenta
                razon = " ".join(str(exc).split())[:150]
                self.cola.put(("bajada-fin", 1, f"fallo     {url} - {razon}"))
            finally:
                self.pendientes.task_done()

    def _pista_registro(self) -> None:
        """
        Un registro vacio no explica lo que es. Este dice para que sirve.

        Se borra sola en cuanto cae la primera linea de verdad; 'hay_pista'
        es lo que evita que quede pegada encima de la primera descarga.
        """
        self.hay_pista = True
        self.registro.configure(state="normal")
        self.registro.delete("1.0", "end")
        self.registro.insert(
            "1.0",
            "Aqui van apareciendo los clips segun se bajan. No se escribe "
            "aqui.\n"
            "Copia el enlace de un video de YouTube y cae solo en la carpeta "
            "de arriba.")
        self.registro.tag_add("pista", "1.0", "end")
        self.registro.tag_configure("pista", foreground="#999")
        self.registro.configure(state="disabled")

    def _registrar(self, texto: str, nueva: bool) -> None:
        """
        Una linea por descarga, reescrita segun avanza.

        Reescribir en vez de ir anadiendo porque si no, una sola descarga
        llenaria el registro de veinte lineas con el mismo nombre y otro
        porcentaje.
        """
        self.registro.configure(state="normal")
        if self.hay_pista:
            self.registro.delete("1.0", "end")
            self.hay_pista = False
        if nueva or self.linea_registro is None:
            if self.registro.get("1.0", "end-1c"):
                self.registro.insert("end", "\n")
            self.linea_registro = int(
                self.registro.index("end-1c").split(".")[0])
        self.registro.delete(f"{self.linea_registro}.0",
                             f"{self.linea_registro}.end")
        self.registro.insert(f"{self.linea_registro}.0", texto)
        self.registro.see("end")
        self.registro.configure(state="disabled")

    def _sacar_de_la_cola(self) -> tuple[str, Path | None]:
        """La que termina es siempre la primera: se atienden de una en una."""
        return self.urls_en_cola.pop(0) if self.urls_en_cola else ("", None)

    def _ofrecer_largo(self, duracion: float, titulo: str) -> None:
        """
        Un video largo no se descarta solo: se pregunta.

        Un recopilatorio de dos horas puede ser justo el material que quieres
        -paisajes, vuelos de dron-, pero son gigas para sacar cuatro segundos,
        y enterarse a mitad de la descarga es tarde.
        """
        self.bajando = max(0, self.bajando - 1)
        url, destino = self._sacar_de_la_cola()
        cuanto = desc.formato_duracion(duracion)
        self._registrar(f"largo     {titulo} ({cuanto})", nueva=False)
        self.aviso_bajada.configure(
            text=f"{self.bajando} en cola" if self.bajando else "")

        if destino is not None and messagebox.askyesno(
                "Video largo",
                f"{titulo}\n\nDura {cuanto}, y de ahi el montaje usa unos "
                f"segundos. Ocupara bastante en el disco.\n\nLo bajo igual?"):
            self._a_la_cola(url, destino, forzar=True)
            return

        self.ya_bajados.discard(url)
        self._decir(f"Saltado por largo: {titulo}")

    def _acabar_bajada(self, fallo: bool, texto: str) -> None:
        self.bajando = max(0, self.bajando - 1)
        url, _ = self._sacar_de_la_cola()
        self._registrar(texto, nueva=False)
        self.aviso_bajada.configure(
            text=f"{self.bajando} en cola" if self.bajando else "")
        if fallo:
            # el enlace se olvida para que copiarlo otra vez lo reintente, que
            # es lo que se hace cuando un video da error a la primera
            self.ya_bajados.discard(url)
            self._decir("Una descarga ha fallado. Mira el registro.")
        else:
            self._decir(texto.strip())

    # ---- yt-dlp ----

    def _comprobar_ytdlp(self) -> None:
        """Hilo secundario: arrancar un proceso tarda y congelaria la ventana."""
        version = desc.version()
        self.cola.put(("yt-dlp", 1 if version else 0, version))

    def _responder_ytdlp(self, hay: bool, version: str) -> None:
        self.yt_dlp_listo = hay
        if hay:
            self.aviso_bajada.configure(text=f"yt-dlp {version}")
            return

        self.aviso_bajada.configure(text="sin yt-dlp")
        if not messagebox.askyesno(
                "Falta yt-dlp",
                "Para bajar los videos hace falta yt-dlp, que no esta "
                "instalado.\n\nSe instala con pip en este mismo Python y "
                "ocupa poco. El resto del montador funciona igual sin el.\n\n"
                "Lo instalo?"):
            self.escuchando.set(False)
            return
        self._instalar_ytdlp()

    def _instalar_ytdlp(self) -> None:
        self._registrar("instalando yt-dlp...", nueva=True)
        self.aviso_bajada.configure(text="instalando...")
        threading.Thread(target=self._trabajar_instalacion,
                         daemon=True).start()

    def _trabajar_instalacion(self) -> None:
        """Hilo secundario: ni un widget desde aqui."""
        bien, salida = desc.instalar()
        if bien:
            self.cola.put(("yt-dlp", 1, desc.version()))
        else:
            # 'nota' y no 'bajada-fin': aqui no ha terminado ninguna descarga,
            # y descontarla del contador lo dejaria en negativo
            self.cola.put(("bajada-nota", 1,
                           f"no se ha podido instalar yt-dlp\n{salida}"))

    # ----------------------------------------------------------------
    # Publicacion
    # ----------------------------------------------------------------

    def _pedir_publicacion(self) -> None:
        if self.trabajando:
            return
        if self.conversacion is None:
            messagebox.showinfo(
                "Todavia no",
                "El titulo y la descripcion salen del guion, asi que primero "
                "hay que escribirlo. Empieza la conversacion en la otra "
                "pestaña.")
            return
        if (self.publicacion.get("1.0", "end-1c").strip()
                and not messagebox.askyesno(
                    "Ya hay titulos",
                    "Se van a sustituir los que hay ahora. Sigo?")):
            return
        self._enviar(gui.PEDIR_PUBLICACION)

    def _recibir_publicacion(self, texto: str) -> None:
        self.publicacion.delete("1.0", "end")
        self.publicacion.insert("1.0", texto)
        self.pestanas.select(3)

    def _guardar_publicacion(self) -> None:
        texto = self.publicacion.get("1.0", "end-1c").strip()
        if not texto:
            messagebox.showwarning(
                "Vacio", "No hay nada que guardar. Pideselo a Claude o "
                         "escribelo aqui.")
            return

        ruta = proy.guardar_publicacion(self.carpeta, texto)
        self._decir(f"Titulos y descripcion guardados en {ruta.name}.")

    # ----------------------------------------------------------------
    # Guardado
    # ----------------------------------------------------------------

    def _guardar(self) -> None:
        texto = self.guion.get("1.0", "end-1c").strip()
        if not texto:
            messagebox.showwarning(
                "Vacio", "No hay guion que guardar. Lo que Claude te dice "
                         "en la conversacion no cuenta como guion: solo "
                         "cuenta lo que aparece en la pestaña Guion.")
            return

        destino = gui.guardar(self.carpeta, texto + "\n")
        self.guardado = destino

        marcas = texto.count("[TXT:")
        cuenta = ("1 rotulo marcado" if marcas == 1
                  else f"{marcas} rotulos marcados")
        self._decir(f"Guardado en {destino.name}, con {cuenta}.")

    # ----------------------------------------------------------------
    # Narracion
    # ----------------------------------------------------------------

    def _generar_voz(self) -> None:
        if self.trabajando:
            return

        texto = self.guion.get("1.0", "end-1c").strip()
        if not texto:
            messagebox.showwarning("Vacio", "No hay guion que narrar.")
            return

        try:
            voz.clave()
        except voz.SinClave as exc:
            messagebox.showerror("Falta la clave de ai33.pro", str(exc))
            return

        # el audio sale del guion, asi que se deja guardado lo que se ha
        # narrado: si no, el mp3 y el .txt de la carpeta dirian cosas distintas
        self._guardar()

        locutable = voz.texto_locutable(texto)
        if not messagebox.askyesno(
                "Generar la voz",
                f"Se van a narrar {len(locutable)} caracteres "
                f"con {voz.NOMBRE_VOZ}.\n\n"
                f"El resultado se guarda como narracion.mp3 en la carpeta. "
                f"Sigo?"):
            return

        self.trabajando = True
        self.boton_voz.state(["disabled"])
        self.boton_enviar.state(["disabled"])
        self.barra.start(12)
        self._decir("Enviando el guion a ai33.pro...")

        threading.Thread(target=self._trabajar_voz, args=(texto,),
                         daemon=True).start()

    def _trabajar_voz(self, texto: str) -> None:
        """Hilo secundario: ni un widget desde aqui."""
        try:
            destino = voz.narrar(
                texto, self.carpeta,
                avance=lambda pct, est: self.cola.put(("voz", pct, est)))
            self.cola.put(("voz-fin", 0, str(destino)))
        except Exception as exc:
            self.cola.put(("error", 0, str(exc)))

    # ----------------------------------------------------------------
    # Montaje
    # ----------------------------------------------------------------

    def _montar(self) -> None:
        """
        Lo que hasta ahora habia que teclear en la consola:

            python -m montador montar --clips <carpeta> --proyecto <nombre>

        Los dos argumentos ya los sabe la ventana: la carpeta es en la que
        estamos trabajando y el nombre del borrador se deduce de ella.

        Va en un proceso aparte, no llamando a cmd_montar() aqui mismo, por
        tres razones: Whisper tarda minutos y se lleva mucha memoria, un fallo
        suyo no debe llevarse por delante la conversacion, y las lineas de
        avance que el CLI ya imprime se pintan en la charla sin inventar otro
        mecanismo.
        """
        if self.trabajando:
            return

        # montar con descargas a medias saldria con menos clips de los que
        # vas a tener, y ademas con un .part suelto en la carpeta
        if self.bajando and not messagebox.askyesno(
                "Quedan descargas",
                f"Todavia estan bajando {self.bajando} clip(s). Si montas "
                f"ahora, esos no entran.\n\nMonto igual?"):
            return

        # el montaje lee el guion.txt de la carpeta, no la pestaña: sin
        # guardar antes, los rotulos saldrian de una version vieja
        if self.guion.get("1.0", "end-1c").strip():
            self._guardar()

        errores, avisos = proy.revisar(self.carpeta)
        if errores:
            messagebox.showerror(
                "Falta material",
                "Todavia no se puede montar:\n\n  "
                + "\n  ".join(errores)
                + f"\n\nTodo eso va dentro de {self.carpeta.name}.")
            return

        if _capcut_abierto():
            messagebox.showwarning(
                "CapCut esta abierto",
                "Cierra CapCut y vuelve a darle. Mantiene el proyecto en "
                "memoria y al cerrarse lo reescribe encima del generado.")
            return

        nombre = proy.nombre_proyecto(self.carpeta)
        aviso = "Aviso:\n  " + "\n  ".join(avisos) + "\n\n" if avisos else ""
        if not messagebox.askyesno(
                "Montar en CapCut",
                f"Se va a montar el borrador '{nombre}' con lo que hay en "
                f"{self.carpeta.name}.\n\n{aviso}"
                f"Si ya existe un borrador con ese nombre, se reemplaza.\n"
                f"La primera vez tarda varios minutos: transcribir la "
                f"narracion es lo lento.\n\nSigo?"):
            return

        self._ocupar(self.boton_montar, self.boton_voz, self.boton_enviar)
        self._escribir_charla(f"[montando el borrador '{nombre}']", "nota")
        self._decir("Montando...")

        threading.Thread(target=self._trabajar_montaje, args=(nombre,),
                         daemon=True).start()

    def _trabajar_montaje(self, nombre: str) -> None:
        """Hilo secundario: ni un widget desde aqui."""
        try:
            proceso = subprocess.Popen(
                [sys.executable, "-m", "montador", "montar",
                 "--clips", str(self.carpeta), "--proyecto", nombre],
                cwd=str(RAIZ),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                bufsize=1, creationflags=SIN_CONSOLA)
        except Exception as exc:
            self.cola.put(("error", 0, str(exc)))
            return

        ultima = ""
        for linea in proceso.stdout:
            linea = linea.rstrip()
            if linea:
                ultima = linea
                self.cola.put(("montaje", 0, linea))
        self.cola.put(("montaje-fin", proceso.wait(), ultima))

    def abrir(self) -> Path | None:
        self.raiz.mainloop()
        return self.guardado


def _capcut_abierto() -> bool:
    """
    Aviso, no comprobacion fiable: si tasklist no esta o falla, se deja pasar.

    Importa porque CapCut abierto tiene el proyecto en memoria y al cerrarse lo
    reescribe encima del que acabamos de generar.
    """
    try:
        salida = subprocess.run(
            ["tasklist", "/fi", "imagename eq CapCut.exe"],
            capture_output=True, text=True, timeout=10,
            creationflags=SIN_CONSOLA).stdout
    except Exception:
        return False
    return "CapCut.exe" in salida


def escribir_guion(carpeta: Path, partes: int = 0,
                   perfil: str = "") -> Path | None:
    """
    Abre la ventana y devuelve la ruta del guion si se ha guardado.

    'partes' ya no decide nada: en la conversacion las partes las marca el
    perfil de reglas, no el montador. Se conserva el parametro para no
    romper a quien llame con el.
    """
    return VentanaGuion(Path(carpeta), partes, perfil).abrir()
