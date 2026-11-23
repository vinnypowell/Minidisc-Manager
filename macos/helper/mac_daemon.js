'use strict';
// MiniDisc Manager - macOS background service. Runs as root (launchd), so the app itself never needs sudo.
//
// Why it exists: macOS's own disk driver owns the recorder's USB interface. To talk to the recorder the driver must be detached (root only),
// the disc must be unmounted first, and the recorder must STAY detached while the app works: closing the USB session (or resetting it)
// gives the recorder back to macOS. So one long-lived process holds the recorder open and runs the helper's commands inside itself.
//
//   - the first request: unmounts the recorder's disc, detaches the macOS driver, claims the recorder
//   - later requests:    reuse the open recorder (no unmounting, no re-enumeration)
//   - idle for IDLE_MS, a "release" request, or a failed command: the recorder is handed back to macOS, which mounts the disc again
//
// Clients talk to it over a Unix socket (owned by the user who installed it, mode 600) with one JSON object per line:
//   -> {"t":"run","cmd":"list","args":{}}     <- {"event":...} lines, then {"result":...} or {"error":...}   (same lines himd_helper.js prints)
//   -> {"t":"stop"}                             asks the running command to stop (what "stop" on stdin does for himd_helper.js)
// Service commands: ping, status, release.
// Only the commands in ALLOWED run here, and only read-only ones for now: this process is root, so each command is added on purpose.
const net = require('net');
const fs = require('fs');
const path = require('path');
const cp = require('child_process');
const { PassThrough } = require('stream');

const RT = process.env.HIMD_RUNTIME || path.join(__dirname, '..', 'runtime');
const SOCK = process.env.MDM_SOCKET || '/var/run/minidisc-manager.sock';
const IDLE_MS = Number(process.env.MDM_IDLE_MS) || 600000;        // how long an unused recorder stays held; releasing it makes macOS re-enumerate it, which is best avoided
const REST_MS = Number(process.env.MDM_REST_MS) || 4000;          // the recorder is left alone this long after the end of a write before the next request touches it
let lastWriteDone = 0;
const SETTLE_MS =Number(process.env.MDM_SETTLE_MS) || 45000;      // after the recorder (re)appears on USB, macOS's driver is still starting the disc: taking the recorder over then leaves it stuck until replugged
let lastAttach = Date.now();                                       // when a recorder last appeared (the service start counts: it may have been plugged in just before)
// The helper commands that run here. list, dump, plan and inspect only read the disc ("dump" writes a file, but only into the staging folder below,
// never a path from the client); upload and delete CHANGE the disc and need the writes switch (see "writes" below). Every argument is checked first.
// The "root file" commands each store (or remove) one small file in the disc's root folder: the track list (TRACKS.CSV), the lyrics (LYRICS.TXT), the disc
// picture (COVER.JPG), the group pictures and the disc label. They all share one routine in the helper that backs up the start of the volume first and
// checks the whole volume afterwards (nothing else changed, the file reads back the same).
const ROOT_FILE_SET = ['tracklist_set', 'lyrics_set', 'cover_set', 'groupart_set', 'label_set', 'jcard_set'];          // take a file
const ROOT_FILE_REMOVE = ['cover_remove', 'groupart_remove', 'label_remove', 'jcard_remove'];                              // take nothing
// "format" erases the whole Hi-MD disc and sets up a fresh volume. It takes no arguments (the app makes the user type FORMAT first), and like every
// change it only runs while the writes switch is on.
// "backup" only reads the disc (it saves the index files into a staged folder, copied to the caller afterwards). "upload_frames" writes ATRAC audio that
// was saved before in its raw form (Clone, Split and the like); the file must be readable by the user's account.
// "spatial_put" / "spatial_remove" store or remove one spatial-audio file (SPnnnnnn.HMS or SPATIAL.JSN) in the root folder; the name is checked here too.
const ALLOWED = new Set(['list', 'dump', 'plan', 'inspect', 'upload', 'upload_frames', 'delete', 'format', 'backup', 'spatial_put', 'spatial_remove', 'spatial_get', ...ROOT_FILE_SET, ...ROOT_FILE_REMOVE]);
const WRITE_COMMANDS = new Set(['upload', 'upload_frames', 'delete', 'format', 'spatial_put', 'spatial_remove', ...ROOT_FILE_SET, ...ROOT_FILE_REMOVE]);
const SPATIAL_NAME = /^(SP[0-9A-Z]{1,6}\.HMS|SPATIAL\.JSN)$/i;
const STAGE = process.env.MDM_STAGE || '/Library/Caches/MiniDiscManager';
const DISKUTIL = '/usr/sbin/diskutil';

const log = (...a) => console.log(new Date().toISOString(), ...a);
const sleepSync = ms => Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);

if (process.platform !== 'darwin') { console.error('mac_daemon.js is for macOS only.'); process.exit(1); }

// ---- where "dump" writes ----------------------------------------------------------------------------------------------------------------
// This process is root, so it never writes to a path the client names (a user could point it at a system file, or swap a folder for a link).
// Output goes to a folder only root can change: STAGE/<uid>/, readable by the user's group. The client (mac_client.js) is told the staged path
// in a {"event":"staged"} line and links the path the app asked for to it, so the app reads its file as usual. Old staged files are removed.
function prepareDump(args) {
    const a = args || {};
    if (!Number.isInteger(a.index) || a.index < 0 || a.index > 2000) throw new Error('Bad track number.');
    const startByte = a.startByte === undefined ? 0 : a.startByte;
    if (!Number.isInteger(startByte) || startByte < 0) throw new Error('Bad start position.');
    const uid = Number(process.env.MDM_UID) || 0, gid = Number(process.env.MDM_GID) || 20;
    const dir = path.join(STAGE, String(uid));
    fs.mkdirSync(STAGE, { recursive: true, mode: 0o755 });         // the parent can be entered by anyone; only this user's folder below is readable, and only by the user's group
    fs.chownSync(STAGE, 0, 0);
    fs.chmodSync(STAGE, 0o755);
    fs.mkdirSync(dir, { recursive: true, mode: 0o750 });
    fs.chownSync(dir, 0, gid);
    fs.chmodSync(dir, 0o750);
    const old = fs.readdirSync(dir).map(n => ({ n, t: fs.statSync(path.join(dir, n)).mtimeMs })).sort((x, y) => y.t - x.t).slice(5);   // keep the 5 newest
    for (const f of old) { try { fs.unlinkSync(path.join(dir, f.n)); } catch (e) { /* in use or gone */ } }
    const staged = path.join(dir, 'track-' + Date.now() + '-' + a.index + '.part');
    fs.writeFileSync(staged, '', { mode: 0o640, flag: 'wx' });        // created here with the right owner and mode; the helper only writes into it
    fs.chownSync(staged, 0, gid);
    fs.chmodSync(staged, 0o640);
    return { staged, args: { index: a.index, out: staged, exact: !!a.exact, raw: !!a.raw, startByte } };
}

