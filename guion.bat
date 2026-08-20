@echo off
chcp 65001 >nul
setlocal

rem ---------------------------------------------------------------
rem  Escribe el guion con Claude y lo guarda en la carpeta del video.
rem
rem  Doble clic: pregunta en que carpeta de MasterTube va.
rem  O arrastra encima la carpeta del video.
rem
rem  Tambien se llega aqui desde montar.bat escribiendo 'guion'.
rem ---------------------------------------------------------------

cd /d "%~dp0"

set "CARPETA=%~1"

if "%CARPETA%"=="" (
  python -m montador guion
) else (
  python -m montador guion --clips "%CARPETA%"
)

echo.
if errorlevel 1 (
  echo  Ha fallado. Copia el error de arriba.
)
pause
