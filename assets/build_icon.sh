#!/usr/bin/env bash
#
# Build PollFiller.app's AppIcon.icns from the master PNG.
#   ./assets/build_icon.sh
#
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT="$(cd "$HERE/.." && pwd)"

MASTER="$HERE/icon_master.png"
[ -f "$MASTER" ] || python3 "$HERE/make_icon.py" "$MASTER"

ICONSET="$HERE/AppIcon.iconset"
rm -rf "$ICONSET"
mkdir -p "$ICONSET"

# name:size pairs required by iconutil
for spec in \
  "icon_16x16:16" "icon_16x16@2x:32" \
  "icon_32x32:32" "icon_32x32@2x:64" \
  "icon_128x128:128" "icon_128x128@2x:256" \
  "icon_256x256:256" "icon_256x256@2x:512" \
  "icon_512x512:512" "icon_512x512@2x:1024"; do
  name="${spec%%:*}"; px="${spec##*:}"
  sips -z "$px" "$px" "$MASTER" --out "$ICONSET/$name.png" >/dev/null
done

mkdir -p "$PROJECT/PollFiller.app/Contents/Resources"
iconutil -c icns "$ICONSET" -o "$PROJECT/PollFiller.app/Contents/Resources/AppIcon.icns"
rm -rf "$ICONSET"
echo "wrote PollFiller.app/Contents/Resources/AppIcon.icns"