// ---- arguments of the commands that read the user's files or change the disc ----------------------------------------------------------------
const UID = Number(process.env.MDM_UID) || 0;
const GID = Number(process.env.MDM_GID) || 20;

// This process is root: a file path from the client is only used if it is a plain file owned by the user who installed the service.
function userFile(p) {
    if (typeof p !== 'string' || !path.isAbsolute(p)) throw new Error('A file path is not valid.');
    let real;
    try { real = fs.realpathSync(p); } catch (e) { throw new Error('File not found: ' + p); }
    const st = fs.statSync(real);
    if (!st.isFile()) throw new Error('Not a file: ' + p);
    // The service may only read what the user could read themselves: ask the system, as that user (sudo sets up the user's groups properly).
    // The owner is not what counts: files on an external drive, a network share or another account are fine as long as the user can read them.
    if (UID) {
        const r = cp.spawnSync('/usr/bin/sudo', ['-n', '-u', '#' + UID, '/bin/test', '-r', real], { timeout: 10000 });
        if (r.status !== 0) throw new Error('The service can only read files that your own account can read: ' + p);
    }
    return real;
}
function userFiles(list) {
    if (!Array.isArray(list) || list.length < 1 || list.length > 300) throw new Error('A list of 1 to 300 files is needed.');
    return list.map(f => {
        if (typeof f === 'string') return userFile(f);
        if (f && typeof f === 'object' && typeof f.path === 'string') {                    // the app sends { path, title, artist, album }: keep only those, check the path
            const o = { path: userFile(f.path) };
            for (const k of ['title', 'artist', 'album']) if (typeof f[k] === 'string') o[k] = f[k].slice(0, 500);
            return o;
        }
        throw new Error('A file path is not valid.');
    });
}

// A folder only root can change, readable by the user's group, for what a command writes (index backups): the client copies it afterwards.
function stageSub(prefix) {
    const base = path.join(STAGE, String(UID));
    fs.mkdirSync(STAGE, { recursive: true, mode: 0o755 }); fs.chownSync(STAGE, 0, 0); fs.chmodSync(STAGE, 0o755);
    fs.mkdirSync(base, { recursive: true, mode: 0o750 }); fs.chownSync(base, 0, GID); fs.chmodSync(base, 0o750);
    const dir = path.join(base, prefix + '-' + Date.now());
    fs.mkdirSync(dir, { recursive: true, mode: 0o750 });
    return dir;
}
function finishStage(dir) {          // everything the command wrote becomes readable by the user's group (the helper runs with a private umask)
    if (!dir) return;
    const walk = d => {
        for (const n of fs.readdirSync(d)) {
            const f = path.join(d, n), st = fs.lstatSync(f);
            fs.chownSync(f, 0, GID);
            if (st.isDirectory()) { fs.chmodSync(f, 0o750); walk(f); } else fs.chmodSync(f, 0o640);
        }
    };
    try { fs.chownSync(dir, 0, GID); fs.chmodSync(dir, 0o750); walk(dir); } catch (e) { log('finishing the staged folder: ' + e.message); }
}

// Checks and cleans the arguments of the helper commands that take files or change the disc. Returns { args, stage }.
function prepareArgs(cmd, a) {
    if (WRITE_COMMANDS.has(cmd) && !a.simulate && !writesOn()) throw new Error(WRITES_OFF_TEXT);
    switch (cmd) {
        case 'plan': case 'inspect':
            if (cmd === 'plan' && Array.isArray(a.files) && a.files.length === 0) return { args: { files: [] }, stage: null };      // "no files": only asks how much room the disc has (the split / combine checks)
            return { args: { files: userFiles(a.files) }, stage: null };
        case 'upload': {
            const format = String(a.format === undefined ? 'auto' : a.format);
            if (!/^[a-z0-9_]{2,12}$/.test(format)) throw new Error('Unknown format.');
            const mp3Kbps = a.mp3Kbps === undefined ? 192 : a.mp3Kbps;
            if (!Number.isInteger(mp3Kbps)) throw new Error('Unknown MP3 bit rate.');
            return { args: { files: userFiles(a.files), simulate: !!a.simulate, format, mp3Kbps }, stage: null };
        }
        case 'delete': {
            if (!Array.isArray(a.indexes) || !a.indexes.length || a.indexes.length > 2000 || !a.indexes.every(Number.isInteger)) throw new Error('A list of track numbers is needed.');
            const stage = stageSub('backup');
            return { args: { indexes: a.indexes, simulate: !!a.simulate, allowSecure: !!a.allowSecure, backupDir: stage }, stage };
        }
        case 'format':                                  // nothing the client sends is passed on
            return { args: {}, stage: null };
        case 'spatial_put': case 'spatial_remove': {
            if (typeof a.name !== 'string' || !SPATIAL_NAME.test(a.name)) throw new Error('That is not a spatial audio file name.');
            const stage = stageSub('backup');
            const args = { name: a.name, simulate: !!a.simulate, backupDir: stage };
            if (cmd === 'spatial_put') args.file = userFile(a.file);
            return { args, stage };
        }
        case 'backup': {                                // the index files go to a staged folder, which the client copies to args.backupDir (or args.dir)
            const stage = stageSub('backup');
            return { args: { dir: stage }, stage };
        }
        case 'upload_frames': {
            if (!Array.isArray(a.files) || !a.files.length || a.files.length > 2000) throw new Error('A list of audio files is needed.');
            const files = a.files.map(f => {
                if (!f || typeof f !== 'object' || typeof f.frames !== 'string') throw new Error('A file path is not valid.');
                if (![0, 1].includes(f.codecId) || !/^[0-9a-fA-F]{10}$/.test(String(f.codecInfo))) throw new Error('Unknown codec details.');
                if (f.skip !== undefined && !(Number.isInteger(f.skip) && f.skip >= 0 && f.skip < 4096)) throw new Error('Bad header length.');
                const o = { frames: userFile(f.frames), codecId: f.codecId, codecInfo: String(f.codecInfo), skip: f.skip === undefined ? 0 : f.skip };
                for (const k of ['title', 'artist', 'album']) if (typeof f[k] === 'string') o[k] = f[k].slice(0, 500);
                return o;
            });
            return { args: { files, simulate: !!a.simulate }, stage: null };
        }
        default:
            if (ROOT_FILE_SET.includes(cmd)) {          // { file: what the app just made, simulate }: the file must be one the user can read; the backup goes to a staged folder
                const stage = stageSub('backup');
                return { args: { file: userFile(a.file), simulate: !!a.simulate, backupDir: stage }, stage };
            }
            if (ROOT_FILE_REMOVE.includes(cmd)) {
                const stage = stageSub('backup');
                return { args: { simulate: !!a.simulate, backupDir: stage }, stage };
            }
            return { args: a, stage: null };
    }
}

