@echo off
setlocal
set "PYTHON=C:\Users\User\AppData\Local\Programs\Python\Python311\python.exe"
if not exist "%PYTHON%" (
  echo 找不到 Python 3.11：%PYTHON%
  echo 請修改本檔中的 PYTHON 路徑，或安裝 Python 3.11。
  pause
  exit /b 1
)
"%PYTHON%" "%~dp0publish_yuanta.py"
if errorlevel 1 pause
endlocal

