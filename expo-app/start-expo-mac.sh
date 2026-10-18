#!/bin/bash
cd "$(dirname "$0")"
if ! command -v node >/dev/null; then
  echo "Node.js is not installed. Install the LTS version from https://nodejs.org and run this again."; exit 1
fi
if [ ! -f UnitNonCSD/package.json ]; then
  echo "First-time setup: creating the Expo project. This takes a few minutes..."
  npx --yes create-expo-app@latest UnitNonCSD --template blank || exit 1
  (cd UnitNonCSD && npx expo install react-native-webview expo-constants expo-linking) || exit 1
fi
cp App.js UnitNonCSD/App.js
cd UnitNonCSD
echo "Keep this window AND the main app window open, then scan the Expo Go codes on the dashboard page 'Share & QR codes'."
npx expo start --lan
