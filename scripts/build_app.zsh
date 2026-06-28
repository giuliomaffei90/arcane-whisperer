#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.13}"
APP_NAME="Arcane Manager"
APP_ICON_PNG="assets/ArcaneManager.png"
APP_ICON_ICNS="assets/ArcaneManager.icns"

if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="$(command -v python3)"
fi

if [ ! -x ".venv/bin/python" ]; then
  "$PYTHON_BIN" -m venv .venv
fi

if [ -f requirements.lock.txt ]; then
  .venv/bin/python -m pip install -r requirements.lock.txt
else
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt pyinstaller
fi

if [ -f "$APP_ICON_PNG" ]; then
  ICONSET_DIR="$(mktemp -d)/ArcaneManager.iconset"
  mkdir -p "$ICONSET_DIR"
  sips -s format png -z 16 16 "$APP_ICON_PNG" --out "$ICONSET_DIR/icon_16x16.png" >/dev/null
  sips -s format png -z 32 32 "$APP_ICON_PNG" --out "$ICONSET_DIR/icon_16x16@2x.png" >/dev/null
  sips -s format png -z 32 32 "$APP_ICON_PNG" --out "$ICONSET_DIR/icon_32x32.png" >/dev/null
  sips -s format png -z 64 64 "$APP_ICON_PNG" --out "$ICONSET_DIR/icon_32x32@2x.png" >/dev/null
  sips -s format png -z 128 128 "$APP_ICON_PNG" --out "$ICONSET_DIR/icon_128x128.png" >/dev/null
  sips -s format png -z 256 256 "$APP_ICON_PNG" --out "$ICONSET_DIR/icon_128x128@2x.png" >/dev/null
  sips -s format png -z 256 256 "$APP_ICON_PNG" --out "$ICONSET_DIR/icon_256x256.png" >/dev/null
  sips -s format png -z 512 512 "$APP_ICON_PNG" --out "$ICONSET_DIR/icon_256x256@2x.png" >/dev/null
  sips -s format png -z 512 512 "$APP_ICON_PNG" --out "$ICONSET_DIR/icon_512x512.png" >/dev/null
  sips -s format png -z 1024 1024 "$APP_ICON_PNG" --out "$ICONSET_DIR/icon_512x512@2x.png" >/dev/null
  iconutil -c icns "$ICONSET_DIR" -o "$APP_ICON_ICNS"
  rm -rf "${ICONSET_DIR:h}"
fi

rm -rf build dist "$APP_NAME.app" "$APP_NAME.spec" "$APP_NAME.zip" "$APP_NAME"*.dmg(N) pyinstaller_build.log

.venv/bin/pyinstaller \
  --noconfirm \
  --windowed \
  --name "$APP_NAME" \
  --osx-bundle-identifier "local.arcanemanager.overlay" \
  --icon "$APP_ICON_ICNS" \
  --add-data=spells.json:resources \
  --add-data=bestiary_srd.json:resources \
  --add-data=items.json:resources \
  --add-data=assets/icons:resources/assets/icons \
  --add-data=assets/dice_roller:resources/assets/dice_roller \
  --add-data=assets/three-dice:resources/assets/three-dice \
  --collect-all pyobjc_core \
  --collect-all pyobjc_framework_Cocoa \
  --collect-all WebKit \
  --collect-all JavaScriptCore \
  --hidden-import objc \
  --hidden-import Cocoa \
  --hidden-import WebKit \
  --hidden-import JavaScriptCore \
  --paths src \
  main.py > pyinstaller_build.log 2>&1

PLIST="dist/$APP_NAME.app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Delete :LSUIElement" "$PLIST" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Set :CFBundleDisplayName $APP_NAME" "$PLIST"
/usr/libexec/PlistBuddy -c "Set :CFBundleName $APP_NAME" "$PLIST"
/usr/libexec/PlistBuddy -c "Set :NSHighResolutionCapable true" "$PLIST" 2>/dev/null || \
  /usr/libexec/PlistBuddy -c "Add :NSHighResolutionCapable bool true" "$PLIST"

codesign --force --deep --sign - "dist/$APP_NAME.app"
cp -R "dist/$APP_NAME.app" .
cp "$APP_ICON_ICNS" "$APP_NAME.app/Contents/Resources/ArcaneManager.icns"
touch "$APP_NAME.app"
codesign --force --deep --sign - "$APP_NAME.app"

rm -rf build dist "$APP_NAME.spec" pyinstaller_build.log

du -sh "$APP_NAME.app"
