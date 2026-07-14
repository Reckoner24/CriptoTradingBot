@echo off
title Bot de Trading Cripto - Gestor 24/7
echo Iniciando Gestor del Bot de Trading...

:loop
echo [%time%] Ejecutando bot...
.entorno\Scripts\python.exe scripts\bot_live_bidirectional.py

echo.
echo [%time%] El proceso del bot termino inesperadamente (crasheo).
echo [%time%] Reiniciando en 15 segundos...
timeout /t 15 /nobreak > nul
goto loop
