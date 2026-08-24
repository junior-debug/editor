"""
La ventana con la que se entra: elegir el video o crear uno nuevo.

Antes esto se preguntaba por consola, y no tenia sentido: el resto del
trabajo -el guion, la voz, los clips, el montaje- ya pasa entero en una
ventana. Aqui se ve de un vistazo lo que hay hecho en cada video, que por
consola habia que ir mirando carpeta por carpeta.

Se abre y se cierra antes de que exista la ventana del guion. Son dos Tk()
distintos, uno detras de otro y nunca a la vez: tkinter no lleva bien dos
raices vivas al mismo tiempo.
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from . import proyecto as proy

# Lo que se ve en la lista cuando algo esta y cuando no. Con palabras y no
# con iconos: la fuente de la consola de Windows no pinta bien los simbolos.
SI, NO = "si", "-"


class VentanaProyecto:
    def __init__(self, partes_por_defecto: int = proy.PARTES_POR_DEFECTO):
        self.base = proy.raiz()
        self.elegida: Path | None = None
        self.creada = False       # recien hecha: no hay que listarle lo que falta
        self.partes_por_defecto = partes_por_defecto

        self.raiz = tk.Tk()
        self.raiz.title("Montador — elegir video")
        self.raiz.geometry("720x480")
        self.raiz.minsize(600, 380)

        self._construir()
        self._refrescar()
        self.raiz.protocol("WM_DELETE_WINDOW", self._cancelar)

    # ----------------------------------------------------------------

    def _construir(self) -> None:
        marco = ttk.Frame(self.raiz, padding=12)
        marco.pack(fill="both", expand=True)
        marco.columnconfigure(0, weight=1)
        marco.rowconfigure(1, weight=1)

        cabecera = ttk.Frame(marco)
        cabecera.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        cabecera.columnconfigure(0, weight=1)
        ttk.Label(cabecera, text=f"MasterTube: {self.base}",
                  foreground="#555").grid(row=0, column=0, sticky="w")
        self.ver_todas = tk.BooleanVar(value=False)
        ttk.Checkbutton(cabecera, text="Ver todas las carpetas",
                        variable=self.ver_todas,
                        command=self._refrescar).grid(row=0, column=1,
                                                      padx=(0, 8))
        ttk.Button(cabecera, text="Abrir en el Explorador",
                   command=self._abrir_explorador).grid(row=0, column=2)

        # ---- lista ----
        caja = ttk.Frame(marco)
        caja.grid(row=1, column=0, sticky="nsew")
        caja.columnconfigure(0, weight=1)
        caja.rowconfigure(0, weight=1)

        columnas = ("partes", "clips", "guion", "voz")
        self.lista = ttk.Treeview(caja, columns=columnas, show="tree headings",
                                  selectmode="browse")
        self.lista.heading("#0", text="Video")
        self.lista.column("#0", width=280, anchor="w")
        for clave, titulo, ancho in (("partes", "Partes", 70),
                                     ("clips", "Clips", 70),
                                     ("guion", "Guion", 70),
                                     ("voz", "Voz", 70)):
            self.lista.heading(clave, text=titulo)
            self.lista.column(clave, width=ancho, anchor="center")
        self.lista.grid(row=0, column=0, sticky="nsew")

        barra = ttk.Scrollbar(caja, orient="vertical",
                              command=self.lista.yview)
        barra.grid(row=0, column=1, sticky="ns")
        self.lista.configure(yscrollcommand=barra.set)

        # doble clic = abrir, que es lo que espera cualquiera de una lista
        self.lista.bind("<Double-1>", lambda _e: self._abrir())
        self.lista.bind("<Return>", lambda _e: self._abrir())

        # ---- video nuevo ----
        nuevo = ttk.LabelFrame(marco, text="Video nuevo", padding=(10, 8))
        nuevo.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        nuevo.columnconfigure(1, weight=1)

        ttk.Label(nuevo, text="Nombre:").grid(row=0, column=0, sticky="w")
        self.nombre = ttk.Entry(nuevo)
        self.nombre.grid(row=0, column=1, sticky="ew", padx=(6, 10))
        self.nombre.bind("<Return>", lambda _e: self._crear())

        ttk.Label(nuevo, text="Partes:").grid(row=0, column=2, sticky="w")
        self.partes = tk.StringVar(value=str(self.partes_por_defecto))
        ttk.Spinbox(nuevo, from_=1, to=30, width=4,
                    textvariable=self.partes).grid(row=0, column=3, padx=(6, 10))

        ttk.Button(nuevo, text="Crear y empezar",
                   command=self._crear).grid(row=0, column=4)

        # ---- pie ----
        pie = ttk.Frame(marco)
        pie.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        pie.columnconfigure(0, weight=1)

        self.estado = ttk.Label(pie, text="", foreground="#555")
        self.estado.grid(row=0, column=0, sticky="w")
        ttk.Button(pie, text="Salir",
                   command=self._cancelar).grid(row=0, column=1, padx=(6, 0))
        self.boton_abrir = ttk.Button(pie, text="Abrir el elegido",
                                      command=self._abrir)
        self.boton_abrir.grid(row=0, column=2, padx=(6, 0))

    # ----------------------------------------------------------------

    def _carpetas(self) -> list[Path]:
        """
        Los videos, del ultimo tocado al primero: se sigue con el de ayer.

        Se filtran las carpetas que no son videos -en MasterTube conviven con
        'perfiles', 'reuniones', 'nicho'-, salvo que se pida verlas todas.
        """
        if not self.base.exists():
            return []
        todas = sorted((d for d in self.base.iterdir() if d.is_dir()),
                       key=lambda d: d.stat().st_mtime, reverse=True)
        if self.ver_todas.get():
            return todas
        videos = [d for d in todas if proy.es_proyecto(d)]
        # si el filtro no deja nada es que se equivoca el filtro, no el
        # usuario: mejor enseñarlo todo que una lista vacia
        return videos or todas

    def _refrescar(self) -> None:
        for fila in self.lista.get_children():
            self.lista.delete(fila)

        carpetas = self._carpetas()
        for carpeta in carpetas:
            partes = proy.partes_de(carpeta)
            clips = sum(1 for p in partes for f in p.iterdir()
                        if f.suffix.lower() in proy.EXTENSIONES_VIDEO)
            guion = (carpeta / "guion.txt").exists()
            voz = any(f.suffix.lower() in proy.EXTENSIONES_AUDIO
                      for f in carpeta.iterdir() if f.is_file())
            self.lista.insert(
                "", "end", text=carpeta.name, values=(
                    len(partes), clips or NO, SI if guion else NO,
                    SI if voz else NO))

        if carpetas:
            primero = self.lista.get_children()[0]
            self.lista.selection_set(primero)
            self.lista.focus(primero)
            self._decir(f"{len(carpetas)} videos en MasterTube. "
                        f"Elige uno o crea otro abajo.")
        else:
            self._decir("Todavia no hay ningun video. Crea el primero abajo.")

        # sin carpetas no hay nada que abrir, y un boton que no hace nada
        # solo sirve para que lo pulses
        self.boton_abrir.state(["!disabled"] if carpetas else ["disabled"])

    def _decir(self, mensaje: str) -> None:
        self.estado.configure(text=mensaje)

    # ----------------------------------------------------------------

    def _seleccionada(self) -> Path | None:
        elegida = self.lista.selection()
        if not elegida:
            return None
        return self.base / self.lista.item(elegida[0], "text")

    def _abrir(self) -> None:
        carpeta = self._seleccionada()
        if carpeta is None:
            messagebox.showinfo("Elige uno",
                                "Selecciona un video de la lista, o crea uno "
                                "nuevo abajo.")
            return
        self.elegida = carpeta
        self.raiz.destroy()

    def _crear(self) -> None:
        nombre = proy.sanear(self.nombre.get())
        if not nombre:
            messagebox.showwarning(
                "Falta el nombre",
                "Escribe como se va a llamar la carpeta del video.")
            return

        destino = proy.carpeta(nombre)
        if destino.exists():
            # no se pisa nada: se abre la que ya hay, que es lo que se queria
            self.elegida = destino
            self.raiz.destroy()
            return

        try:
            partes = max(1, min(int(self.partes.get()), 30))
        except ValueError:
            partes = self.partes_por_defecto

        self.elegida = proy.crear(nombre, partes)
        self.creada = True
        # se deja abierta en el Explorador: casi siempre lo siguiente es
        # soltar algo dentro
        proy.abrir_en_explorador(self.elegida)
        self.raiz.destroy()

    def _abrir_explorador(self) -> None:
        carpeta = self._seleccionada() or self.base
        self.base.mkdir(parents=True, exist_ok=True)
        proy.abrir_en_explorador(carpeta)

    def _cancelar(self) -> None:
        self.elegida = None
        self.raiz.destroy()

    def abrir(self) -> tuple[Path | None, bool]:
        self.raiz.mainloop()
        return self.elegida, self.creada


def elegir_carpeta(partes: int = proy.PARTES_POR_DEFECTO
                   ) -> tuple[Path | None, bool]:
    """
    La carpeta del video con la que trabajar.

    Devuelve (carpeta, recien_creada), como preguntar_carpeta(): el segundo
    valor evita listarle a nadie todo lo que le falta a una carpeta que se
    acaba de crear vacia. Carpeta a None si se cierra sin elegir.
    """
    return VentanaProyecto(partes or proy.PARTES_POR_DEFECTO).abrir()
