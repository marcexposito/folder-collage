#!/bin/bash
# Folder Collage installer — double-click me.
# Adds two Finder right-click Quick Actions: "Collage it" and "Remove collage".
set -e
cd "$(dirname "$0")"

APP="$HOME/Library/Application Support/FolderCollage"
SERVICES="$HOME/Library/Services"

echo "📁 Installing Folder Collage…"
echo

# 1) Python + Pillow in a private environment (doesn't touch the rest of your system).
#    Needs Python 3.10+: current, fully patched Pillow releases no longer support Apple's built-in 3.9.
if [[ -z "$FC_SKIP_DEPS" ]]; then
  PY=""
  for c in /opt/homebrew/bin/python3 /usr/local/bin/python3 \
           /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
           "$(command -v python3 2>/dev/null)" /usr/bin/python3; do
    if [[ -n "$c" && -x "$c" ]] && "$c" -c 'import sys; assert sys.version_info >= (3, 10)' 2>/dev/null; then
      PY="$c"; break
    fi
  done
  if [[ -z "$PY" ]]; then
    echo "Folder Collage needs Python 3.10 or newer, and this Mac doesn't have it yet."
    echo
    echo "Install it from https://www.python.org/downloads/macos/ (the big yellow button),"
    echo "or with Homebrew:  brew install python"
    echo "then double-click this installer again."
    read -n 1 -s -r -p "Press any key to close."; exit 1
  fi
  mkdir -p "$APP"
  echo "• Setting up Python ($("$PY" --version))…"
  rm -rf "$APP/venv"
  "$PY" -m venv "$APP/venv"
  PIP=("$APP/venv/bin/python" -m pip install --quiet --disable-pip-version-check --only-binary=:all:)
  "${PIP[@]}" --upgrade pip
  # Minimum versions are the first releases with all known security fixes (see SECURITY.md).
  "${PIP[@]}" -r requirements.txt
  "${PIP[@]}" -r requirements-heic.txt 2>/dev/null \
    || echo "  (HEIC support skipped — JPEG/PNG photos still work)"
  "$APP/venv/bin/python" -c 'import PIL; print("  Pillow", PIL.__version__)'
fi

mkdir -p "$APP"
cp collage_folder_icon.py "$APP/"

# Small launcher the Quick Actions call
cat > "$APP/collage" <<'EOF'
#!/bin/bash
APP="$HOME/Library/Application Support/FolderCollage"
exec "$APP/venv/bin/python" "$APP/collage_folder_icon.py" --notify "$@"
EOF
chmod +x "$APP/collage"

