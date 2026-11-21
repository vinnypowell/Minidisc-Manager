#!/bin/sh
# Installs the MiniDisc Manager background service on this Mac (needed once; run again to update). Usage:  sudo sh mac_install.sh
# The service runs as root so the app itself never needs sudo. It is copied to a folder only root can change.
set -e
if [ "$(id -u)" != "0" ]; then echo "Run this with sudo:   sudo sh mac_install.sh"; exit 1; fi
HERE="$(cd "$(dirname "$0")" && pwd)"
DEST="/Library/Application Support/MiniDiscManager"
LABEL="com.minidiscmanager.usbhelper"
PLIST="/Library/LaunchDaemons/$LABEL.plist"
USER_UID="${SUDO_UID:-$(stat -f %u /dev/console)}"
USER_GID="${SUDO_GID:-$(stat -f %g /dev/console)}"
# the runtime (node, ffmpeg, the libraries) sits next to this script, or, in the packaged app, in the app's Resources folder
RT="$HERE/runtime"; [ -d "$RT" ] || RT="$HERE/../Resources/runtime"
for f in "helper/mac_daemon.js" "helper/himd_helper.js"; do
  [ -e "$HERE/$f" ] || { echo "Missing $f next to this script."; exit 1; }
done
for f in node node_modules; do
  [ -e "$RT/$f" ] || { echo "Missing runtime/$f."; exit 1; }
done

launchctl bootout system "$PLIST" 2>/dev/null || true
rm -f /var/run/minidisc-manager.sock
# keep the user's mount-guard choice across updates
KEEP_OFF=0; [ -e "$DEST/mountguard-off" ] && KEEP_OFF=1
KEEP_WRITES=0; [ -e "$DEST/writes-always" ] && KEEP_WRITES=1      # "keep disc changes on" is the user's explicit choice: an update does not undo it
# the guard is its own service and must keep running while this one is updated: remember the old guard program to see whether it changed
GUARD_LABEL="com.minidiscmanager.mountguard"
GUARD_PLIST="/Library/LaunchDaemons/$GUARD_LABEL.plist"
OLD_GUARD="$(mktemp)"; cp "$DEST/bin/mdm-mountguard" "$OLD_GUARD" 2>/dev/null || : > "$OLD_GUARD"
rm -rf "$DEST"
mkdir -p "$DEST/bin"
# -L: the packaged app stores its files as links into its Resources folder; the service needs the real files
cp -RL "$HERE/helper" "$RT" "$DEST/"
[ -f "$HERE/service-version.txt" ] && cp "$HERE/service-version.txt" "$DEST/service-version.txt"      # the app compares this stamp to decide whether the service needs updating
chmod +x "$DEST/runtime/node"
[ "$KEEP_OFF" = "1" ] && echo off > "$DEST/mountguard-off"
[ "$KEEP_WRITES" = "1" ] && echo on > "$DEST/writes-always"

# The mount guard: a small program that asks macOS not to mount the recorder's disc (needs the Xcode command line tools to build)
if [ -f "$HERE/bin/mdm-mountguard" ]; then            # the packaged app brings the guard ready-built (people need not have the developer tools)
  cp "$HERE/bin/mdm-mountguard" "$DEST/bin/mdm-mountguard"
  chmod 755 "$DEST/bin/mdm-mountguard"
  echo "Installed the mount guard."
elif [ -f "$HERE/native/mdm_mountguard.c" ]; then
  if clang -O2 -o "$DEST/bin/mdm-mountguard" "$HERE/native/mdm_mountguard.c" -framework DiskArbitration -framework CoreFoundation; then
    echo "Built the mount guard."
  else
    echo "WARNING: the mount guard could not be built (are the developer tools installed? run: xcode-select --install). The service still works, but macOS may keep mounting the disc."
  fi
fi

xattr -dr com.apple.quarantine "$DEST" 2>/dev/null || true
chown -R root:wheel "$DEST"
# files copied from another computer can arrive readable by their owner only: let every user read and run them, and nobody but root change them
chmod -R u+rwX,go+rX,go-w "$DEST"
chmod 755 "$DEST/runtime/node"
for t in ffmpeg whisper-cli; do if [ -f "$DEST/runtime/$t" ]; then chmod 755 "$DEST/runtime/$t"; fi; done
[ -f "$DEST/runtime/atracdenc3p/atracdenc" ] && chmod 755 "$DEST/runtime/atracdenc3p/atracdenc"

# The mount guard runs as its own background service (in the user's login session, like the main service), so it is still running whenever the
# main service restarts or stops. It is only reloaded when its program changed or it is not loaded.
if [ -x "$DEST/bin/mdm-mountguard" ]; then
  cat > "$GUARD_PLIST" <<GUARDEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$GUARD_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/launchctl</string>
    <string>asuser</string>
    <string>$USER_UID</string>
    <string>$DEST/bin/mdm-mountguard</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>5</integer>
  <key>StandardOutPath</key><string>/var/log/minidisc-mountguard.log</string>
  <key>StandardErrorPath</key><string>/var/log/minidisc-mountguard.log</string>
</dict>
</plist>
GUARDEOF
  chown root:wheel "$GUARD_PLIST"
  chmod 644 "$GUARD_PLIST"
  if launchctl print "system/$GUARD_LABEL" > /dev/null 2>&1 && cmp -s "$OLD_GUARD" "$DEST/bin/mdm-mountguard"; then
    echo "The mount guard is already running and unchanged: left alone."
  else
    launchctl bootout system "$GUARD_PLIST" 2>/dev/null || true
    launchctl bootstrap system "$GUARD_PLIST"
    echo "The mount guard service was (re)loaded."
  fi
fi
rm -f "$OLD_GUARD"

cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/launchctl</string>
    <string>asuser</string>
    <string>$USER_UID</string>
    <string>$DEST/runtime/node</string>
    <string>$DEST/helper/mac_daemon.js</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>HIMD_RUNTIME</key><string>$DEST/runtime</string>
    <key>MDM_UID</key><string>$USER_UID</string>
    <key>MDM_GID</key><string>$USER_GID</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>/var/log/minidisc-manager.log</string>
  <key>StandardErrorPath</key><string>/var/log/minidisc-manager.log</string>
</dict>
</plist>
PLISTEOF
chown root:wheel "$PLIST"
chmod 644 "$PLIST"
plutil -lint "$PLIST"
# The service runs as root but INSIDE the user's login session (launchctl asuser): started in the plain system context, macOS refuses
# to hand out the recorder's USB interface (IOCreatePlugInInterfaceForService: out of resources). It starts once that user is logged in.
launchctl bootstrap system "$PLIST"
i=0; while [ ! -S /var/run/minidisc-manager.sock ] && [ $i -lt 20 ]; do sleep 1; i=$((i + 1)); done   # the service needs a few seconds to start
sleep 1

echo
echo "Checking the service (as user $USER_UID):"
if sudo -u "#$USER_UID" "$DEST/runtime/node" "$DEST/helper/mac_client.js" status; then
  echo "The MiniDisc Manager background service is installed and running."
  echo "Remove it any time with:  sudo sh mac_uninstall.sh      Log: /var/log/minidisc-manager.log"
else
  echo "The service did not answer. Look at the log:  tail -30 /var/log/minidisc-manager.log"
fi
