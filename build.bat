@echo off
REM Build the Nexys A7-50T bitstream with Vivado (2018.2 or newer). Double-click or run from cmd.
REM Run this from the fpga-audio-filter folder. Vivado's bin folder must be on PATH, e.g.
REM   set PATH=C:\Xilinx\Vivado\2018.2\bin;%PATH%
cd /d "%~dp0"
set "VIV=vivado"
where vivado >nul 2>nul
if errorlevel 1 set "VIV=C:\Xilinx\Vivado\2018.2\bin\vivado.bat"
if not "%VIV%"=="vivado" if not exist "%VIV%" (
  echo Vivado not found on PATH or in C:\Xilinx\Vivado\2018.2\bin.
  echo Install Vivado 2018.2 there or add its bin folder to PATH.
  pause
  exit /b 1
)
if not exist build mkdir build
call "%VIV%" -mode batch -nojournal -log build\vivado.log -source fpga\scripts\build.tcl
py fpga\scripts\parse_reports.py
pause
