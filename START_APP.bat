@echo off
title Smart Student Attendance & Energy Management System
color 0B

echo ==============================================================================
echo       SMART STUDENT ATTENDANCE & CLASSROOM ENERGY MANAGEMENT SYSTEM
echo ==============================================================================
echo.
echo  [1] Starting Local Web Server (Python Flask)...
echo  [2] Barcode Attendance + Real-Time Camera Scanner
echo  [3] Classroom Energy Management (3 Zones: 3 Fans + 2 Lights per zone)
echo.
echo  Server Address: http://127.0.0.1:5000
echo  Default Login : Username: admin  ^|  Password: admin123
echo.
echo ==============================================================================

:: Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not found in your system PATH!
    echo Please install Python 3.10+ from https://www.python.org or the Microsoft Store.
    echo.
    pause
    exit /b 1
)

:: Automatically launch browser after server starts
start "" cmd /c "timeout /t 2 /nobreak >nul && start http://127.0.0.1:5000"

echo Launching web application in your default browser...
echo Press CTRL+C in this window at any time to stop the server.
echo.

:: Launch the Flask application
python app.py

if errorlevel 1 (
    echo.
    echo [SERVER STOPPED OR FAILED TO START]
    pause
)
