@echo off
cd /d "%~dp0"
where node >nul 2>nul
if errorlevel 1 (
  echo.
  echo Node.js is not installed.
  echo Install the "LTS" version from https://nodejs.org and then double-click this file again.
  echo.
  pause
  exit /b 1
)
if not exist UnitNonCSD\package.json (
  echo First-time setup: creating the Expo project. This takes a few minutes...
  call npx --yes create-expo-app@latest UnitNonCSD --template blank
  if errorlevel 1 goto failed
  cd UnitNonCSD
  call npx expo install react-native-webview expo-constants expo-linking
  if errorlevel 1 goto failed
  cd ..
)
copy /Y App.js UnitNonCSD\App.js >nul
cd UnitNonCSD
echo.
echo Keep this window AND the main app window open.
echo Then scan the "Expo Go" QR codes on the dashboard page "Share ^& QR codes".
echo.
call npx expo start --lan
pause
exit /b 0
:failed
echo.
echo Setup did not finish. Check your internet connection and run this file again.
pause
exit /b 1