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
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, ttk
from urllib.parse import quote_plus

from . import guionista as gui
from . import perfiles as perf
from . import proyecto as proy
from . import voz

# Busqueda de YouTube. Se deja a la vista para poder cambiarla: hay dias en
# que el material bueno esta en otro sitio.
BUSCADOR = "https://www.youtube.com/results?search_query={}"

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
        self.raiz.protocol("WM_DELETE_WINDOW", self.cerrar)

    def cerrar(self) -> None:
        if self.tarea is not None:
            self.raiz.after_cancel(self.tarea)
            self.tarea = None
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

        abajo = ttk.Frame(marco, padding=(8, 6, 8, 8))
        abajo.grid(row=2, column=0, sticky="ew")
        ttk.Label(abajo, text="Abrir en el navegador:").pack(side="left",
                                                             padx=(0, 8))
        self.barra_partes = ttk.Frame(abajo)
        self.barra_partes.pack(side="left")

        self._pintar_botones_partes()
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
                    self.trabajando = False
                    self.barra.stop()
                    self.boton_voz.state(["!disabled"])
                    self.boton_enviar.state(["!disabled"])
                    self._decir(f"Narracion guardada en {Path(texto).name}")

                elif clase == "error":
                    self.trabajando = False
                    self.barra.stop()
                    self.boton_enviar.state(["!disabled"])
                    self.boton_voz.state(["!disabled"])
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
        elif not charla and not busquedas:
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

    def abrir(self) -> Path | None:
        self.raiz.mainloop()
        return self.guardado


def escribir_guion(carpeta: Path, partes: int = 0,
                   perfil: str = "") -> Path | None:
    """
    Abre la ventana y devuelve la ruta del guion si se ha guardado.

    'partes' ya no decide nada: en la conversacion las partes las marca el
    perfil de reglas, no el montador. Se conserva el parametro para no
    romper a quien llame con el.
    """
    return VentanaGuion(Path(carpeta), partes, perfil).abrir()
