@echo off
chcp 65001 >nul
setlocal

rem ---------------------------------------------------------------
rem  Arrastra la carpeta del video (la que contiene parte1, parte2,
rem  ...) y sueltala encima de este .bat.
rem
rem  O ejecutalo con doble clic: usara CARPETA_POR_DEFECTO.
rem ---------------------------------------------------------------

set "CARPETA_POR_DEFECTO=C:\Users\junio\Desktop\MasterTube\noveno video"

rem opciones: MODELO=small va mucho mas rapido para una primera prueba
set "MODELO=medium"
set "DISPOSITIVO=auto"

cd /d "%~dp0"

set "CARPETA=%~1"
if "%CARPETA%"=="" set "CARPETA=%CARPETA_POR_DEFECTO%"

if not exist "%CARPETA%" (
  echo.
  echo  No existe la carpeta:
  echo    %CARPETA%
  echo.
  echo  Arrastra la carpeta del video encima de este .bat, o edita
  echo  CARPETA_POR_DEFECTO en la primera linea del archivo.
  echo.
  pause
  exit /b 1
)

rem nombre del proyecto = nombre de la carpeta + _auto, sin espacios
for %%I in ("%CARPETA%") do set "NOMBRE=%%~nxI"
set "NOMBRE=%NOMBRE: =_%"
set "PROYECTO=%NOMBRE%_auto"

echo.
echo  Carpeta  : %CARPETA%
echo  Proyecto : %PROYECTO%
echo  Modelo   : %MODELO%  (dispositivo: %DISPOSITIVO%)
echo.

python -m montador montar --clips "%CARPETA%" --proyecto "%PROYECTO%" --modelo "%MODELO%" --dispositivo "%DISPOSITIVO%" --guardar-edl "%CARPETA%\edl.json"

echo.
if errorlevel 1 (
  echo  Ha fallado. Copia el error de arriba.
) else (
  echo  Cierra CapCut y vuelve a abrirlo para ver el borrador.
)
echo.
pause
