@echo off
title DGT Grid Bot 24/7
echo [%time%] Iniciando DGT Grid Bot...

:loop
echo [%time%] Ejecutando DGT Grid Bot...
.entorno\Scripts\python.exe scripts\dgt_bot.py

echo.
echo [%time%] DGT Bot termino inesperadamente, reiniciando en 15 segundos...
timeout /t 15 /nobreak > nul
goto loop
