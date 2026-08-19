"""
Comprueba que el parche esta donde debe y que whisper puede arrancar.

    python diagnostico.py
"""
import sys
from pathlib import Path

print("Python :", sys.version.split()[0])
print("Cwd    :", Path.cwd())
print()

try:
    import montador.alineacion as a
except ImportError as e:
    print("NO se puede importar montador.alineacion:", e)
    print("-> Estas ejecutando esto desde la carpeta montador-capcut?")
    sys.exit(1)

print("alineacion.py cargado desde:")
print("   ", a.__file__)
parcheado = hasattr(a, "_cargar_modelo") and hasattr(a, "_registrar_dlls_cuda")
print("parche aplicado:", "SI" if parcheado else "NO  <-- el problema es este")
if not parcheado:
    print()
    print("Copia alineacion.py y cli.py DENTRO de la carpeta 'montador\\',")
    print("junto a config.py y edl.py. No en la raiz del proyecto.")
    sys.exit(1)

print()
print("Carpetas de DLL de NVIDIA registradas:")
d = a._registrar_dlls_cuda()
if d:
    for x in d:
        print("   ", x)
else:
    print("    ninguna (no hay paquetes nvidia-* instalados)")

print()
for dev, cmp_ in (("cuda", "float16"), ("cpu", "int8")):
    try:
        a._cargar_modelo("tiny", dev, cmp_)
        print(f"{dev:5s} OK")
    except Exception as e:                    # noqa: BLE001
        print(f"{dev:5s} FALLA -> {type(e).__name__}: {e}")
