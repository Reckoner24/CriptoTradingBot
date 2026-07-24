# Original User Request

## Initial Request — 2026-07-21T23:36:27Z

# Teamwork Project Prompt — Draft

> Status: Launched
> Goal: Craft prompt → get user approval → delegate to teamwork_preview

Sistema de trading algorítmico automatizado y optimizado para alcanzar una rentabilidad del 100% semanal de forma replicable en un entorno de producción, delegando en el equipo de agentes el balance óptimo entre riesgo y recompensa.

Working directory: c:\Users\mages\OneDrive\Documentos\CriptoTradingBot
Integrity mode: development

## Requirements

### R1. Optimización Extrema de Estrategia
Optimizar la estrategia, gestión de riesgo y arquitectura del repositorio actual (`CriptoTradingBot`) para apuntar a un objetivo del 100% de rentabilidad semanal. El equipo de agentes debe encontrar y decidir el balance óptimo entre el riesgo asumido y la recompensa esperada.

### R2. Replicabilidad en Producción
El sistema optimizado debe ser completamente funcional y replicable en el entorno productivo (modo paper / live). Las ganancias observadas en backtests deben traducirse al comportamiento en producción con alta fidelidad.

## Acceptance Criteria

### Verificación de Rentabilidad y Estabilidad
- [ ] La proyección de 20 días (`python scripts/proyeccion_20d.py` u otro script de backtest equivalente) debe demostrar matemáticamente una rentabilidad proporcional a la meta (ej. mínimo 300% en 20 días) sin incurrir en liquidación (Drawdown máximo < 40%).
- [ ] La rentabilidad proyectada debe tener un Factor de Beneficio (Profit Factor) general mayor a 1.2.

### Verificación de Paridad y Regresiones
- [ ] El script de control de paridad (`python scripts/parity_check_24h.py`) debe ejecutarse correctamente, garantizando que el comportamiento de producción sea fiel a los resultados de backtest.
- [ ] La suite de pruebas unitarias (`python -m pytest tests/`) debe pasar al 100%, asegurando que las reglas del gestor de salidas y gestión de riesgo sigan intactas y estables.
