@echo off
chcp 65001 >nul
cd /d %~dp0

rem 优先用带 tkinter 的 Python（本机 3.10）；找不到再退回系统 pythonw
set "PYW=C:\Users\Administrator\AppData\Local\Programs\Python\Python310\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw.exe"

start "" "%PYW%" "%~dp0desktop.py"
