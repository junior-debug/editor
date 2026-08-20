"""
Ventana para escribir el guion con Claude.

Tkinter viene con Python, asi que no anade dependencias. La generacion corre
en un hilo aparte y se comunica por cola: si se llamara a Claude desde el hilo
de la ventana, esta se quedaria congelada varios minutos y Windows la marcaria
como "no responde".
"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from . import guionista as gui
from . import perfiles as perf
from . import proyecto as proy
from . import voz

MINUTOS_POR_DEFECTO = 13


class VentanaGuion:
    def __init__(self, carpeta: Path, partes: int = 4, perfil: str = ""):
        self.carpeta = Path(carpeta)
        self.perfil_inicial = perfil
        self.guardado: Path | None = None
        self.cola: queue.Queue = queue.Queue()
        self.trabajando = False
        self.tarea = None
        # aviso fijo que el contador de palabras no debe pisar
        self.nota = ""

        self.raiz = tk.Tk()
        self.raiz.title(f"Guion — {self.carpeta.name}")
        self.raiz.geometry("860x680")
        self.raiz.minsize(640, 480)

        try:
            self.backend = gui.detectar_backend()
        except gui.SinBackend as exc:
            self.backend = ""
            self.raiz.after(100, lambda: messagebox.showerror(
                "Sin conexion con Claude", str(exc)))

        self._construir(partes)
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

    def _construir(self, partes: int) -> None:
        marco = ttk.Frame(self.raiz, padding=12)
        marco.pack(fill="both", expand=True)
        marco.columnconfigure(0, weight=1)
        marco.rowconfigure(5, weight=1)

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
        reglas.grid(row=1, column=0, sticky="ew", pady=(12, 0))
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

        ttk.Label(marco, text="De que va el video:").grid(
            row=2, column=0, sticky="w", pady=(12, 2))

        self.tema = tk.Text(marco, height=5, wrap="word", undo=True)
        self.tema.grid(row=3, column=0, sticky="ew")
        self.tema.insert("1.0", "")
        self.tema.focus_set()

        opciones = ttk.Frame(marco)
        opciones.grid(row=4, column=0, sticky="ew", pady=10)

        ttk.Label(opciones, text="Minutos:").pack(side="left")
        self.minutos = ttk.Spinbox(opciones, from_=1, to=90, width=5)
        self.minutos.set(MINUTOS_POR_DEFECTO)
        self.minutos.pack(side="left", padx=(4, 16))

        ttk.Label(opciones, text="Partes:").pack(side="left")
        self.partes = ttk.Spinbox(opciones, from_=1, to=12, width=5)
        self.partes.set(max(1, partes))
        self.partes.pack(side="left", padx=(4, 16))

        self.boton_generar = ttk.Button(opciones, text="Escribir guion",
                                        command=self._generar)
        self.boton_generar.pack(side="left")

        self.barra = ttk.Progressbar(opciones, mode="determinate", length=160)
        self.barra.pack(side="left", padx=12)

        caja = ttk.Frame(marco)
        caja.grid(row=5, column=0, sticky="nsew")
        caja.columnconfigure(0, weight=1)
        caja.rowconfigure(0, weight=1)

        self.texto = tk.Text(caja, wrap="word", undo=True,
                             font=("Consolas", 10))
        self.texto.grid(row=0, column=0, sticky="nsew")
        barra_v = ttk.Scrollbar(caja, orient="vertical",
                                command=self.texto.yview)
        barra_v.grid(row=0, column=1, sticky="ns")
        self.texto.configure(yscrollcommand=barra_v.set)
        self.texto.bind("<<Modified>>", self._al_editar)

        pie = ttk.Frame(marco)
        pie.grid(row=6, column=0, sticky="ew", pady=(10, 0))
        pie.columnconfigure(0, weight=1)

        self.estado = ttk.Label(pie, text="Escribe el tema y dale a "
                                          "'Escribir guion'.")
        self.estado.grid(row=0, column=0, sticky="w")

        self.boton_voz = ttk.Button(pie, text=f"Generar voz ({voz.NOMBRE_VOZ})",
                                    command=self._generar_voz)
        self.boton_voz.grid(row=0, column=1, sticky="e", padx=(0, 6))

        self.boton_guardar = ttk.Button(pie, text="Guardar guion.txt",
                                        command=self._guardar)
        self.boton_guardar.grid(row=0, column=2, sticky="e")

        existente = self.carpeta / "guion.txt"
        if existente.exists():
            self.texto.insert("1.0", existente.read_text(encoding="utf-8"))
            self.nota = "Cargado el guion.txt que ya habia. "
            self._al_editar()

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
        top.geometry("720x560")
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

    def _al_editar(self, _evento=None) -> None:
        self.texto.edit_modified(False)
        palabras = len(self.texto.get("1.0", "end-1c").split())
        if palabras and not self.trabajando:
            minutos = palabras / gui.PALABRAS_POR_MINUTO
            self._decir(f"{self.nota}{palabras} palabras, unos "
                        f"{minutos:.1f} min de locucion.")

    # ----------------------------------------------------------------
    # Generacion
    # ----------------------------------------------------------------

    def _generar(self) -> None:
        if self.trabajando:
            return
        if not self.backend:
            messagebox.showerror("Sin conexion con Claude",
                                 "No hay ni CLI de Claude ni API key.")
            return

        tema = self.tema.get("1.0", "end-1c").strip()
        if not tema:
            messagebox.showwarning("Falta el tema",
                                   "Escribe de que va el video.")
            return

        if self.texto.get("1.0", "end-1c").strip():
            if not messagebox.askyesno(
                    "Ya hay texto",
                    "Se va a sustituir el guion que hay ahora. Sigo?"):
                return

        try:
            minutos = float(self.minutos.get())
            partes = int(self.partes.get())
        except ValueError:
            messagebox.showwarning("Numeros",
                                   "Minutos y partes tienen que ser numeros.")
            return

        try:
            reglas = self._reglas_elegidas()
        except RuntimeError as exc:
            messagebox.showerror("Reglas", str(exc))
            return

        self.nota = ""
        self.trabajando = True
        self.boton_generar.state(["disabled"])
        self.texto.delete("1.0", "end")
        self.barra.configure(maximum=partes, value=0)
        self._decir(f"Escribiendo la parte 1 de {partes} "
                    f"con las reglas '{self.perfil.get()}'...")

        hilo = threading.Thread(
            target=self._trabajar, args=(tema, minutos, partes, reglas),
            daemon=True)
        hilo.start()

    def _trabajar(self, tema: str, minutos: float, partes: int,
                  reglas: str) -> None:
        """Corre en el hilo secundario: aqui no se toca ningun widget."""
        try:
            gui.generar(
                tema, minutos, partes, backend=self.backend,
                trabajo=self.carpeta, reglas=reglas,
                avance=lambda n, t, texto: self.cola.put(("parte", n, t, texto)))
            self.cola.put(("fin", 0, 0, ""))
        except Exception as exc:
            self.cola.put(("error", 0, 0, str(exc)))

    def _vaciar_cola(self) -> None:
        try:
            while True:
                clase, n, total, texto = self.cola.get_nowait()

                if clase == "parte":
                    if self.texto.get("1.0", "end-1c").strip():
                        self.texto.insert("end", "\n\n")
                    self.texto.insert("end", texto.strip())
                    self.texto.see("end")
                    self.barra.configure(value=n)
                    if n < total:
                        self._decir(f"Escribiendo la parte {n + 1} "
                                    f"de {total}...")

                elif clase == "fin":
                    self.trabajando = False
                    self.boton_generar.state(["!disabled"])
                    self._al_editar()

                elif clase == "voz":
                    self.barra.configure(value=n)
                    self._decir(f"Narrando... {n} % ({texto})")

                elif clase == "voz-fin":
                    self.trabajando = False
                    self.boton_voz.state(["!disabled"])
                    self.boton_generar.state(["!disabled"])
                    self.barra.configure(value=100)
                    self._decir(f"Narracion guardada en {Path(texto).name}")

                elif clase == "error":
                    self.trabajando = False
                    self.boton_generar.state(["!disabled"])
                    self.boton_voz.state(["!disabled"])
                    self.barra.configure(value=0)
                    self._decir("Ha fallado.")
                    messagebox.showerror("No ha salido", texto)
        except queue.Empty:
            pass

        self.tarea = self.raiz.after(120, self._vaciar_cola)

    # ----------------------------------------------------------------
    # Guardado
    # ----------------------------------------------------------------

    def _guardar(self) -> None:
        texto = self.texto.get("1.0", "end-1c").strip()
        if not texto:
            messagebox.showwarning("Vacio", "No hay nada que guardar.")
            return

        destino = gui.guardar(self.carpeta, texto + "\n")
        self.guardado = destino

        marcas = texto.count("[TXT:")
        cuenta = "1 rotulo marcado" if marcas == 1 else f"{marcas} rotulos marcados"
        self._decir(f"Guardado en {destino.name}, con {cuenta}.")

    # ----------------------------------------------------------------
    # Narracion
    # ----------------------------------------------------------------

    def _generar_voz(self) -> None:
        if self.trabajando:
            return

        texto = self.texto.get("1.0", "end-1c").strip()
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
        self.boton_generar.state(["disabled"])
        self.barra.configure(maximum=100, value=0)
        self._decir("Enviando el guion a ai33.pro...")

        threading.Thread(target=self._trabajar_voz, args=(texto,),
                         daemon=True).start()

    def _trabajar_voz(self, texto: str) -> None:
        """Hilo secundario: ni un widget desde aqui."""
        try:
            destino = voz.narrar(
                texto, self.carpeta,
                avance=lambda pct, est: self.cola.put(("voz", pct, 0, est)))
            self.cola.put(("voz-fin", 0, 0, str(destino)))
        except Exception as exc:
            self.cola.put(("error", 0, 0, str(exc)))

    def abrir(self) -> Path | None:
        self.raiz.mainloop()
        return self.guardado


def escribir_guion(carpeta: Path, partes: int = 0,
                   perfil: str = "") -> Path | None:
    """
    Abre la ventana y devuelve la ruta del guion si se ha guardado.

    Por defecto propone tantas partes de guion como carpetas parteN haya:
    es el reparto que luego usa el EDL para ir metiendo material nuevo.
    """
    carpeta = Path(carpeta)
    if not partes:
        partes = len(proy.partes_de(carpeta)) or 4
    return VentanaGuion(carpeta, partes, perfil).abrir()
