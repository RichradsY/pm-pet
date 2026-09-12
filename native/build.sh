#!/bin/bash
set -euo pipefail

native_dir="$(cd "$(dirname "$0")" && pwd)"
app_dir="${1:-$native_dir/../build/PM Pet.app}"
module_cache="$native_dir/../.build/module-cache"
mkdir -p "$app_dir/Contents/MacOS" "$app_dir/Contents/Resources"
mkdir -p "$module_cache"
export CLANG_MODULE_CACHE_PATH="$module_cache"
export SWIFT_MODULECACHE_PATH="$module_cache"

xcrun swiftc -swift-version 5 -O -target "$(uname -m)-apple-macosx13.0" \
  -module-cache-path "$module_cache" \
  -framework AppKit -framework WebKit \
  "$native_dir/main.swift" -o "$app_dir/Contents/MacOS/PMPet"
cp "$native_dir/Resources/pet.html" "$app_dir/Contents/Resources/pet.html"
cp "$native_dir/Info.plist" "$app_dir/Contents/Info.plist"
/usr/bin/codesign --force --sign - "$app_dir" >/dev/null
echo "$app_dir"
