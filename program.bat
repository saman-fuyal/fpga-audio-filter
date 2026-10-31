@echo off
REM Program the board over USB (volatile). Use "program.bat flash" to write the QSPI flash.
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
if "%1"=="flash" (
  call "%VIV%" -mode batch -nojournal -nolog -source fpga\scripts\program.tcl -tclargs flash
) else (
  call "%VIV%" -mode batch -nojournal -nolog -source fpga\scripts\program.tcl
)
pause
