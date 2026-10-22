#!/bin/sh
# Build Pianpian.app: a double-clickable window around this checkout (proof of concept, this Mac only).
#
#   tools/make_app.sh              # -> dist/Pianpian.app, copied to ~/Applications
#
# The .app does not contain the code: it runs launcher.py from this folder, with a small Python
# environment (pywebview) in ~/Library/Application Support/Pianpian/venv. So edits to the code
# show up the next time you open it, and the pipeline uses the uv/ffmpeg/yt-dlp already installed.
set -eu
REPO=$(cd "$(dirname "$0")/.." && pwd)
APP="$REPO/dist/Pianpian.app"
VENV="$HOME/Library/Application Support/Pianpian/venv"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

echo "1/4 icon"
swiftc -O "$REPO/tools/svg2png.swift" -o "$TMP/svg2png"
mkdir -p "$TMP/AppIcon.iconset"
for s in 16 32 128 256 512; do
  "$TMP/svg2png" "$REPO/design/icons/20-pianpian-watermelon.svg" "$TMP/AppIcon.iconset/icon_${s}x${s}.png" "$s"
  "$TMP/svg2png" "$REPO/design/icons/20-pianpian-watermelon.svg" "$TMP/AppIcon.iconset/icon_${s}x${s}@2x.png" $((s * 2))
done
iconutil -c icns "$TMP/AppIcon.iconset" -o "$TMP/AppIcon.icns"

echo "2/4 python environment (pywebview)"
export UV_DEFAULT_INDEX="${UV_DEFAULT_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"   # PyPI is slow from China
[ -x "$VENV/bin/python" ] || uv venv -q --python 3.12 "$VENV"
uv pip install -q --python "$VENV/bin/python" "pywebview>=6.2"

echo "3/4 bundle"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$TMP/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"
cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Pianpian</string>
  <key>CFBundleDisplayName</key><string>Pianpian</string>
  <key>CFBundleIdentifier</key><string>app.pianpian.poc</string>
  <key>CFBundleExecutable</key><string>pianpian</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.0.1</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
EOF
cat > "$APP/Contents/MacOS/pianpian" <<EOF
#!/bin/sh
# Apps opened from Finder get a bare PATH: add Homebrew's, where uv, ffmpeg and yt-dlp live.
export PATH="/opt/homebrew/bin:/usr/local/bin:\$HOME/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
mkdir -p "\$HOME/Library/Logs/Pianpian"
exec "$VENV/bin/python" "$REPO/launcher.py" >> "\$HOME/Library/Logs/Pianpian/launcher.log" 2>&1
EOF
chmod +x "$APP/Contents/MacOS/pianpian"

echo "4/4 install to ~/Applications"
mkdir -p "$HOME/Applications"
rm -rf "$HOME/Applications/Pianpian.app"
cp -R "$APP" "$HOME/Applications/Pianpian.app"
echo "done: ~/Applications/Pianpian.app (drag it to the Dock to keep it there)"
