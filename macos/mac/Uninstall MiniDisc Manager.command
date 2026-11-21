#!/bin/sh
# Removes MiniDisc Manager from this Mac: the background service, the mount guard and the app. Double-click it (Terminal opens and asks for your password).
clear
echo "Remove MiniDisc Manager"
echo "-----------------------"
echo
echo "Please UNPLUG the MiniDisc recorder first (macOS mounts a Hi-MD disc again as soon as the service is gone)."
echo "Press Return to continue, or close this window to cancel."
read -r _
echo
echo "Removing the background service (macOS asks for your password)..."
sudo /bin/sh -c '
launchctl bootout system /Library/LaunchDaemons/com.minidiscmanager.usbhelper.plist 2>/dev/null
rm -f /Library/LaunchDaemons/com.minidiscmanager.usbhelper.plist /var/run/minidisc-manager.sock
launchctl bootout system /Library/LaunchDaemons/com.minidiscmanager.mountguard.plist 2>/dev/null
rm -f /Library/LaunchDaemons/com.minidiscmanager.mountguard.plist
rm -rf "/Library/Application Support/MiniDiscManager" "/Library/Caches/MiniDiscManager"
rm -f /var/log/minidisc-manager.log /var/log/minidisc-mountguard.log
'
echo "The background service was removed."
if [ -d "/Applications/MiniDisc Manager.app" ]; then
  rm -rf "/Applications/MiniDisc Manager.app" && echo "The app was removed from Applications."
fi
DATA="$HOME/Library/Application Support/MiniDiscManager"
if [ -d "$DATA" ]; then
  echo
  echo "MiniDisc Manager's own settings and saved recordings are in:"
  echo "  $DATA"
  printf "Delete them as well? (y/N) "
  read -r ans
  case "$ans" in
    y|Y|yes|YES) rm -rf "$DATA" && echo "Deleted." ;;
    *) echo "Kept." ;;
  esac
fi
echo
echo "All done. You can close this window."
