/* MiniDisc Manager - mount guard (macOS). Runs as root, started by the background service.
 *
 * Why: when macOS mounts a Hi-MD disc, Spotlight and fseventsd start reading and writing it, macOS's own USB driver keeps resetting
 * this recorder ("babble error"), unmounting hangs for minutes, and the service cannot take the recorder over. So macOS is asked not to
 * mount a Sony Hi-MD recorder's disc at all (the standard Disk Arbitration "mount approval" mechanism). The disk still exists for the
 * system; it just is not mounted, so nothing reads it until the app does. Only Sony "Hi-MD" USB disks are refused; every other disk is untouched.
 *
 *   clang -O2 -o mdm-mountguard mdm_mountguard.c -framework DiskArbitration -framework CoreFoundation
 */
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <DiskArbitration/DiskArbitration.h>
#include <CoreFoundation/CoreFoundation.h>

static int contains(CFTypeRef value, const char *needle) {
    char buf[256];
    if (!value || CFGetTypeID(value) != CFStringGetTypeID()) return 0;
    if (!CFStringGetCString((CFStringRef)value, buf, sizeof buf, kCFStringEncodingUTF8)) return 0;
    return strcasestr(buf, needle) != NULL;
}

#define OFF_FILE "/Library/Application Support/MiniDiscManager/mountguard-off"      /* present = the user switched the guard off */

static DADissenterRef approve(DADiskRef disk, void *context) {
    (void)context;
    if (access(OFF_FILE, F_OK) == 0) return NULL;
    CFDictionaryRef d = DADiskCopyDescription(disk);
    if (!d) return NULL;
    int block = contains(CFDictionaryGetValue(d, kDADiskDescriptionDeviceVendorKey), "sony")
             && contains(CFDictionaryGetValue(d, kDADiskDescriptionDeviceModelKey), "hi-md")
             && contains(CFDictionaryGetValue(d, kDADiskDescriptionDeviceProtocolKey), "usb");
    const char *name = DADiskGetBSDName(disk);
    CFRelease(d);
    if (!block) return NULL;
    printf("refused to mount the Hi-MD disc %s (the MiniDisc Manager service keeps it unmounted)\n", name ? name : "?");
    fflush(stdout);
    return DADissenterCreate(kCFAllocatorDefault, kDAReturnNotPermitted, CFSTR("MiniDisc Manager keeps this disc unmounted so the app can use it"));
}

int main(void) {
    DASessionRef session = DASessionCreate(kCFAllocatorDefault);
    if (!session) { fprintf(stderr, "could not create a Disk Arbitration session\n"); return 1; }
    DARegisterDiskMountApprovalCallback(session, NULL, approve, NULL);
    DASessionScheduleWithRunLoop(session, CFRunLoopGetCurrent(), kCFRunLoopDefaultMode);
    printf("mount guard running\n");
    fflush(stdout);
    CFRunLoopRun();
    return 0;
}
