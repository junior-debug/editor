"""
La rejilla de resultados: elegir clips sin salir de la ventana.

Antes, cada busqueda abria una pestaña del navegador y habia que ir viendo
videos y copiando enlaces. Con veinte clips de media por montaje, eso son
sesenta o setenta videos abiertos y cerrados en cada uno.

Aqui los resultados llegan con **su duracion delante**, que es lo que mas
descarta: uno de doce minutos es una charla y uno de treinta segundos es el
plano que se busca, y hasta ahora eso no se sabia hasta abrirlo.

No se pierde la revision a ojo, que es lo que el usuario dijo que le sirve:
doble clic en cualquier resultado lo abre en YouTube. Lo que se quita es
abrir diez pestañas para descartar siete.

Las miniaturas van en PNG porque es lo que lee tkinter sin ayuda, y las
convierte ffmpeg, que ya esta. Las PhotoImage se guardan en una lista de la
ventana **a proposito**: si no se conserva la referencia, el recolector se
las lleva y la rejilla se queda en blanco.
"""

from __future__ import annotations

import queue
import tempfile
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, ttk

from . import descargas as desc

POR_FILA = 2
CUANTOS = 8


class VentanaResultados:
    def __init__(self, padre, terminos: list[str], parte: str):
        self.terminos = terminos
        self.parte = parte
        self.cola: queue.Queue = queue.Queue()
        self.marcados: dict[str, desc.Resultado] = {}
        self.elegidos: list[str] = []
        self.imagenes: list = []      # sin esto, tkinter borra las miniaturas
        self.resultados: list[desc.Resultado] = []
        self.buscando = False
        self.tarea = None
        self.cache = Path(tempfile.gettempdir()) / "montador_miniaturas"

        self.raiz = tk.Toplevel(padre)
        self.raiz.title(f"Buscar clips para {parte}")
        self.raiz.geometry("980x620")
        self.raiz.minsize(760, 480)

        self._construir()
        self.tarea = self.raiz.after(120, self._vaciar_cola)
        self.raiz.protocol("WM_DELETE_WINDOW", self._cerrar)
        if terminos:
            self.lista.selection_set(0)
            self._buscar()

    # ----------------------------------------------------------------

    def _construir(self) -> None:
        marco = ttk.Frame(self.raiz, padding=10)
        marco.pack(fill="both", expand=True)
        marco.columnconfigure(1, weight=1)
        marco.rowconfigure(0, weight=1)

        # ---- los terminos, a la izquierda ----
        izq = ttk.Frame(marco)
        izq.grid(row=0, column=0, sticky="ns", padx=(0, 10))
        izq.rowconfigure(1, weight=1)
        ttk.Label(izq, text="Busquedas de esta parte").grid(row=0, column=0,
                                                            sticky="w")
        self.lista = tk.Listbox(izq, width=32, exportselection=False,
                                font=("Segoe UI", 9))
        self.lista.grid(row=1, column=0, sticky="ns", pady=(4, 0))
        for t in self.terminos:
            self.lista.insert("end", t)
        self.lista.bind("<<ListboxSelect>>", lambda _e: self._buscar())

        # ---- la rejilla, a la derecha ----
        der = ttk.Frame(marco)
        der.grid(row=0, column=1, sticky="nsew")
        der.columnconfigure(0, weight=1)
        der.rowconfigure(1, weight=1)

        self.barra = ttk.Progressbar(der, mode="indeterminate")
        self.barra.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        # Canvas + frame interior: es la unica forma de tener scroll sobre
        # una rejilla de widgets en tkinter
        self.lienzo = tk.Canvas(der, highlightthickness=0, background="#fafafa")
        self.lienzo.grid(row=1, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(der, orient="vertical",
                               command=self.lienzo.yview)
        scroll.grid(row=1, column=1, sticky="ns")
        self.lienzo.configure(yscrollcommand=scroll.set)

        self.rejilla = ttk.Frame(self.lienzo)
        self.ventana_rejilla = self.lienzo.create_window(
            (0, 0), window=self.rejilla, anchor="nw")
        self.rejilla.bind(
            "<Configure>",
            lambda _e: self.lienzo.configure(
                scrollregion=self.lienzo.bbox("all")))
        self.lienzo.bind(
            "<Configure>",
            lambda e: self.lienzo.itemconfigure(self.ventana_rejilla,
                                                width=e.width))
        self.lienzo.bind_all("<MouseWheel>", self._rueda)

        # ---- pie ----
        pie = ttk.Frame(marco)
        pie.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        pie.columnconfigure(0, weight=1)
        self.estado = ttk.Label(pie, text="", foreground="#555")
        self.estado.grid(row=0, column=0, sticky="w")

        ttk.Button(pie, text="Abrir en el navegador",
                   command=self._en_navegador).grid(row=0, column=1, padx=(6, 0))
        self.boton_bajar = ttk.Button(
            pie, text=f"Bajar los marcados a {self.parte}",
            command=self._bajar)
        self.boton_bajar.grid(row=0, column=2, padx=(6, 0))

    def _rueda(self, evento) -> None:
        self.lienzo.yview_scroll(-1 if evento.delta > 0 else 1, "units")

    def _decir(self, mensaje: str) -> None:
        self.estado.configure(text=mensaje)

    def _termino(self) -> str:
        cual = self.lista.curselection()
        return self.terminos[cual[0]] if cual else ""

    # ----------------------------------------------------------------

    def _buscar(self) -> None:
        termino = self._termino()
        if not termino or self.buscando:
            return
        self.buscando = True
        self.barra.start(12)
        self._decir(f"Buscando: {termino}")
        self._limpiar()
        threading.Thread(target=self._trabajar, args=(termino,),
                         daemon=True).start()

    def _trabajar(self, termino: str) -> None:
        """Hilo secundario: ni un widget desde aqui."""
        try:
            resultados = desc.buscar(termino, CUANTOS)
            self.cola.put(("resultados", resultados))
            for r in resultados:
                ruta = desc.miniatura(r, self.cache)
                if ruta:
                    self.cola.put(("miniatura", (r.id, ruta)))
        except Exception as exc:
            self.cola.put(("error", str(exc)))

    def _limpiar(self) -> None:
        for hijo in self.rejilla.winfo_children():
            hijo.destroy()
        self.imagenes.clear()
        self.tarjetas = {}

    def _vaciar_cola(self) -> None:
        try:
            while True:
                clase, dato = self.cola.get_nowait()
                if clase == "error":
                    self.buscando = False
                    self.barra.stop()
                    self._decir("La busqueda ha fallado.")
                    messagebox.showerror("No ha salido", dato)
                elif clase == "resultados":
                    self.buscando = False
                    self.barra.stop()
                    self.resultados = dato
                    self._pintar(dato)
                elif clase == "miniatura":
                    self._poner_miniatura(*dato)
        except queue.Empty:
            pass
        self.tarea = self.raiz.after(120, self._vaciar_cola)

    # ----------------------------------------------------------------

    def _pintar(self, resultados: list[desc.Resultado]) -> None:
        if not resultados:
            self._decir("Sin resultados para esa busqueda.")
            return
        for i, r in enumerate(resultados):
            self._tarjeta(r, i // POR_FILA, i % POR_FILA)
        for c in range(POR_FILA):
            self.rejilla.columnconfigure(c, weight=1)
        marcados = len(self.marcados)
        self._decir(f"{len(resultados)} resultados. Doble clic para verlo en "
                    f"YouTube. {marcados} marcados.")

    def _tarjeta(self, r: desc.Resultado, fila: int, columna: int) -> None:
        tarjeta = ttk.Frame(self.rejilla, padding=6, relief="groove",
                            borderwidth=1)
        tarjeta.grid(row=fila, column=columna, sticky="nsew", padx=4, pady=4)
        tarjeta.columnconfigure(1, weight=1)

        marca = tk.BooleanVar(value=r.id in self.marcados)
        casilla = ttk.Checkbutton(
            tarjeta, variable=marca,
            command=lambda: self._marcar(r, marca.get()))
        casilla.grid(row=0, column=0, rowspan=2, sticky="n")

        hueco = tk.Label(tarjeta, width=25, height=6, background="#e8e8e8",
                         text="...", cursor="hand2")
        hueco.grid(row=0, column=1, rowspan=2, sticky="w", padx=(4, 8))
        hueco.bind("<Double-1>", lambda _e: webbrowser.open_new_tab(r.url))

        # la duracion delante del titulo: es lo que mas descarta de un vistazo
        color = "#b00" if r.larga else "#0a7a3d"
        ttk.Label(tarjeta, text=r.duracion, foreground=color,
                  font=("Segoe UI", 10, "bold")).grid(row=0, column=2,
                                                      sticky="ne")

        texto = tk.Label(tarjeta, text=r.titulo[:70], wraplength=250,
                         justify="left", anchor="w", cursor="hand2",
                         font=("Segoe UI", 9))
        texto.grid(row=1, column=2, sticky="nw")
        texto.bind("<Double-1>", lambda _e: webbrowser.open_new_tab(r.url))

        ttk.Label(tarjeta, text=r.canal[:34], foreground="#777",
                  font=("Segoe UI", 8)).grid(row=2, column=2, sticky="nw")

        self.tarjetas[r.id] = hueco

    def _poner_miniatura(self, id_video: str, ruta: Path) -> None:
        hueco = getattr(self, "tarjetas", {}).get(id_video)
        if hueco is None:
            return
        try:
            imagen = tk.PhotoImage(file=str(ruta))
        except tk.TclError:
            return
        # la referencia se guarda o el recolector se lleva la imagen y la
        # tarjeta se queda en blanco
        self.imagenes.append(imagen)
        hueco.configure(image=imagen, text="", width=0, height=0)

    def _marcar(self, r: desc.Resultado, puesto: bool) -> None:
        if puesto:
            self.marcados[r.id] = r
        else:
            self.marcados.pop(r.id, None)
        self._decir(f"{len(self.marcados)} marcados para bajar a {self.parte}.")

    # ----------------------------------------------------------------

    def _en_navegador(self) -> None:
        termino = self._termino()
        if termino:
            from urllib.parse import quote_plus
            webbrowser.open_new_tab(
                f"https://www.youtube.com/results?search_query={quote_plus(termino)}")

    def _bajar(self) -> None:
        if not self.marcados:
            messagebox.showinfo(
                "Nada marcado",
                "Marca la casilla de los videos que quieras antes de bajar.")
            return
        largos = [r for r in self.marcados.values() if r.larga]
        if largos and not messagebox.askyesno(
                "Alguno es largo",
                f"{len(largos)} de los marcados pasan de media hora y ocuparan "
                f"bastante.\n\nLos bajo igual?"):
            return
        self.elegidos = [r.url for r in self.marcados.values()]
        self._cerrar()

    def _cerrar(self) -> None:
        if self.tarea is not None:
            self.raiz.after_cancel(self.tarea)
            self.tarea = None
        self.lienzo.unbind_all("<MouseWheel>")
        self.raiz.destroy()

    def abrir(self) -> list[str]:
        self.raiz.grab_set()
        self.raiz.wait_window()
        return self.elegidos


def elegir_clips(padre, terminos: list[str], parte: str) -> list[str]:
    """Abre la rejilla y devuelve las URL marcadas para bajar."""
    return VentanaResultados(padre, terminos, parte).abrir()
