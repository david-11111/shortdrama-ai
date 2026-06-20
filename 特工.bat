@echo off
setlocal
title ShortDrama Agent Run

cd /d "%~dp0"

echo [Agent] Checking Docker Desktop...
docker info >nul 2>nul
if errorlevel 1 (
  echo [Agent] Docker is not ready. Starting Docker Desktop...
  docker desktop start >nul 2>nul
  if errorlevel 1 (
    echo.
    echo [Agent] Could not start Docker Desktop automatically.
    echo [Agent] Open Docker Desktop manually, wait until it is running, then run this script again.
    pause
    exit /b 1
  )

  echo [Agent] Waiting for Docker daemon...
  for /L %%i in (1,1,60) do (
    docker info >nul 2>nul
    if not errorlevel 1 goto :docker_ready
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Sleep -Seconds 2" >nul
  )

  echo.
  echo [Agent] Docker Desktop started, but the Docker daemon is still not ready.
  echo [Agent] Open Docker Desktop and check for startup errors, then run this script again.
  pause
  exit /b 1
)

:docker_ready
echo [Agent] Starting local SaaS services...
docker compose up -d postgres redis api worker-video worker-image worker-text worker-admin beat nginx
if errorlevel 1 (
  echo.
  echo [Agent] Startup failed. Make sure Docker Desktop is running.
  pause
  exit /b 1
)

echo [Agent] Waiting for API health check...
set "READY="
for /L %%i in (1,1,40) do (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-RestMethod -Uri 'http://localhost/health' -TimeoutSec 3; if ($r.status -eq 'ok') { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>nul
  if not errorlevel 1 (
    set "READY=1"
    goto :open_agent
  )
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Sleep -Seconds 2" >nul
)

echo.
echo [Agent] API is not healthy yet. The page will open anyway; refresh after Docker finishes starting.

:open_agent
echo [Agent] Opening Agent Run page...
start "" "http://localhost/director/agent-run"

echo.
echo [Agent] Opened: http://localhost/director/agent-run
echo [Agent] You can close this window. Docker services will keep running in the background.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Sleep -Seconds 5" >nul
exit /b 0