# 2) Finder Quick Actions
make_quick_action () {   # $1 = menu title, $2 = extra launcher flags, $3 = icon PNG in assets/
  local wf="$SERVICES/$1.workflow"
  rm -rf "$wf"; mkdir -p "$wf/Contents/Resources"
  # "…Template" name = macOS tints it to match light/dark mode, like its own icons
  cp "assets/$3" "$wf/Contents/Resources/workflowCustomImageTemplate.png"
  cp "assets/$3" "$wf/Contents/Resources/workflowCustomImage.png"     # name Automator itself uses
  cat > "$wf/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleName</key><string>$1</string>
	<key>CFBundleIdentifier</key><string>io.github.foldercollage.$(echo "$1" | tr -cd '[:alnum:]' | tr '[:upper:]' '[:lower:]')</string>
	<key>NSServices</key>
	<array>
		<dict>
			<key>NSBackgroundColorName</key><string>background</string>
			<key>NSIconName</key><string>workflowCustomImageTemplate</string>
			<key>NSMenuItem</key><dict><key>default</key><string>$1</string></dict>
			<key>NSMessage</key><string>runWorkflowAsService</string>
			<key>NSRequiredContext</key><dict><key>NSApplicationIdentifier</key><string>com.apple.finder</string></dict>
			<key>NSSendFileTypes</key><array><string>public.folder</string></array>
		</dict>
	</array>
</dict>
</plist>
EOF
  local U1 U2 U3
  U1=$(uuidgen); U2=$(uuidgen); U3=$(uuidgen)
  cat > "$wf/Contents/document.wflow" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>AMApplicationBuild</key><string>523</string>
	<key>AMApplicationVersion</key><string>2.10</string>
	<key>AMDocumentVersion</key><string>2</string>
	<key>actions</key>
	<array>
		<dict>
			<key>action</key>
			<dict>
				<key>AMAccepts</key>
				<dict>
					<key>Container</key><string>List</string>
					<key>Optional</key><true/>
					<key>Types</key><array><string>com.apple.cocoa.string</string></array>
				</dict>
				<key>AMActionVersion</key><string>2.0.3</string>
				<key>AMApplication</key><array><string>Automator</string></array>
				<key>AMParameterProperties</key>
				<dict>
					<key>COMMAND_STRING</key><dict/>
					<key>CheckedForUserDefaultShell</key><dict/>
					<key>inputMethod</key><dict/>
					<key>shell</key><dict/>
					<key>source</key><dict/>
				</dict>
				<key>AMProvides</key>
				<dict>
					<key>Container</key><string>List</string>
					<key>Types</key><array><string>com.apple.cocoa.string</string></array>
				</dict>
				<key>ActionBundlePath</key><string>/System/Library/Automator/Run Shell Script.action</string>
				<key>ActionName</key><string>Run Shell Script</string>
				<key>ActionParameters</key>
				<dict>
					<key>COMMAND_STRING</key><string>"\$HOME/Library/Application Support/FolderCollage/collage" $2 "\$@"</string>
					<key>CheckedForUserDefaultShell</key><true/>
					<key>inputMethod</key><integer>1</integer>
					<key>shell</key><string>/bin/bash</string>
					<key>source</key><string></string>
				</dict>
				<key>BundleIdentifier</key><string>com.apple.RunShellScript</string>
				<key>CFBundleVersion</key><string>2.0.3</string>
				<key>CanShowSelectedItemsWhenRun</key><false/>
				<key>CanShowWhenRun</key><true/>
				<key>Category</key><array><string>AMCategoryUtilities</string></array>
				<key>Class Name</key><string>RunShellScriptAction</string>
				<key>InputUUID</key><string>$U1</string>
				<key>Keywords</key><array><string>Shell</string><string>Script</string></array>
				<key>OutputUUID</key><string>$U2</string>
				<key>UUID</key><string>$U3</string>
				<key>UnlocalizedApplications</key><array><string>Automator</string></array>
				<key>isViewVisible</key><integer>1</integer>
				<key>location</key><string>309.000000:253.000000</string>
				<key>nibPath</key><string>/System/Library/Automator/Run Shell Script.action/Contents/Resources/Base.lproj/main.nib</string>
			</dict>
			<key>isViewVisible</key><integer>1</integer>
		</dict>
	</array>
	<key>connectors</key><dict/>
	<key>workflowMetaData</key>
	<dict>
		<key>applicationBundleIDsByPath</key><dict/>
		<key>applicationPaths</key><array/>
		<key>inputTypeIdentifier</key><string>com.apple.Automator.fileSystemObject.folder</string>
		<key>outputTypeIdentifier</key><string>com.apple.Automator.nothing</string>
		<key>presentationMode</key><integer>15</integer>
		<key>processesInput</key><false/>
		<key>serviceInputTypeIdentifier</key><string>com.apple.Automator.fileSystemObject.folder</string>
		<key>serviceOutputTypeIdentifier</key><string>com.apple.Automator.nothing</string>
		<key>serviceProcessesInput</key><false/>
		<key>customImageFileExtension</key><string>png</string>
		<key>useAutomaticInputType</key><false/>
		<key>workflowTypeIdentifier</key><string>com.apple.Automator.servicesMenu</string>
	</dict>
</dict>
</plist>
EOF
  echo "• Added Quick Action: $1"
}

mkdir -p "$SERVICES"
make_quick_action "Collage it" "" collage-icon.png
make_quick_action "Remove collage" "--reset" remove-icon.png

# Make macOS re-read the Quick Actions (and their icons) instead of using cached copies
if [[ -z "$FC_SKIP_DEPS" ]]; then
  LSREG=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister
  [[ -x "$LSREG" ]] && "$LSREG" -f "$SERVICES/Collage it.workflow" "$SERVICES/Remove collage.workflow" 2>/dev/null || true
  if [[ -x /System/Library/CoreServices/pbs ]]; then
    /System/Library/CoreServices/pbs -flush 2>/dev/null || true
    /System/Library/CoreServices/pbs -update 2>/dev/null || true
  fi
  echo "• Restarting Finder so the menu picks up the changes (your windows will reopen)…"
  killall Finder 2>/dev/null || true
fi

echo
echo "✅ Done! In Finder, right-click any folder → Quick Actions → Collage it."
echo "   (It may also appear at the bottom of the menu, under Services.)"
echo
echo "   Not seeing it? Open Finder, press Shift-Cmd-G, go to ~/Library/Services,"
echo "   double-click \"Collage it.workflow\" and choose Install. See the README for more."
echo
echo "   macOS may ask to let it access a folder like Desktop or Documents the first time — that's"
echo "   needed to read your photos. It never needs Full Disk Access; don't grant that."
echo
[[ -z "$FC_SKIP_DEPS" ]] && read -n 1 -s -r -p "Press any key to close." || true
