@echo off
rem Record a short voice clip through each filter bank and play it back on the laptop.
rem Run from the project folder:  tools\record_voice.bat   (optional: tools\record_voice.bat COM5)
setlocal
set PORT=%1
if "%PORT%"=="" set PORT=COM6
cd /d "%~dp0.."

echo.
echo Voice recordings on %PORT%. Gain 4 (SW4 up, SW5 SW3 SW2 down), SW15 down.
echo Speak at normal volume about 20 cm from the MIC; LD15 must stay off.
echo Each recording lasts 0.33 s: keep talking ("ssssaaaa..." or counting) BEFORE and WHILE you press a key.
echo.

call :one voice_b0   "bank 0, bypass:          SW1 down, SW0 down, SW8 down"
call :one voice_b1   "bank 1, low-pass 1 kHz:  SW1 down, SW0 up"
call :one voice_b2   "bank 2, high-pass 2 kHz: SW1 up,   SW0 down"
call :one voice_b3   "bank 3, telephone band:  SW1 up,   SW0 up"
call :one voice_asic "31-tap ASIC core:        SW1 down, SW0 down, SW8 up"

echo.
echo Done. Put SW8 back down. Files: results\voice_*.wav  (double-click to replay)
endlocal
exit /b 0

:one
echo ------------------------------------------------------------
echo Set %~2
echo Start talking, then press any key while you keep talking...
pause > nul
py host\af_host.py --port %PORT% capture --wav results\%1.wav --tag %1 > "%TEMP%\voice_out.txt"
if errorlevel 1 (
    echo   capture failed - check the USB cable and COM port
    exit /b 0
)
for /f "tokens=2 delims=:," %%v in ('findstr /c:"peak_dbfs" "%TEMP%\voice_out.txt"') do set PEAK=%%v
echo   recorded results\%1.wav, peak %PEAK% dBFS
py -c "import sys; sys.exit(0 if float(sys.argv[1]) < -1.0 else 1)" %PEAK%
if errorlevel 1 echo   WARNING: clipped. Lower the gain one step or speak further away, then run this again.
echo   playing it now
start "" "results\%1.wav"
timeout /t 3 > nul
exit /b 0
