@echo off
REM ============================================================
REM  *** DEPRECADO ***
REM  Este script es un mecanismo de arranque LEGADO.
REM  El arranque oficial es con PM2:
REM      pm2 start ecosystem.config.js
REM      pm2 save
REM
REM  El bot tiene ahora lock de instancia unica por socket:
REM  un doble arranque (PM2 + este .bat) simplemente FALLARA,
REM  y el bucle de abajo reintentaria para siempre.
REM  Mantenido solo como referencia historica.
REM ============================================================
echo [AVISO] run_bot_247.bat esta DEPRECADO. Usa PM2: pm2 start ecosystem.config.js
echo [AVISO] Si el bot ya corre bajo PM2, este arranque fallara por el lock de instancia unica.
pause

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
