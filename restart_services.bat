@echo off
REM ============================================
REM AQI Integration - Service Restart Script
REM ============================================

echo ============================================
echo Stopping services...
echo ============================================

docker-compose stop worker
docker-compose stop backend
docker-compose stop dashboard

timeout /t 3 /nobreak > nul

echo.
echo ============================================
echo Starting services with updated code...
echo ============================================

docker-compose up -d postgres
timeout /t 5 /nobreak > nul

docker-compose up -d redis
timeout /t 3 /nobreak > nul

docker-compose up -d backend
timeout /t 5 /nobreak > nul

docker-compose up -d dashboard
timeout /t 3 /nobreak > nul

docker-compose up -d worker

echo.
echo ============================================
echo Services restarted!
echo ============================================
echo.
echo Checking status...
docker-compose ps

echo.
echo ============================================
echo Checking backend logs (last 20 lines)...
echo ============================================
docker-compose logs --tail=20 backend

echo.
echo Done! You can now run verification:
echo   venv\Scripts\python.exe verify_aqi_integration.py
echo.

pause
