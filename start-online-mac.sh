#!/bin/bash
# Puts the store online (free Cloudflare quick tunnel) so phones on any network can open it.
cd "$(dirname "$0")"
mkdir -p tools
if [ ! -x tools/cloudflared ]; then
  ARCH=$(uname -m); [ "$ARCH" = "arm64" ] && F=cloudflared-darwin-arm64.tgz || F=cloudflared-darwin-amd64.tgz
  echo "Downloading the free Cloudflare connector - one time only..."
  curl -L -o tools/cf.tgz "https://github.com/cloudflare/cloudflared/releases/latest/download/$F" && tar -xzf tools/cf.tgz -C tools && rm tools/cf.tgz && chmod +x tools/cloudflared || { echo "Download failed."; exit 1; }
fi
echo "Keep this window AND the app window open. When an address ending in trycloudflare.com appears, open the dashboard page 'Share & QR codes' and press Refresh."
tools/cloudflared tunnel --no-autoupdate --metrics 127.0.0.1:45678 --url http://127.0.0.1:8000
