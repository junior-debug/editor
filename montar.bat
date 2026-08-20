@echo off
chcp 65001 >nul
setlocal

rem ---------------------------------------------------------------
rem  Doble clic: pregunta el nombre de la carpeta del video y la
rem  crea dentro de MasterTube, con sus parte1...parteN.
rem
rem  O arrastra encima una carpeta ya preparada para usarla tal cual.
rem ---------------------------------------------------------------

rem opciones: MODELO=small va mucho mas rapido para una primera prueba
set "MODELO=medium"
set "DISPOSITIVO=auto"

cd /d "%~dp0"

set "CARPETA=%~1"

if not "%CARPETA%"=="" if not exist "%CARPETA%" (
  echo.
  echo  No existe la carpeta:
  echo    %CARPETA%
  echo.
  pause
  exit /b 1
)

echo.
if "%CARPETA%"=="" (
  python -m montador montar --modelo "%MODELO%" --dispositivo "%DISPOSITIVO%"
) else (
  python -m montador montar --clips "%CARPETA%" --modelo "%MODELO%" --dispositivo "%DISPOSITIVO%"
)

echo.
if errorlevel 1 (
  echo  Ha fallado. Copia el error de arriba.
) else (
  echo  Cierra CapCut y vuelve a abrirlo para ver el borrador.
)
echo.
pause
