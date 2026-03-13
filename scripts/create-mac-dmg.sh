#!/bin/bash

set -xe

CONFIG=${1:-release}
OUTPUT_DIR=universal

xmake clean
# Build the arm64 version
xmake f -y -p macosx -a "arm64" -m $CONFIG --target_minver=13.5
xmake b -y

# Build the x86_64 version
xmake f -y -p macosx -a "x86_64" -m $CONFIG --target_minver=13.5
xmake b -y

# Create output directory for universal binaries
rm -rf build/macosx/$OUTPUT_DIR/$CONFIG || true
mkdir -p build/macosx/$OUTPUT_DIR/$CONFIG

# Create the app bundle structure
mkdir -p build/macosx/$OUTPUT_DIR/$CONFIG/macOSLauncher.app/Contents/MacOS
mkdir -p build/macosx/$OUTPUT_DIR/$CONFIG/macOSLauncher.app/Contents/Resources

# Generate Info.plist with version substitution
VERSION="1.0.0.0"
if [ -f mods/src/version.h ]; then
    MAJOR=$(grep "^#define VERSION_MAJOR[[:space:]]" mods/src/version.h | awk '{print $3}')
    MINOR=$(grep "^#define VERSION_MINOR[[:space:]]" mods/src/version.h | awk '{print $3}')
    REVISION=$(grep "^#define VERSION_REVISION[[:space:]]" mods/src/version.h | awk '{print $3}')
    PATCH=$(grep "^#define VERSION_PATCH[[:space:]]" mods/src/version.h | awk '{print $3}')
    if [ -n "$MAJOR" ] && [ -n "$MINOR" ] && [ -n "$REVISION" ] && [ -n "$PATCH" ]; then
        VERSION="$MAJOR.$MINOR.$REVISION.$PATCH"
    fi
fi
sed "s/\${VERSION}/$VERSION/g" macos-launcher/src/Info.plist.template > build/macosx/$OUTPUT_DIR/$CONFIG/macOSLauncher.app/Contents/Info.plist

# Create universal binaries using lipo
lipo -create build/macosx/arm64/$CONFIG/macOSLauncher build/macosx/x86_64/$CONFIG/macOSLauncher -output build/macosx/$OUTPUT_DIR/$CONFIG/macOSLauncher.app/Contents/MacOS/macOSLauncher
lipo -create build/macosx/arm64/$CONFIG/stfc-community-patch-loader build/macosx/x86_64/$CONFIG/stfc-community-patch-loader -output build/macosx/$OUTPUT_DIR/$CONFIG/macOSLauncher.app/Contents/stfc-community-patch-loader
lipo -create build/macosx/arm64/$CONFIG/libstfc-community-patch.dylib build/macosx/x86_64/$CONFIG/libstfc-community-patch.dylib -output build/macosx/$OUTPUT_DIR/$CONFIG/macOSLauncher.app/Contents/libstfc-community-patch.dylib

# Copy icons and assets
cp assets/launcher.icns build/macosx/$OUTPUT_DIR/$CONFIG/macOSLauncher.app/Contents/Resources/
# Copy compiled asset catalog from one of the architecture builds (they should be identical)
if [ -f build/macosx/arm64/$CONFIG/macOSLauncher.app/Contents/Resources/Assets.car ]; then
    cp build/macosx/arm64/$CONFIG/macOSLauncher.app/Contents/Resources/Assets.car build/macosx/$OUTPUT_DIR/$CONFIG/macOSLauncher.app/Contents/Resources/
fi
# Copy PkgInfo if it exists
if [ -f build/macosx/arm64/$CONFIG/macOSLauncher.app/Contents/Resources/PkgInfo ]; then
    cp build/macosx/arm64/$CONFIG/macOSLauncher.app/Contents/Resources/PkgInfo build/macosx/$OUTPUT_DIR/$CONFIG/macOSLauncher.app/Contents/Resources/
fi

# Rename to final app name
mv build/macosx/$OUTPUT_DIR/$CONFIG/macOSLauncher.app build/macosx/$OUTPUT_DIR/$CONFIG/STFC\ Community\ Patch.app

rm -rf build/macosx/$OUTPUT_DIR/$CONFIG/*.dSYM || true
codesign --force --verify --verbose --deep --sign "-" build/macosx/$OUTPUT_DIR/$CONFIG/STFC\ Community\ Patch.app

rm stfc-community-patch-installer.dmg || true
create-dmg \
  --volname "STFC Community Patch Installer" \
  --background "assets/mac_installer_background.png" \
  --window-pos 200 120 \
  --window-size 800 400 \
  --icon-size 100 \
  --icon "STFC Community Patch.app" 200 190 \
  --hide-extension "STFC Community Patch.app" \
  --app-drop-link 600 185 \
  --filesystem APFS \
  --format ULFO \
  "stfc-community-patch-installer.dmg" \
  "build/macosx/$OUTPUT_DIR/$CONFIG/"
