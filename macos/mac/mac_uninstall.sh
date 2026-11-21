#!/bin/sh
# Removes the MiniDisc Manager background service and its mount guard. Usage:  sudo sh mac_uninstall.sh
# Do this with the recorder UNPLUGGED: once the guard is gone macOS mounts a Hi-MD disc again, and it writes to it (Spotlight, fseventsd).
if [ "$(id -u)" != "0" ]; then echo "Run this with sudo:   sudo sh mac_uninstall.sh"; exit 1; fi
LABEL="com.minidiscmanager.usbhelper"
PLIST="/Library/LaunchDaemons/$LABEL.plist"
GUARD_PLIST="/Library/LaunchDaemons/com.minidiscmanager.mountguard.plist"
launchctl bootout system "$PLIST" 2>/dev/null
rm -f "$PLIST" /var/run/minidisc-manager.sock
launchctl bootout system "$GUARD_PLIST" 2>/dev/null
rm -f "$GUARD_PLIST"
rm -rf "/Library/Application Support/MiniDiscManager"
echo "The MiniDisc Manager background service and mount guard have been removed. (Logs in /var/log/minidisc-*.log are left; delete them if you like.)"
