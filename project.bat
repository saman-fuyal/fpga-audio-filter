@echo off
REM Create the Vivado GUI project (vivado_proj\audio_filter.xpr) and open it.
REM Uses vivado from PATH, else the default install folder C:\Xilinx\Vivado\2018.2.
cd /d "%~dp0"
set "VIV=vivado"
where vivado >nul 2>nul
if errorlevel 1 set "VIV=C:\Xilinx\Vivado\2018.2\bin\vivado.bat"
if not "%VIV%"=="vivado" if not exist "%VIV%" (
  echo Vivado not found on PATH or in C:\Xilinx\Vivado\2018.2\bin.
  echo Open Vivado 2018.2 and, in its Tcl Console, type:
  echo   cd %CD:\=/%
  echo   source fpga/scripts/create_project.tcl
  pause
  exit /b 1
)
call "%VIV%" -mode batch -nojournal -nolog -source fpga\scripts\create_project.tcl
start "" "%VIV%" vivado_proj\audio_filter.xpr
