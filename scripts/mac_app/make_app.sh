#!/bin/zsh
# Builds ~/Applications/DEIXIS.app, a double-click launcher for the local server (see launch.zsh).
set -euo pipefail
HERE="${0:A:h}"
REPO="${HERE:h:h}"
APP="$HOME/Applications/DEIXIS.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>DEIXIS</string>
  <key>CFBundleIdentifier</key><string>local.deixis.launcher</string>
  <key>CFBundleExecutable</key><string>launch</string>
  <key>CFBundleIconFile</key><string>deixis</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSUIElement</key><true/>
</dict></plist>
PLIST

sed "s|__REPO__|$REPO|" "$HERE/launch.zsh" > "$APP/Contents/MacOS/launch"
chmod +x "$APP/Contents/MacOS/launch"

# Icon from the UI's SVG (Quick Look renders it to PNG).
TMP=$(mktemp -d)
qlmanage -t -s 1024 -o "$TMP" "$REPO/apps/web/dist/deixis-icon.svg" >/dev/null 2>&1 || true
PNG=$(ls "$TMP"/*.png 2>/dev/null | head -1 || true)
if [[ -n "$PNG" ]]; then
  SET="$TMP/deixis.iconset"; mkdir "$SET"
  for s in 16 32 128 256 512; do
    sips -z $s $s "$PNG" --out "$SET/icon_${s}x${s}.png" >/dev/null
    sips -z $((s*2)) $((s*2)) "$PNG" --out "$SET/icon_${s}x${s}@2x.png" >/dev/null
  done
  iconutil -c icns "$SET" -o "$APP/Contents/Resources/deixis.icns"
fi
rm -rf "$TMP"
touch "$APP"
echo "Built $APP"