// ---- the recorder's disc: find and unmount it ---------------------------------------------------------------------------------------
// Only external USB disks whose name says Sony / Hi-MD are ever touched.
function recorderDisks() {
    const found = [];
    const t0 = Date.now();
    // Only a disk that is MOUNTED (FAT, under /Volumes) can be in the way, so look at those; asking diskutil about every disk takes seconds.
    let mounts = '';
    try { mounts = cp.execFileSync('/sbin/mount', { encoding: 'utf8', timeout: 10000 }); } catch (e) { log('mount failed: ' + e.message); return found; }
    const ids = [...new Set([...mounts.matchAll(/^\/dev\/(disk\d+)(?:s\d+)* on \/Volumes\/.*\((?:msdos|exfat)/gm)].map(x => x[1]))];
    for (const m of ids.map(id => [null, id])) {
        let info = '';
        try { info = cp.execFileSync(DISKUTIL, ['info', '/dev/' + m[1]], { encoding: 'utf8', timeout: 30000 }); } catch (e) { continue; }
        const name = (info.match(/Device \/ Media Name:\s*(.*)/) || [])[1] || '';
        const proto = (info.match(/Protocol:\s*(.*)/) || [])[1] || '';
        if (/usb/i.test(proto) && /sony|hi-?md/i.test(name)) found.push(m[1]);
    }
    log('looked for the recorder disk: ' + (found.join(', ') || 'none') + ' (' + (Date.now() - t0) + ' ms)');
    return found;
}

function unmountRecorder() {
    let mounts = '';
    try { mounts = cp.execFileSync('/sbin/mount', { encoding: 'utf8', timeout: 10000 }); } catch (e) { /* treated as: nothing mounted */ }
    for (const id of recorderDisks()) {
        if (!new RegExp('^/dev/' + id + '(s\\d+)?\\s', 'm').test(mounts)) { log(id + ' is not mounted (nothing to unmount)'); continue; }     // the usual case once the mount guard runs
        for (let attempt = 1; attempt <= 2; attempt++) {
            const t0 = Date.now();
            try {
                cp.execFileSync(DISKUTIL, ['unmountDisk', 'force', '/dev/' + id], { encoding: 'utf8', stdio: 'pipe', timeout: 20000 });
                log('unmounted ' + id + ' (' + (Date.now() - t0) + ' ms)');
                sleepSync(3000);                 // macOS is still taking the disk apart for a moment; claiming the recorder at once fails
                break;
            } catch (e) {
                log('unmount of ' + id + ' failed after ' + (Date.now() - t0) + ' ms (attempt ' + attempt + '): ' + String(e.stderr || e.message).trim());
                sleepSync(2000);                 // fseventsd / Spotlight let go after a moment
            }
        }
    }
}

// ---- the mount guard: macOS is asked never to mount the recorder's disc ------------------------------------------------------------------
// A separate small program (bin/mdm-mountguard, built by mac_install.sh) that refuses the mount through Disk Arbitration. Without it the disc
// is mounted, Spotlight reads it, unmounting hangs and the recorder cannot be taken over. It can be switched off (the disc then mounts again
// as usual): the "guard" request with {"enabled": false}; the choice is kept in the file mountguard-off next to runtime/.
const GUARD_BIN = path.join(RT, '..', 'bin', 'mdm-mountguard');
const GUARD_OFF = path.join(RT, '..', 'mountguard-off');
// The guard is NOT a child of this service: it is its own background service (com.minidiscmanager.mountguard, set up by mac_install.sh), so it
// keeps refusing the mount while this service restarts, updates or stops. (When it was a child, a restart handed the recorder back to macOS
// with the guard already gone: macOS mounted the disc read-write, wrote to it, and the next takeover found it damaged.)
function guardState() {
    if (!fs.existsSync(GUARD_BIN)) return 'missing';
    if (fs.existsSync(GUARD_OFF)) return 'off';
    try { cp.execFileSync('/usr/bin/pgrep', ['-x', 'mdm-mountguard'], { stdio: 'ignore' }); return 'running'; } catch (e) { return 'stopped'; }
}
const startGuard = () => { };       // nothing to start here any more
const stopGuard = () => { };        // the guard reads mountguard-off itself

// ---- keep the recorder open between requests ------------------------------------------------------------------------------------------
const usbDir = path.join(RT, 'node_modules', 'usb', 'dist');
const { WebUSB } = require(path.join(usbDir, 'webusb', 'index.js'));
const { WebUSBDevice } = require(path.join(usbDir, 'webusb', 'webusb-device.js'));
const { Interface } = require(path.join(usbDir, 'usb', 'interface.js'));

const detached = [];                            // interfaces whose macOS driver we took away
const origClaim = Interface.prototype.claim;
Interface.prototype.claim = function () {
    let lastError = null;
    for (let attempt = 1; attempt <= 8; attempt++) {
        try {
            if (this.isKernelDriverActive()) { this.detachKernelDriver(); if (!detached.includes(this)) detached.push(this); log('detached the macOS driver'); sleepSync(500); }
        } catch (e) { log('could not detach the macOS driver: ' + e.message); }
        try {
            const r = origClaim.call(this);
            if (attempt > 1) log('claimed the recorder on attempt ' + attempt);
            return r;
        } catch (e) {
            lastError = e;
            log('claim attempt ' + attempt + ' failed: ' + e.message);
            sleepSync(1000);
        }
    }
    throw lastError;
};

// Right after the recorder is claimed (before any command), put its bulk-only transport in a known state: macOS's own driver may have been
// halfway through a command when it was taken away, and a recorder that is out of step stalls every read.
const origClaimInterface = WebUSBDevice.prototype.claimInterface;
WebUSBDevice.prototype.claimInterface = async function (n) {
    const was = this.configuration && this.configuration.interfaces.find(i => i.interfaceNumber === n);
    const already = !!(was && was.claimed);
    const r = await origClaimInterface.call(this, n);
    // (A bulk-only mass storage reset, request 0xFF, is NOT sent here: this recorder does not answer it, and the USB library then waits on it for hours.)
    if (!already) log('recorder claimed (interface ' + n + ')');
    return r;
};

// node-mass-storage re-reads a stalled status forever; give up after a few stalls so the session can be restarted instead of spinning.
const { USBMassStorageDriver } = require(path.join(RT, 'node_modules', 'node-mass-storage', 'dist', 'usb-mass-storage.js'));
const origBulkIn = USBMassStorageDriver.prototype.bulkTrasferIn;
USBMassStorageDriver.prototype.bulkTrasferIn = async function (length) {
    const r = await origBulkIn.call(this, length);
    if (r && r.status === 'stall') {
        this.__stalls = (this.__stalls || 0) + 1;
        if (this.__stalls > 6) { this.__stalls = 0; throw new Error('The recorder keeps stalling (its USB transport is out of step). Unplug it and plug it back in.'); }
    } else {
        this.__stalls = 0;
    }
    return r;
};

const origRelease = WebUSBDevice.prototype.releaseInterface;
const origClose = WebUSBDevice.prototype.close;
// himd-js ends every command with reset + releaseInterface + close; here those would hand the recorder back to macOS, so they do nothing.
WebUSBDevice.prototype.reset = async function () { };
WebUSBDevice.prototype.releaseInterface = async function () { };
WebUSBDevice.prototype.close = async function () { };

// A standard disc read with the firmware patch asks for the audio in ONE bulk read of over a megabyte. macOS's USB layer never completes a request that big
// (Windows's does), so the read hangs after the header. Reads of a standard disc larger than 64 KB are therefore made in 64 KB pieces and put together again.
const origTransferIn = WebUSBDevice.prototype.transferIn;
const BULK_PIECE = 65536;
WebUSBDevice.prototype.transferIn = async function (ep, length) {
    if (wantMode !== 'netmd' || !(length > BULK_PIECE)) return origTransferIn.call(this, ep, length);
    const parts = [];
    let got = 0;
    while (got < length) {
        const want = Math.min(BULK_PIECE, length - got);
        const r = await origTransferIn.call(this, ep, want);
        if (r.status !== 'ok') return r;
        const b = Buffer.from(r.data.buffer, r.data.byteOffset, r.data.byteLength);
        parts.push(b); got += b.length;
        if (b.length < want) break;                                   // a short piece ends the transfer, as it does for one big read
    }
    const all = Buffer.concat(parts);
    return { status: 'ok', data: new DataView(all.buffer, all.byteOffset, all.byteLength) };
};

let held = null;                                // the open recorder (a WebUSBDevice), reused by every request
let heldMode = 'himd';                          // 'himd' (a Hi-MD disc, USB disk) or 'netmd' (a standard disc, NetMD): the recorder re-appears under another USB ID when the disc type changes
let wantMode = 'himd';                          // what the request being run needs
let mscSynced = false;                          // true once the bulk-only transport has been reset since the recorder was taken over
let heldSince = 0;
const origRequest = WebUSB.prototype.requestDevice;
WebUSB.prototype.requestDevice = async function (options) {
    if (held && heldMode === wantMode) return held;
    if (held) { log('the recorder is now in another mode (' + heldMode + ' -> ' + wantMode + '): the old connection is dropped'); held = null; mscSynced = false; detached.splice(0); }
    if (wantMode === 'netmd') { held = await origRequest.call(this, options); heldMode = 'netmd'; heldSince = Date.now(); return held; }      // a standard disc has no disk for macOS to mount: nothing to unmount, nothing to wait for
    const wait = lastAttach + SETTLE_MS - Date.now();
    if (wait > 0) { log('the recorder appeared ' + Math.round((SETTLE_MS - wait) / 1000) + ' s ago: waiting ' + Math.round(wait / 1000) + ' s for macOS to finish with it before taking it over'); await new Promise(r => setTimeout(r, wait)); }
    unmountRecorder();
    held = await origRequest.call(this, options);
    heldMode = 'himd';
    heldSince = Date.now();
    return held;
};

let idleTimer = null;
async function teardown(why) {
    clearTimeout(idleTimer);
    const d = held;
    held = null;
    mscSynced = false;
    if (!d) return;
    log('giving the recorder back to macOS (' + why + ')');
    try { await origRelease.call(d, 0); } catch (e) { log('release: ' + e.message); }
    for (const i of detached.splice(0)) { try { i.attachKernelDriver(); } catch (e) { log('could not reattach the macOS driver: ' + e.message + ' (unplug and replug the recorder)'); } }
    try { await origClose.call(d); } catch (e) { /* closed anyway */ }
    lastAttach = Date.now();                     // giving the recorder back makes macOS re-enumerate it
}

// Note when a recorder appears on the bus (hotplug), for the settle wait above.
try {
    const { usb: usbCore } = require(path.join(RT, 'node_modules', 'usb'));
    usbCore.on('attach', d => {
        try { if (d.deviceDescriptor.idVendor === 0x054c) { lastAttach = Date.now(); log('a Sony USB device appeared (0x' + d.deviceDescriptor.idProduct.toString(16) + ')'); } } catch (e) { /* ignore */ }
    });
    usbCore.on('detach', d => {                  // unplugged (or re-enumerated by the recorder itself): the open connection is dead, so the next request must open a fresh one
        try { if (d.deviceDescriptor.idVendor === 0x054c && held) { log('a Sony USB device went away (0x' + d.deviceDescriptor.idProduct.toString(16) + '): dropping the open connection'); held = null; mscSynced = false; detached.splice(0); } } catch (e) { /* ignore */ }
    });
} catch (e) { log('could not watch for recorders appearing: ' + e.message); }

// ---- raw SCSI for the Python side of the app ---------------------------------------------------------------------------------------------
// The app's Python code reads the disc itself (himd_dev.Device) with plain SCSI commands over USB bulk-only transport. On macOS it cannot open the
// recorder, so on macOS its Device class sends each command here: {"cmd":"scsi","args":{"cdb":"<hex>","length":n,"timeout":ms,"out":"<base64>"}}
// -> {"result":{"data":"<base64>","status":n}}. Only READ commands pass for now (a raw channel to a root process must not be able to write
// to the disc): writes need the file "writes-enabled" next to runtime/, which is not created by anything yet.
// Writing is OFF unless a client switched it on with {"cmd":"writes","args":{"enabled":true,"minutes":20}}; it switches itself off again when the time
// is up, and always when this service starts. Even with writes on, only WRITE(10) and "set time" pass through the raw channel: nothing else
// (no format, no vendor commands). The helper's own write commands (upload, delete) are gated by the same switch below.
let writesUntil = 0;
// "Keep on" (for testing): a file next to runtime/, so it survives a restart and an update. Only the user's explicit choice creates it; switching changes off removes it.
const WRITES_ALWAYS = path.join(RT, '..', 'writes-always');
const writesAlways = () => fs.existsSync(WRITES_ALWAYS);
// DECISION (user, 2026-11-20): changes to the disc are simply allowed; the "Disc changes" button is gone from the app. Only the file `writes-never` next to runtime/ (made by hand,
// for anyone who wants the old read-only behaviour back) switches changes off. The checks on WHAT may be written (only the commands listed above, with checked arguments) stay.
const WRITES_NEVER = path.join(RT, '..', 'writes-never');
const writesOn = () => !fs.existsSync(WRITES_NEVER) && (true || Date.now() < writesUntil || writesAlways());
const WRITES_OFF_TEXT = 'Changes to the disc are switched off. Click "Disc changes" at the top of the window to allow them for a while.';
function scsiAllowed(cdb) {
    const op = cdb[0];
    if (op === 0x00 || op === 0x03 || op === 0x12 || op === 0x23 || op === 0x25 || op === 0x28) return true;   // TEST UNIT READY, REQUEST SENSE, INQUIRY, READ FORMAT CAPACITIES, READ CAPACITY, READ(10)
    if (op === 0xC2 && cdb[3] === 0x50) return true;                                                          // the recorder's "get time"
    if (!writesOn()) return false;
    return op === 0x2A || (op === 0xC2 && cdb[3] === 0x90);                                                   // WRITE(10), and the recorder's "set time"
}
let mscTag = 0;
async function mscDevice() {
    const himdjs = require(path.join(RT, 'node_modules', 'himd-js'));
    const ids = himdjs.DevicesIds.filter(d => d.vendorId === 0x054c).map(d => ({ vendorId: d.vendorId, productId: d.deviceId }));
    const webusb = new WebUSB({ allowedDevices: ids, deviceTimeout: 10000000 });
    const device = await webusb.requestDevice({ filters: ids });          // the cached, already claimed recorder when one is held
    await device.open();
    if (!device.configuration) await device.selectConfiguration(1);
    await device.claimInterface(0);
    let epIn = 0, epOut = 0;
    for (const e of device.configuration.interfaces[0].alternate.endpoints) {
        if (e.type !== 'bulk') continue;
        if (e.direction === 'in') epIn = e.endpointNumber; else epOut = e.endpointNumber;
    }
    if (!epIn || !epOut) throw new Error('The recorder has no bulk endpoints.');
    return { device, epIn, epOut };
}
const withTimeout = (p, ms, what) => Promise.race([p, new Promise((_, rej) => setTimeout(() => rej(new Error('The recorder stopped responding (' + what + ').')), ms))]);
async function mscIn(m, length) {
    for (let k = 0; k < 2; k++) {
        const r = await m.device.transferIn(m.epIn, length);
        if (r.status === 'stall') { await m.device.clearHalt('in', m.epIn); if (length === 13) continue; }
        return r.data ? Buffer.from(r.data.buffer, r.data.byteOffset, r.data.byteLength) : Buffer.alloc(0);
    }
    return Buffer.alloc(0);
}
async function scsiCommand(a) {
    const cdb = Buffer.from(String(a.cdb || ''), 'hex');
    if (cdb.length < 1 || cdb.length > 16) throw new Error('Bad SCSI command.');
    if (!scsiAllowed(cdb)) {
        const isWrite = cdb[0] === 0x2A || (cdb[0] === 0xC2 && cdb[3] === 0x90);
        throw new Error(isWrite && !writesOn() ? WRITES_OFF_TEXT : 'This SCSI command (0x' + cdb[0].toString(16) + ') is not allowed through the background service.');
    }
    const out = a.out ? Buffer.from(String(a.out), 'base64') : null;
    const length = out ? out.length : Math.max(0, Math.min(Number(a.length) || 0, 4 * 1024 * 1024));
    const timeout = Math.max(1000, Math.min(Number(a.timeout) || 5000, 120000));
    const m = await mscDevice();
    return withTimeout((async () => {
        const cbw = Buffer.alloc(31);
        cbw.write('USBC', 0, 'ascii');
        cbw.writeUInt32LE(++mscTag, 4);
        cbw.writeUInt32LE(length, 8);
        cbw[12] = out ? 0 : 0x80;
        cbw[13] = 0;
        cbw[14] = cdb.length;
        cdb.copy(cbw, 15);
        await m.device.transferOut(m.epOut, cbw);
        let data = Buffer.alloc(0);
        if (out) await m.device.transferOut(m.epOut, out);
        else if (length) data = await mscIn(m, length);
        const csw = await mscIn(m, 13);
        if (csw.length !== 13) throw new Error('The recorder sent a bad status.');
        return { data: data.toString('base64'), status: csw[12] };
    })(), timeout, 'SCSI 0x' + cdb[0].toString(16));
}
async function scsiReset() {
    const m = await mscDevice();       // recovery: clear both endpoints (the recorder does not answer the bulk-only reset request itself)
    const limit = (p, ms) => Promise.race([p, new Promise((_, rej) => setTimeout(() => rej(new Error('timed out')), ms))]);
    try { await limit(m.device.clearHalt('in', m.epIn), 3000); await limit(m.device.clearHalt('out', m.epOut), 3000); } catch (e) { log('clear halt: ' + e.message); }
    return { reset: true };
}

// ---- running requests -----------------------------------------------------------------------------------------------------------------
const helper = require('./himd_helper.js');       // not run as a program: only exports the commands
const netmdHelper = require('./netmd_helper.js'); // the same for standard discs (NetMD)
// Standard MiniDisc commands (a request with "h":"netmd"). Only these run, with checked arguments; nothing that writes a path chosen by the client
// (no track download, no copies, no firmware patch) and no switch to Hi-MD mode. Changes need the writes switch like every other change.
const NETMD_ALLOWED = new Set(['list', 'plan', 'upload', 'delete', 'move', 'format', 'rename', 'halt', 'remote', 'fetch_stream', 'fetch', 'exploit_probe']);      // remote: the recorder plays the disc itself (writes nothing)
const NETMD_WRITES = new Set(['upload', 'delete', 'move', 'format', 'rename']);
function prepareNetmdArgs(cmd, a) {
    if (NETMD_WRITES.has(cmd) && !writesOn()) throw new Error(WRITES_OFF_TEXT);
    const idx = (v, what) => { if (!Number.isInteger(v) || v < 0 || v > 2000) throw new Error('Bad ' + what + '.'); return v; };
    switch (cmd) {
        case 'list': case 'halt': case 'exploit_probe': return {};
        case 'fetch': {             // saves one track decoded to a WAV in the staging folder (never a path chosen by the client; no "raw" copies yet)
            const p = prepareDump({ index: idx(a.index, 'track number') });
            return { index: a.index, out: p.staged, exploit: !!a.exploit, raw: false, __staged: p.staged };
        }
        case 'fetch_stream': {      // reads one track off the disc with the recorder's temporary firmware patch (as on Windows) into a file in the staging folder
            const seconds = Number(a.seconds);
            if (!Number.isFinite(seconds) || seconds < 1 || seconds > 100000) throw new Error('Bad length.');
            const o = { index: idx(a.index, 'track number'), seconds };
            if (a.spinWait !== undefined && a.spinWait !== null) { if (!Number.isFinite(Number(a.spinWait)) || Number(a.spinWait) < 0 || Number(a.spinWait) > 60000) throw new Error('Bad wait.'); o.spinWait = Number(a.spinWait); }
            const p = prepareDump({ index: o.index });
            o.out = p.staged; o.__staged = p.staged;
            return o;
        }
        case 'plan': return { files: Array.isArray(a.files) && a.files.length === 0 ? [] : userFiles(a.files) };
        case 'upload': {
            const format = String(a.format === undefined ? 'sp' : a.format);
            if (!['sp', 'lp2', 'lp4'].includes(format)) throw new Error('Unknown format: ' + format);
            return { files: userFiles(a.files), format, copyDir: null };
        }
        case 'delete':
            if (!Array.isArray(a.indexes) || a.indexes.length < 1 || a.indexes.length > 300) throw new Error('A list of tracks is needed.');
            return { indexes: a.indexes.map(v => idx(v, 'track number')) };
        case 'move': return { from: idx(a.from, 'track number'), to: idx(a.to, 'track number') };
        case 'remote': {
            if (!['play', 'pause', 'resume', 'stop', 'seek', 'next', 'previous', 'status'].includes(a.action)) throw new Error('Unknown remote action.');
            const sec = a.seconds === undefined ? 0 : Number(a.seconds);
            if (!Number.isFinite(sec) || sec < 0 || sec > 100000) throw new Error('Bad time.');
            return { action: a.action, index: a.index === undefined ? 0 : idx(a.index, 'track number'), seconds: sec };
        }
        case 'format':
            if (a.mode !== 'standard' && a.mode !== 'himd') throw new Error('Unknown format.');
            return { mode: a.mode };
        case 'rename': {
            if (typeof a.title !== 'string' || a.title.length > 300) throw new Error('Bad title.');
            return a.disc ? { disc: true, title: a.title } : { index: idx(a.index, 'track number'), title: a.title };
        }
    }
    throw new Error('Not allowed.');
}
async function runNetmd(sock, msg, out) {
    const cmd = String(msg.cmd || '');
    if (!NETMD_ALLOWED.has(cmd)) { await out({ error: 'The background service does not run "' + cmd + '" for standard discs.' }); return; }
    let args;
    try { args = prepareNetmdArgs(cmd, msg.args && typeof msg.args === 'object' ? msg.args : {}); } catch (e) { await out({ error: String(e.message || e) }); return; }
    if (NETMD_WRITES.has(cmd)) log('WRITE netmd ' + cmd + ' ' + JSON.stringify(args.indexes || (args.files || []).map(f => path.basename(String(typeof f === 'string' ? f : f.path))) || args).slice(0, 200));
    const ctl = new PassThrough();
    current = { sock, ctl, cmd: 'netmd ' + cmd };
    if (args.__staged) { await out({ event: 'staged', path: args.__staged }); delete args.__staged; }
    netmdHelper.setSay(out);
    netmdHelper.setCtl(ctl);
    let failed = false;
    try {
        const result = await netmdHelper.commands[cmd](args);
        await out({ result });
        if (cmd === 'format' && args.mode === 'himd') {        // the recorder now disconnects and comes back as a Hi-MD recorder: the old connection is dead
            log('the recorder was switched to Hi-MD mode: dropping the old connection');
            held = null; mscSynced = false; detached.splice(0);
        }
    } catch (e) {
        const text = String(e && e.message || e);
        failed = text !== 'stopped';          // a read ended on purpose (another track was asked for) is normal: keep holding the recorder
        await out({ error: text });
    } finally {
        current = null;
        ctl.destroy();
        if (NETMD_WRITES.has(cmd)) lastWriteDone = Date.now();
    }
    if (failed) await teardown('the command failed');
}
let current = null;                               // { sock, ctl } while a command runs
let queue = Promise.resolve();

const LIGHT = new Set(['ping', 'status', 'writes', 'guard', 'devices']);      // answered immediately, outside the queue, without disturbing a read in progress

async function runJob(sock, msg) {
    const out = obj => new Promise(resolve => { if (sock.destroyed) resolve(); else sock.write(JSON.stringify(obj) + '\n', () => resolve()); });
    const cmd = String(msg.cmd || '');
    const light = LIGHT.has(cmd);
    if (!light) clearTimeout(idleTimer);
    if (!light) {                                   // the recorder needs a short rest after a burst of writes: the next request waits until it has had it
        const rest = lastWriteDone + REST_MS - Date.now();
        if (rest > 0) await new Promise(r => setTimeout(r, rest));
    }
    if (!light) wantMode = msg.h === 'netmd' ? 'netmd' : 'himd';
    try {
        if (!light && msg.h === 'netmd') { await runNetmd(sock, msg, out); return; }
        if (cmd === 'ping') { await out({ result: { ok: true } }); return; }
        if (cmd === 'status') { await out({ result: { held: !!held, settleSeconds: held ? 0 : Math.max(0, Math.ceil((lastAttach + SETTLE_MS - Date.now()) / 1000)), heldSeconds: held ? Math.round((Date.now() - heldSince) / 1000) : 0, allowed: [...ALLOWED], mountGuard: guardState(), writes: writesOn(), writesAlways: writesAlways(), writesSecondsLeft: writesOn() && !writesAlways() ? Math.round((writesUntil - Date.now()) / 1000) : 0 } }); return; }
        if (cmd === 'guard') {          // {"enabled": true|false}: keep macOS from mounting the recorder's disc (on by default)
            const want = msg.args && typeof msg.args === 'object' ? msg.args.enabled : undefined;
            if (want === false) { try { fs.writeFileSync(GUARD_OFF, 'off\n'); } catch (e) { /* state below tells */ } stopGuard(); }
            if (want === true) { try { fs.unlinkSync(GUARD_OFF); } catch (e) { /* was not off */ } startGuard(); }
            await out({ result: { mountGuard: guardState() } });
            return;
        }
        if (cmd === 'release') { await teardown('requested'); await out({ result: { released: true } }); return; }
        if (cmd === 'writes') {         // {"enabled": true, "minutes": 20}: allow changes to the disc for a while (off by default, and again after a restart)
            const a = msg.args && typeof msg.args === 'object' ? msg.args : {};
            if (a.enabled === true && a.always === true) {
                try { fs.writeFileSync(WRITES_ALWAYS, 'on' + String.fromCharCode(10)); } catch (e) { /* the state below tells */ }
                log('WRITES KEPT ON until switched off');
            } else if (a.enabled === true) {
                const minutes = Math.max(1, Math.min(Number(a.minutes) || 20, 120));
                writesUntil = Date.now() + minutes * 60000;
                log('WRITES SWITCHED ON for ' + minutes + ' minutes');
            } else if (a.enabled === false) {
                writesUntil = 0;
                try { fs.unlinkSync(WRITES_ALWAYS); } catch (e) { /* was not kept on */ }
                log('writes switched off');
            }
            await out({ result: { writes: writesOn(), always: writesAlways(), secondsLeft: writesOn() && !writesAlways() ? Math.round((writesUntil - Date.now()) / 1000) : 0 } });
            return;
        }
        if (cmd === 'devices') {        // the Hi-MD recorders on the USB bus (other programs cannot see one while this service holds it)
            const usbm = require(path.join(RT, 'node_modules', 'usb'));
            const himdjs = require(path.join(RT, 'node_modules', 'himd-js'));
            const known = new Set(himdjs.DevicesIds.filter(d => d.vendorId === 0x054c).map(d => d.deviceId));
            const list = usbm.getDeviceList().map(d => d.deviceDescriptor).filter(d => d.idVendor === 0x054c && known.has(d.idProduct)).map(d => ({ vendorId: d.idVendor, productId: d.idProduct }));
            const netmdjs = require(path.join(RT, 'node_modules', 'netmd-js'));
            const net = usbm.getDeviceList().map(d => d.deviceDescriptor).filter(d => netmdjs.DevicesIds.some(n => n.vendorId === d.idVendor && n.deviceId === d.idProduct)).map(d => ({ vendorId: d.idVendor, productId: d.idProduct }));
            await out({ result: { devices: list, netmd: net } });
            return;
        }
        if (cmd === 'scsi' || cmd === 'scsi_reset') {
            const opcode = msg.args && typeof msg.args.cdb === 'string' ? msg.args.cdb.slice(0, 2).toLowerCase() : '';
            let result, failure = null;
            try { result = cmd === 'scsi' ? await scsiCommand(msg.args || {}) : await scsiReset(); }
            catch (e) {
                // A read that times out soon after a write usually means the recorder is still busy with it: one more try after a rest, before giving up.
                if (opcode === '28' && Date.now() - lastWriteDone < 30000) {
                    log('a read right after a write did not answer (' + String(e && e.message || e) + '); trying once more after a rest');
                    await new Promise(r => setTimeout(r, 4000));
                    try { result = await scsiCommand(msg.args || {}); } catch (e2) { failure = e2; }
                } else failure = e;
            }
            if (failure) {
                log('SCSI failure (' + cmd + (opcode ? ' cdb=' + msg.args.cdb.slice(0, 24) : '') + '): ' + String(failure && failure.message || failure));
                await out({ error: String(failure && failure.message || failure) }); await teardown('a SCSI command failed');
            } else await out({ result });
            return;
        }
        if (!ALLOWED.has(cmd)) { await out({ error: 'The background service does not run "' + cmd + '" yet.' }); return; }
        let args = msg.args && typeof msg.args === 'object' ? msg.args : {};
        let stage = null;
        if (cmd === 'dump') {
            try { const p = prepareDump(args); args = p.args; await out({ event: 'staged', path: p.staged }); } catch (e) { await out({ error: String(e.message || e) }); return; }
        } else if (cmd === 'spatial_get') {          // reads one spatial-audio file off the disc into the staging folder, like a track read
            try {
                if (typeof args.name !== 'string' || !SPATIAL_NAME.test(args.name)) throw new Error('That is not a spatial audio file name.');
                for (const k of ['limit', 'runKB']) if (args[k] !== undefined && !(Number.isInteger(args[k]) && args[k] >= 0 && args[k] <= 1e10)) throw new Error('Bad ' + k + '.');
                const p = prepareDump({ index: 0 });
                args = { name: args.name, out: p.staged, limit: args.limit || 0, runKB: args.runKB || 128, slow: !!args.slow };
                await out({ event: 'staged', path: p.staged });
            } catch (e) { await out({ error: String(e.message || e) }); return; }
        } else {
            try {
                const p = prepareArgs(cmd, args);
                args = p.args; stage = p.stage;
                if (stage) await out({ event: 'staged_dir', path: stage });
                if (WRITE_COMMANDS.has(cmd) && !args.simulate) log('WRITE ' + cmd + ' ' + JSON.stringify(args.indexes || (args.files || []).map(f => path.basename(String(typeof f === 'string' ? f : (f.path || f.frames || f.title || '?'))))).slice(0, 200));
            } catch (e) { await out({ error: String(e.message || e) }); return; }
        }
        const ctl = new PassThrough();
        current = { sock, ctl, cmd };
        helper.setSay(out);
        helper.setCtl(ctl);
        let failed = false;
        try {
            const result = await helper.commands[cmd](args);
            finishStage(stage);                   // the client copies the staged folder before it sees the result
            await out({ result });
        } catch (e) {
            const text = String(e && e.message || e);
            failed = text !== 'stopped';          // a read ended on purpose (the app asked for another track) is normal: keep holding the recorder
            finishStage(stage);
            await out({ error: text });
        } finally {
            current = null;
            ctl.destroy();
            if (WRITE_COMMANDS.has(cmd) && !args.simulate) lastWriteDone = Date.now();
        }
        if (failed) await teardown('the command failed');      // start the next request from a clean state
    } finally {
        if (!light && held) idleTimer = setTimeout(() => teardown('idle'), IDLE_MS);
    }
}

function onMessage(sock, line) {
    let msg;
    try { msg = JSON.parse(line); } catch (e) { sock.write(JSON.stringify({ error: 'Bad request.' }) + '\n'); return; }
    if (msg.t === 'stop') { if (current && current.sock === sock) current.ctl.write('stop\n'); return; }
    if (msg.t !== 'run') { sock.write(JSON.stringify({ error: 'Unknown request type.' }) + '\n'); return; }
    if (LIGHT.has(String(msg.cmd))) {                                      // status-type requests never touch the recorder: answer at once, do not wait or stop a running read
        runJob(sock, msg).catch(e => log('job error: ' + (e && e.stack || e)));
        return;
    }
    if (current && current.sock !== sock) {                                // a new request from another client ends a long read, like the app does
        const op = msg.cmd === 'scsi' && msg.args && typeof msg.args.cdb === 'string' ? ' (SCSI 0x' + msg.args.cdb.slice(0, 2) + ')' : '';
        log('the running ' + (current.cmd || 'read') + ' is stopped because a "' + String(msg.cmd) + '"' + op + ' request arrived from another connection' + (msg.who ? ' | asked by: ' + String(msg.who).slice(0, 300) : ''));
        current.ctl.write('stop\n');
    }
    queue = queue.then(() => runJob(sock, msg)).catch(e => log('job error: ' + (e && e.stack || e)));
}

function onConnection(sock) {
    let buf = '';
    sock.setEncoding('utf8');
    sock.on('data', d => {
        buf += d;
        let i;
        while ((i = buf.indexOf('\n')) >= 0) {
            const line = buf.slice(0, i);
            buf = buf.slice(i + 1);
            if (line.trim()) onMessage(sock, line);
        }
    });
    sock.on('error', () => { });
    sock.on('close', () => { if (current && current.sock === sock) current.ctl.write('stop\n'); });
}

// ---- start ----------------------------------------------------------------------------------------------------------------------------
try { fs.unlinkSync(SOCK); } catch (e) { /* none yet */ }
process.umask(0o077);                              // the socket is created readable and writable by root only ...
const server = net.createServer(onConnection);
server.listen(SOCK, () => {
    const uid = Number(process.env.MDM_UID), gid = Number(process.env.MDM_GID) || 20;
    if (uid) fs.chownSync(SOCK, uid, gid);         // ... then handed to the user who installed the service (and nobody else)
    fs.chmodSync(SOCK, 0o600);
    log('MiniDisc Manager background service ready on ' + SOCK + (uid ? ' (user ' + uid + ')' : ' (root only)'));
    startGuard();
    log('mount guard: ' + guardState());
});

async function shutdown(sig) {
    log('stopping (' + sig + ')');
    stopGuard();
    await teardown('service stopping');
    try { fs.unlinkSync(SOCK); } catch (e) { /* gone */ }
    process.exit(0);
}
process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));
process.on('uncaughtException', e => { log('uncaught: ' + (e && e.stack || e)); teardown('error').finally(() => process.exit(1)); });
