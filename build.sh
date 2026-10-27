#!/bin/zsh
set -euo pipefail
cd "${0:A:h}"
PLUGIN_PACKAGE="$PWD/build/marketplace/plugins/cost-calculator"
mkdir -p "$PLUGIN_PACKAGE/bin" "$PWD/build/module-cache" "$PWD/build/marketplace/.agents/plugins"
ditto Plugin "$PLUGIN_PACKAGE"
cp README.md "$PLUGIN_PACKAGE/README.md"
cp INSTALL.md "$PLUGIN_PACKAGE/INSTALL.md"
cp INSTALL.md "$PWD/build/marketplace/INSTALL.md"
cp README.md "$PWD/build/marketplace/README.md"
cp .agents/plugins/marketplace.json "$PWD/build/marketplace/.agents/plugins/marketplace.json"
ZSTD_PREFIX="${COST_CALCULATOR_ZSTD_PREFIX:-/opt/homebrew/opt/zstd}"
if [[ ! -f "$ZSTD_PREFIX/lib/libzstd.a" ]]; then
  print -u2 "Missing static zstd library. Install zstd or set COST_CALCULATOR_ZSTD_PREFIX."
  exit 1
fi
xcrun clang -O2 -target arm64-apple-macosx26.0 -I "$ZSTD_PREFIX/include" -c Sources/ZstdBridge.c -o build/ZstdBridge.o
cp "$ZSTD_PREFIX/LICENSE" "$PLUGIN_PACKAGE/ZSTD-LICENSE" 2>/dev/null || cp "$ZSTD_PREFIX/share/doc/zstd/LICENSE" "$PLUGIN_PACKAGE/ZSTD-LICENSE"
xcrun swiftc -import-objc-header Sources/ZstdBridge.h build/ZstdBridge.o "$ZSTD_PREFIX/lib/libzstd.a" -parse-as-library -swift-version 5 -O -module-cache-path "$PWD/build/module-cache" -target arm64-apple-macosx26.0 Sources/*.swift -o "$PLUGIN_PACKAGE/bin/cost-calculator" -lsqlite3
codesign --force --sign - "$PLUGIN_PACKAGE/bin/cost-calculator"
mkdir -p "$PWD/plugins"
ditto "$PLUGIN_PACKAGE" "$PWD/plugins/cost-calculator"
ditto --norsrc --noextattr -c -k --keepParent "$PLUGIN_PACKAGE" "$PWD/build/cost-calculator-plugin.zip"
ditto --norsrc --noextattr -c -k --keepParent "$PWD/build/marketplace" "$PWD/build/token-usage-marketplace.zip"
(
  cd "$PWD/build"
  shasum -a 256 cost-calculator-plugin.zip token-usage-marketplace.zip > SHA256SUMS
)
printf '%s\n' "$PLUGIN_PACKAGE" "$PWD/build/cost-calculator-plugin.zip" "$PWD/build/token-usage-marketplace.zip" "$PWD/build/SHA256SUMS"
