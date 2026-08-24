"""
Estilo de montaje.

Todos los valores salen del analisis del proyecto "0817" (noveno video):
167 cortes, 776 s, CapCut 9.2.8. Ver analisis-estilo-montaje.md.

Tocar estos numeros es la forma prevista de cambiar el resultado.
"""
from dataclasses import dataclass, field


@dataclass
class EstiloCorte:
    # media 4,65 s / mediana 4,67 s / p10-p90 3,80-5,47
    objetivo_s: float = 4.7
    minimo_s: float = 3.0
    maximo_s: float = 6.0
    # cuanto puede desplazarse un corte para caer en una pausa de la narracion
    ventana_pausa_s: float = 0.9
    # silencio minimo para considerarlo pausa aprovechable
    pausa_minima_s: float = 0.18


@dataclass
class EstiloTransicion:
    # 53 transiciones / 167 cortes = 32 %, una cada 3,1 cortes (moda 3)
    cada_n_cortes: int = 3
    jitter: int = 1          # alterna entre 2, 3 y 4 cortes
    # pesos = usos reales en el proyecto analizado
    pesos: dict = field(default_factory=lambda: {
        "7671182918861032722": 9,   # Remolino de gel rosa
        "6916426617455645186": 9,   # Desenfocar
        "7665629734243503378": 8,   # Croma de pixeles
        "7665566915024260360": 6,   # Barrido gelatinoso
        "6724845717472416269": 5,   # Combinar
        "7667469125362453767": 5,   # Mezcla y revelacion
        "7665267554369277191": 4,   # Ajuste desplazado
        "7667095812756868359": 3,   # Error de senal
        "7647004085459225857": 3,   # Circulo de fuego
        "7661956939139665173": 1,   # Impacto de fuego
    })


@dataclass
class EstiloSonido:
    # 55 efectos en 776 s -> uno cada 14,1 s (min 4,4 / max 19,6)
    cada_s: float = 14.1
    jitter_s: float = 4.0
    # HALLAZGO: 53 de 55 efectos caen en cortes SIN transicion.
    # La transicion larga ya es el acento visual; el corte seco lleva el sonido.
    solo_en_cortes_sin_transicion: bool = True
    # 25 de 55 caen en el frame exacto; el resto se anticipan hasta 0,87 s
    anticipacion_maxima_s: float = 0.87
    probabilidad_en_frame: float = 0.45
    # pesos = usos reales
    pesos: dict = field(default_factory=lambda: {
        "Click_Mouse_Click_02(864360)": 11,
        "Glitch sound that matches the sound logo(1192372)": 11,
        "pop! (tapping the mouth with a hand)(912415)": 10,
        "Fuwa: short wind noise: swipe etc": 10,
        "swish_whoosh (large)(794558)": 10,
    })


@dataclass
class EstiloRotulo:
    duracion_s: float = 3.0
    # nombre de la plantilla de CapCut por defecto para las marcas [TXT: ...]
    plantilla_por_defecto: str = "TITLE EN - WORLD NEWS"


@dataclass
class EstiloEfecto:
    """
    La capa de efecto que cubre el video entero.

    Sale del proyecto 'catorce_auto', donde junior la puso a mano: una sola
    pista de efecto, de 0 al final, sin trocear. La velocidad la bajo de 0,33
    -el valor de fabrica del efecto- a 0,3, y ese es el numero que se copia.

    'Bordes de fuego', el otro efecto de aquel proyecto, NO se reproduce: solo
    duraba tres segundos al principio y eso es una entrada concreta de ese
    video, no una regla del canal.
    """
    activo: bool = True
    nombre: str = "Ruido negro"
    effect_id: str = "7399470796290166022"
    # 'effects_adjust_speed' del efecto; None deja el que traiga el prototipo
    velocidad: float | None = 0.3


@dataclass
class Estilo:
    corte: EstiloCorte = field(default_factory=EstiloCorte)
    transicion: EstiloTransicion = field(default_factory=EstiloTransicion)
    sonido: EstiloSonido = field(default_factory=EstiloSonido)
    rotulo: EstiloRotulo = field(default_factory=EstiloRotulo)
    efecto: EstiloEfecto = field(default_factory=EstiloEfecto)

    fps: float = 30.0
    ancho: int = 1920
    alto: int = 1080

    # semilla fija -> el mismo material produce siempre el mismo montaje
    semilla: int = 20260817


ESTILO = Estilo()
