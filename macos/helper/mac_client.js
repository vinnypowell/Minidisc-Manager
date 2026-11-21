'use strict';
// Talks to the MiniDisc Manager background service (mac_daemon.js) the way himd_helper.js is used:
//     node mac_client.js <command> [json-args]
// Prints the same JSON lines to stdout; a "stop" line on stdin is passed on. Exit code 0 on a result, 1 on an error, 3 if the service is not running.
// Service commands: ping, status, release (hands the recorder back to macOS straight away).
const net = require('net');
const fs = require('fs');

const SOCK = process.env.MDM_SOCKET || '/var/run/minidisc-manager.sock';
const [cmd, argJson] = process.argv.slice(2);
if (!cmd) { console.error('Usage: mac_client.js <command> [json-args]'); process.exit(2); }

let args = {};
try { args = argJson ? JSON.parse(argJson) : {}; } catch (e) { console.log(JSON.stringify({ error: 'The arguments are not valid JSON.' })); process.exit(2); }

const sock = net.connect(SOCK);
let buf = '';
let done = false;
let stagedDir = null;
sock.setEncoding('utf8');
sock.on('connect', () => {
    sock.write(JSON.stringify({ t: 'run', cmd, args, h: process.env.MDM_HELPER || undefined }) + '\n');
    process.stdin.on('data', d => { if (String(d).includes('stop')) sock.write(JSON.stringify({ t: 'stop' }) + '\n'); });
    process.stdin.on('error', () => { });
    process.stdin.resume();
});
sock.on('data', d => {
    buf += d;
    let i;
    while ((i = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, i);
        buf = buf.slice(i + 1);
        if (!line.trim()) continue;
        let o = null;
        try { o = JSON.parse(line); } catch (e) { /* passed through anyway */ }
        // "dump": the service writes into its own staging folder and tells us where; link the file the caller asked for (args.out) to it
        if (o && o.event === 'staged' && typeof args.out === 'string' && typeof o.path === 'string') {
            try { fs.rmSync(args.out, { force: true }); fs.symlinkSync(o.path, args.out); }
            catch (e) { process.stdout.write(JSON.stringify({ error: 'Could not link ' + args.out + ' to the staged file: ' + e.message }) + '\n'); sock.end(); setTimeout(() => process.exit(1), 50); return; }
        }
        // "delete" and friends: index backups are written to a folder only the service can change; copy it to where the caller wants it (args.backupDir)
        if (o && o.event === 'staged_dir' && typeof o.path === 'string') stagedDir = o.path;
        const backupTo = typeof args.backupDir === 'string' ? args.backupDir : (typeof args.dir === 'string' ? args.dir : null);        // "backup" names its folder "dir"
        if (o && (o.result !== undefined || o.error !== undefined) && stagedDir && backupTo) {
            try { fs.mkdirSync(backupTo, { recursive: true }); fs.cpSync(stagedDir, backupTo, { recursive: true }); }
            catch (e) { process.stdout.write(JSON.stringify({ event: 'warning', text: 'Could not copy the backups to ' + backupTo + ': ' + e.message }) + '\n'); }
            stagedDir = null;
        }
        process.stdout.write(line + '\n');
        if (o && (o.result !== undefined || o.error !== undefined)) { done = true; sock.end(); setTimeout(() => process.exit(o.error !== undefined ? 1 : 0), 50); }
    }
});
sock.on('error', e => {
    const text = e.code === 'ENOENT' || e.code === 'ECONNREFUSED'
        ? 'The MiniDisc Manager background service is not running. Install it once with: sudo sh mac_install.sh'
        : e.code === 'EACCES' ? 'This account may not use the MiniDisc Manager background service (it belongs to the user who installed it).'
        : 'Could not reach the background service: ' + e.message;
    console.log(JSON.stringify({ error: text }));
    process.exit(3);
});
sock.on('close', () => { if (!done) { console.log(JSON.stringify({ error: 'The background service closed the connection.' })); process.exit(1); } });
