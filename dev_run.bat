@echo off
cd /d "%~dp0"
echo Installing dependencies...
pip install -r requirements.txt --quiet
echo.
echo Starting wordCensor...
python app/main.py
pause
