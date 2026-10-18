@echo off
cd /d "%~dp0"
if not exist tools mkdir tools
if not exist tools\cloudflared.exe (
  echo Downloading the free Cloudflare connector - one time only...
  curl -L -o tools\cloudflared.exe https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe
  if errorlevel 1 goto failed
)
echo.
echo Putting your store online so phones on ANY network can open it.
echo Keep this window AND the app window open.
echo When a line shows an address ending in  trycloudflare.com  your store is online.
echo Then open the dashboard page "Share ^& QR codes" and press Refresh.
echo.
tools\cloudflared.exe tunnel --no-autoupdate --metrics 127.0.0.1:45678 --url http://127.0.0.1:8000
pause
exit /b 0
:failed
echo Download failed. Check the internet connection and try again.
pause
exit /b 1
