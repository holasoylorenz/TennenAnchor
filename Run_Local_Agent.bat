@echo off
title TennenAnchor - Local AI Agent (CUDA GPU Accelerated)
cd /d "%~dp0"
echo =====================================================================
echo   TennenAnchor Local AI Agent (Gemma 4 E4B + Quadro T1000 CUDA GPU)
echo =====================================================================
echo.
py -3 agent\local_agent.py %*
pause
