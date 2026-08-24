"""
La ventana de ideas: de que hacer el proximo video.

Se abre desde la ventana de proyecto, que es el paso anterior a crear la
carpeta. El orden del trabajo es ese: primero se decide el tema y despues se
monta la carpeta con su nombre.

Claude busca en internet, asi que **tarda minutos**, no segundos. Por eso la
llamada va en un hilo con su barra y con un aviso que lo dice: una ventana
congelada cinco minutos se da por colgada y se cierra.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, ttk

from . import guionista as gui
from . import ideas as id_mod

CUANTAS_POR_DEFECTO = 6

COLORES = {
    id_mod.PROPUESTA: "#1a4f8a",
    id_mod.ELEGIDA: "#0a7a3d",
    id_mod.HECHA: "#666666",
    id_mod.DESCARTADA: "#999999",
}


class VentanaIdeas:
    def __init__(self, padre=None):
        self.cola: queue.Queue = queue.Queue()
        self.buscando = False
        self.elegida: id_mod.Idea | None = None
        self.tarea = None

        # Toplevel si ya hay una ventana viva, Tk si se abre suelta: dos Tk()
        # a la vez es justo lo que tkinter no lleva bien.
        self.suelta = padre is None
        self.raiz = tk.Tk() if self.suelta else tk.Toplevel(padre)
        self.raiz.title("Ideas para el proximo video")
        self.raiz.geometry("900x560")
        self.raiz.minsize(720, 440)

        self.backend = ""
        try:
            self.backend = gui.detectar_backend()
        except gui.SinBackend:
            pass

        self._construir()
        self._refrescar()
        self.tarea = self.raiz.after(150, self._vaciar_cola)
        self.raiz.protocol("WM_DELETE_WINDOW", self._cerrar)

    # ----------------------------------------------------------------

    def _construir(self) -> None:
        marco = ttk.Frame(self.raiz, padding=12)
        marco.pack(fill="both", expand=True)
        marco.columnconfigure(0, weight=1)
        marco.rowconfigure(2, weight=1)

        arriba = ttk.Frame(marco)
        arriba.grid(row=0, column=0, sticky="ew")
        arriba.columnconfigure(1, weight=1)

        ttk.Label(arriba, text="Reglas:").grid(row=0, column=0, sticky="w")
        self.reglas = ttk.Combobox(arriba, state="readonly")
        self.reglas.grid(row=0, column=1, sticky="ew", padx=(6, 6))
        ttk.Button(arriba, text="Ver / editar",
                   command=self._editar_reglas).grid(row=0, column=2)

        ttk.Label(arriba, text="Cuantas:").grid(row=0, column=3, sticky="w",
                                                padx=(10, 0))
        self.cuantas = tk.StringVar(value=str(CUANTAS_POR_DEFECTO))
        ttk.Spinbox(arriba, from_=3, to=12, width=4,
                    textvariable=self.cuantas).grid(row=0, column=4, padx=(6, 6))

        self.boton_buscar = ttk.Button(arriba, text="Buscar ideas nuevas",
                                       command=self._buscar)
        self.boton_buscar.grid(row=0, column=5)

        self.barra = ttk.Progressbar(marco, mode="indeterminate")
        self.barra.grid(row=1, column=0, sticky="ew", pady=(8, 6))

        # ---- lista ----
        caja = ttk.Frame(marco)
        caja.grid(row=2, column=0, sticky="nsew")
        caja.columnconfigure(0, weight=1)
        caja.rowconfigure(0, weight=1)

        columnas = ("dato", "estado")
        self.lista = ttk.Treeview(caja, columns=columnas, show="tree headings",
                                  selectmode="browse")
        self.lista.heading("#0", text="Titular")
        self.lista.column("#0", width=330, anchor="w")
        self.lista.heading("dato", text="El dato que lo sostiene")
        self.lista.column("dato", width=380, anchor="w")
        self.lista.heading("estado", text="Estado")
        self.lista.column("estado", width=90, anchor="center")
        self.lista.grid(row=0, column=0, sticky="nsew")

        barra_v = ttk.Scrollbar(caja, orient="vertical",
                                command=self.lista.yview)
        barra_v.grid(row=0, column=1, sticky="ns")
        self.lista.configure(yscrollcommand=barra_v.set)
        self.lista.bind("<<TreeviewSelect>>", lambda _e: self._pintar_detalle())
        self.lista.bind("<Double-1>", lambda _e: self._abrir_fuente())

        for estado, color in COLORES.items():
            self.lista.tag_configure(estado, foreground=color)

        # ---- detalle ----
        self.detalle = tk.Text(marco, height=4, wrap="word", state="disabled",
                               relief="flat", background="#f4f4f4",
                               padx=8, pady=6, font=("Segoe UI", 9))
        self.detalle.grid(row=3, column=0, sticky="ew", pady=(8, 0))

        # ---- pie ----
        pie = ttk.Frame(marco)
        pie.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        pie.columnconfigure(0, weight=1)
        self.estado = ttk.Label(pie, text="", foreground="#555")
        self.estado.grid(row=0, column=0, sticky="w")

        ttk.Button(pie, text="Descartar",
                   command=self._descartar).grid(row=0, column=1, padx=(6, 0))
        ttk.Button(pie, text="Abrir la fuente",
                   command=self._abrir_fuente).grid(row=0, column=2, padx=(6, 0))
        ttk.Button(pie, text="Hacer este video",
                   command=self._elegir).grid(row=0, column=3, padx=(6, 0))

    # ----------------------------------------------------------------

    def _refrescar(self) -> None:
        nombres = id_mod.listar_reglas() or [id_mod.asegurar_reglas()]
        self.reglas.configure(values=nombres)
        if self.reglas.get() not in nombres:
            self.reglas.set(nombres[0])

        for fila in self.lista.get_children():
            self.lista.delete(fila)

        # las propuestas primero: son las que hay que mirar. Lo hecho y lo
        # descartado se queda abajo, de memoria.
        orden = {id_mod.PROPUESTA: 0, id_mod.ELEGIDA: 1,
                 id_mod.HECHA: 2, id_mod.DESCARTADA: 3}
        self.todas = sorted(id_mod.cargar(),
                            key=lambda i: (orden.get(i.estado, 9), i.fecha))
        for idea in self.todas:
            self.lista.insert("", "end", text=idea.titular,
                              values=(idea.dato[:90], idea.estado),
                              tags=(idea.estado,))

        pendientes = sum(1 for i in self.todas if i.estado == id_mod.PROPUESTA)
        hechos = len(id_mod.temas_de_los_videos())
        self._decir(f"{pendientes} ideas sin usar. "
                    f"{hechos} videos ya hechos, que Claude no repetira.")

    def _decir(self, mensaje: str) -> None:
        self.estado.configure(text=mensaje)

    def _seleccionada(self) -> id_mod.Idea | None:
        cual = self.lista.selection()
        if not cual:
            return None
        titular = self.lista.item(cual[0], "text")
        return next((i for i in self.todas if i.titular == titular), None)

    def _pintar_detalle(self) -> None:
        idea = self._seleccionada()
        self.detalle.configure(state="normal")
        self.detalle.delete("1.0", "end")
        if idea:
            self.detalle.insert("1.0",
                                f"{idea.dato}\n\n"
                                f"Por que ahora: {idea.porque}\n"
                                f"Fuente: {idea.fuente}")
        self.detalle.configure(state="disabled")

    # ----------------------------------------------------------------

    def _editar_reglas(self) -> None:
        nombre = self.reglas.get() or id_mod.asegurar_reglas()
        texto = id_mod.cargar_reglas(nombre) or id_mod.REGLAS_FABRICA

        ventana = tk.Toplevel(self.raiz)
        ventana.title(f"Reglas de busqueda — {nombre}")
        ventana.geometry("760x560")
        caja = tk.Text(ventana, wrap="word", undo=True, padx=10, pady=8,
                       font=("Segoe UI", 10))
        caja.pack(fill="both", expand=True, padx=10, pady=(10, 0))
        caja.insert("1.0", texto)

        def guardar():
            id_mod.guardar_reglas(nombre, caja.get("1.0", "end-1c"))
            self._decir(f"Reglas '{nombre}' guardadas.")
            ventana.destroy()

        pie = ttk.Frame(ventana, padding=10)
        pie.pack(fill="x")
        ttk.Button(pie, text="Guardar", command=guardar).pack(side="right")
        ttk.Button(pie, text="Cancelar",
                   command=ventana.destroy).pack(side="right", padx=(0, 6))

    def _buscar(self) -> None:
        if self.buscando:
            return
        if not self.backend:
            messagebox.showerror(
                "Sin conexion con Claude",
                "No se ha encontrado ni el CLI de Claude ni una API key.")
            return

        try:
            cuantas = max(3, min(int(self.cuantas.get()), 12))
        except ValueError:
            cuantas = CUANTAS_POR_DEFECTO

        self.buscando = True
        self.boton_buscar.state(["disabled"])
        self.barra.start(12)
        self._decir("Claude esta buscando en internet. Tarda varios minutos.")

        reglas = id_mod.cargar_reglas(self.reglas.get())
        threading.Thread(target=self._trabajar, args=(reglas, cuantas),
                         daemon=True).start()

    def _trabajar(self, reglas: str, cuantas: int) -> None:
        """Hilo secundario: ni un widget desde aqui."""
        try:
            respuesta = gui.pedir(id_mod.prompt(reglas, cuantas),
                                  backend=self.backend,
                                  trabajo=id_mod.carpeta_reglas())
            self.cola.put(("ideas", 0, respuesta))
        except Exception as exc:
            self.cola.put(("error", 0, str(exc)))

    def _vaciar_cola(self) -> None:
        try:
            while True:
                clase, _numero, texto = self.cola.get_nowait()
                self.buscando = False
                self.barra.stop()
                self.boton_buscar.state(["!disabled"])

                if clase == "error":
                    self._decir("La busqueda ha fallado.")
                    messagebox.showerror("No ha salido", texto)
                    continue

                nuevas, charla = id_mod.extraer(texto)
                if not nuevas:
                    self._decir("Claude no ha devuelto ninguna idea legible.")
                    messagebox.showwarning("Sin ideas", charla[:600] or texto[:600])
                    continue

                _todas, cuantas = id_mod.anadir(nuevas)
                self._refrescar()
                self._decir(f"{cuantas} ideas nuevas de {len(nuevas)} "
                            f"propuestas; el resto ya estaban.")
                if charla:
                    messagebox.showinfo("Lo que dice Claude", charla[:1500])
        except queue.Empty:
            pass
        self.tarea = self.raiz.after(150, self._vaciar_cola)

    # ----------------------------------------------------------------

    def _elegir(self) -> None:
        idea = self._seleccionada()
        if idea is None:
            messagebox.showinfo("Elige una", "Selecciona una idea de la lista.")
            return
        id_mod.marcar(idea.titular, id_mod.ELEGIDA)
        self.elegida = idea
        self._cerrar()

    def _descartar(self) -> None:
        idea = self._seleccionada()
        if idea is None:
            return
        id_mod.marcar(idea.titular, id_mod.DESCARTADA)
        self._refrescar()
        self._decir(f"Descartada: {idea.titular[:50]}. No volvera a salir.")

    def _abrir_fuente(self) -> None:
        idea = self._seleccionada()
        if idea is None:
            return
        for trozo in idea.fuente.split():
            if trozo.startswith("http"):
                webbrowser.open_new_tab(trozo.rstrip(".,)"))
                return
        self._decir("Esa idea no trae enlace.")

    def _cerrar(self) -> None:
        if self.buscando and not messagebox.askyesno(
                "Buscando",
                "Claude todavia esta buscando. Si cierras se pierde.\n\n"
                "Cierro igual?"):
            return
        if self.tarea is not None:
            self.raiz.after_cancel(self.tarea)
            self.tarea = None
        self.raiz.destroy()

    def abrir(self) -> id_mod.Idea | None:
        if self.suelta:
            self.raiz.mainloop()
        else:
            self.raiz.grab_set()
            self.raiz.wait_window()
        return self.elegida


def elegir_idea(padre=None):
    """Abre la ventana y devuelve la idea elegida, o None."""
    return VentanaIdeas(padre).abrir()
