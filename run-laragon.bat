@echo off
setlocal
cd /d "%~dp0"

set "LARAGON_PYTHON="
for /d %%D in ("C:\laragon\bin\python\python-*") do (
    if exist "%%~fD\python.exe" set "LARAGON_PYTHON=%%~fD\python.exe"
)

if not defined LARAGON_PYTHON (
    where python >nul 2>nul
    if errorlevel 1 (
        echo [ERROR] Python Laragon atau Python sistem tidak ditemukan.
        echo Tambahkan Python melalui Laragon: Menu ^> Tools ^> Quick add ^> Python.
        pause
        exit /b 1
    )
    set "LARAGON_PYTHON=python"
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Membuat virtual environment dengan Python Laragon...
    "%LARAGON_PYTHON%" -m venv .venv
    if errorlevel 1 goto :gagal
)

echo [2/3] Memastikan dependensi tersedia...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :gagal

if not defined ABSENSI_PORT set "ABSENSI_PORT=5000"

echo [3/3] Menjalankan Sistem Absensi...
echo Buka: http://127.0.0.1:%ABSENSI_PORT%
echo Tekan Ctrl+C untuk menghentikan server.
".venv\Scripts\waitress-serve.exe" --listen=127.0.0.1:%ABSENSI_PORT% --threads=4 wsgi:app
exit /b %errorlevel%

:gagal
echo.
echo [ERROR] Persiapan aplikasi gagal. Periksa koneksi internet dan pesan di atas.
pause
exit /b 1
