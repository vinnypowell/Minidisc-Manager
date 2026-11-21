// appaudio (macOS): records ONLY the sound of one application (the MiniDisc Manager window with the streaming site) and writes it to stdout as
// raw 44.1 kHz, 16-bit, stereo PCM, in real time, with silence where nothing plays (the recorder in bandcamp.py works out times from how many bytes
// have arrived, exactly as with the Windows helper appaudio.exe).
//
//   usage: appaudio <pid of the program whose sound is wanted>      stops when stdin is closed
//
// It uses ScreenCaptureKit (see the comment at the filter below for what is captured). The first use asks the user for the "Screen & System Audio Recording" permission (for
// the program that started this one). ScreenCaptureKit delivers 48 kHz, so the sound is converted to 44.1 kHz here.
// Build: swiftc -O -swift-version 5 -o appaudio appaudio_mac.swift -framework ScreenCaptureKit -framework CoreMedia
import Foundation
import ScreenCaptureKit
import CoreMedia

setvbuf(stdout, nil, _IONBF, 0)

let debugPath = "/tmp/mdm_appaudio.log"          // only written when the environment variable MDM_APPAUDIO_DEBUG is set: what was found and delivered
let debugOn = ProcessInfo.processInfo.environment["MDM_APPAUDIO_DEBUG"] != nil
func debug(_ s: String) {
    if !debugOn { return }
    let line = String(format: "%.3f ", Date().timeIntervalSince1970) + s + "\n"
    if let h = FileHandle(forWritingAtPath: debugPath) { h.seekToEndOfFile(); h.write(line.data(using: .utf8)!); h.closeFile() }
    else { FileManager.default.createFile(atPath: debugPath, contents: line.data(using: .utf8)) }
}
func fail(_ s: String, code: Int32 = 1) -> Never {
    FileHandle.standardError.write((s + "\n").data(using: .utf8)!)
    debug("FAIL: " + s)
    exit(code)
}

guard CommandLine.arguments.count >= 2, let targetPid = Int32(CommandLine.arguments[1]) else { fail("usage: appaudio <pid>", code: 2) }
// With "all" as the second argument every application's sound is captured (a fallback while the per-program capture is being tried out).
let captureAll = CommandLine.arguments.count >= 3 && CommandLine.arguments[2] == "all"

// "Who is responsible for this process" (private but long-standing libSystem call).
typealias RespFn = @convention(c) (pid_t) -> pid_t
let respSym = dlsym(UnsafeMutableRawPointer(bitPattern: -2), "responsibility_get_pid_responsible_for_pid")
let responsible: RespFn? = respSym.map { unsafeBitCast($0, to: RespFn.self) }

let RATE = 44100
final class Capture: NSObject, SCStreamOutput, SCStreamDelegate {
    var stream: SCStream?
    let lock = NSLock()
    var pending = [Int16]()                    // interleaved stereo samples (44.1 kHz) waiting to be written
    var inL = [Float](), inR = [Float]()       // received sound not yet converted to 44.1 kHz
    var phase = 0.0                            // position (in input frames) of the next output frame
    var written = 0                            // frames written so far
    var t0 = Date()
    var delivered = 0, peakNow: Float = 0      // for the log
    var firstAudio = false

    func stream(_ stream: SCStream, didOutputSampleBuffer sb: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .audio, sb.isValid, let fd = sb.formatDescription, let asbd = fd.audioStreamBasicDescription else { return }
        let channels = Int(asbd.mChannelsPerFrame)
        let planar = (asbd.mFormatFlags & kAudioFormatFlagIsNonInterleaved) != 0
        let inRate = asbd.mSampleRate > 0 ? asbd.mSampleRate : 48000
        var l = [Float](), r = [Float]()
        do {
            try sb.withAudioBufferList { list, _ in
                let bufs = UnsafeMutableAudioBufferListPointer(list.unsafeMutablePointer)
                if planar {
                    let frames = Int(bufs[0].mDataByteSize) / 4
                    let pl = bufs[0].mData!.assumingMemoryBound(to: Float.self)
                    let pr = bufs[min(1, bufs.count - 1)].mData!.assumingMemoryBound(to: Float.self)
                    l = Array(UnsafeBufferPointer(start: pl, count: frames)); r = Array(UnsafeBufferPointer(start: pr, count: frames))
                } else {
                    let p = bufs[0].mData!.assumingMemoryBound(to: Float.self)
                    let frames = Int(bufs[0].mDataByteSize) / 4 / max(1, channels)
                    l.reserveCapacity(frames); r.reserveCapacity(frames)
                    for i in 0..<frames { l.append(p[i * channels]); r.append(p[i * channels + min(1, channels - 1)]) }
                }
            }
        } catch { debug("audio buffer error: \(error)"); return }
        lock.lock()
        inL.append(contentsOf: l); inR.append(contentsOf: r); delivered += l.count
        for v in l { let a = abs(v); if a > peakNow { peakNow = a } }
        // convert to 44.1 kHz by linear interpolation
        let step = inRate / Double(RATE)
        while phase + 1 < Double(inL.count) {
            let i = Int(phase), f = Float(phase - Double(i))
            let a = inL[i] + (inL[i + 1] - inL[i]) * f, b = inR[i] + (inR[i + 1] - inR[i]) * f
            pending.append(Int16(max(-1.0, min(1.0, a)) * 32767)); pending.append(Int16(max(-1.0, min(1.0, b)) * 32767))
            phase += step
        }
        let used = min(Int(phase), inL.count)
        if used > 0 { inL.removeFirst(used); inR.removeFirst(used); phase -= Double(used) }
        lock.unlock()
        if !firstAudio { firstAudio = true; debug("first audio buffer: \(l.count) frames, planar=\(planar), channels=\(channels), rate=\(inRate)") }
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) { fail("The sound capture stopped: \(error.localizedDescription)") }

    // Writes the sound at the pace of the clock: whatever has arrived, and silence for what is missing.
    func pump() {
        t0 = Date()
        var lastLog = Date()
        while true {
            usleep(20000)
            let due = Int(Date().timeIntervalSince(t0) * Double(RATE)) - written
            if due < 441 { continue }
            lock.lock()
            let have = min(due, pending.count / 2)
            var chunk = Array(pending.prefix(have * 2))
            pending.removeFirst(have * 2)
            if pending.count > RATE * 2 { pending.removeFirst(pending.count - RATE) }      // never fall far behind: keep the newest second
            let peak = peakNow
            lock.unlock()
            if have < due { chunk.append(contentsOf: [Int16](repeating: 0, count: (due - have) * 2)) }
            written += due
            if Date().timeIntervalSince(lastLog) >= 1.0 {
                lastLog = Date()
                lock.lock(); let d = delivered; peakNow = 0; lock.unlock()
                debug(String(format: "level: peak %.4f, %d frames received in total, %d written", peak, d, written))
            }
            let data = chunk.withUnsafeBufferPointer { Data(buffer: $0) }
            do { try FileHandle.standardOutput.write(contentsOf: data) } catch { exit(0) }      // the reader went away
        }
    }
}

let cap = Capture()
let sem = DispatchSemaphore(value: 0)
var startError: String? = nil
let deniedText = "macOS has not allowed recording yet. In System Settings > Privacy & Security > Screen & System Audio Recording, switch ON the entry for the program that started MiniDisc Manager (Terminal, if you started it from there; MiniDisc Manager itself when it runs as an app), then quit and reopen that program."

SCShareableContent.getExcludingDesktopWindows(false, onScreenWindowsOnly: false) { content, error in
    defer { sem.signal() }
    if let error = error {
        let ns = error as NSError
        startError = ns.code == -3801 ? deniedText : "Could not list the applications: \(error.localizedDescription) (\(ns.code))"
        return
    }
    guard let content = content, let display = content.displays.first else { startError = "No display was found."; return }
    var apps = [SCRunningApplication]()
    for a in content.applications {
        let owner = responsible?(a.processID) ?? a.processID
        debug("app pid=\(a.processID) responsible=\(owner) bundle=\(a.bundleIdentifier) name=\(a.applicationName)")
        if a.processID == targetPid || owner == targetPid { apps.append(a) }
    }
    let filter: SCContentFilter
    if captureAll {
        debug("capturing the sound of ALL applications")
        filter = SCContentFilter(display: display, excludingApplications: [], exceptingWindows: [])
    } else {
        // The web view's sound is made by WebKit helper processes that ScreenCaptureKit does not list as applications of the program, so a capture of "just this
        // program" is silent. Instead everything is captured EXCEPT the other applications that are listed (a browser, a chat program, a music player ...): what
        // is left is this program, its web view and the system itself.
        if apps.isEmpty { startError = "The program (process \(targetPid)) was not found among the running applications."; return }
        let others = content.applications.filter { a in a.processID != targetPid && (responsible?(a.processID) ?? a.processID) != targetPid }
        debug("capturing everything except \(others.count) other application(s); this program: " + apps.map { "\($0.processID):\($0.bundleIdentifier)" }.joined(separator: ", "))
        filter = SCContentFilter(display: display, excludingApplications: others, exceptingWindows: [])
    }
    let cfg = SCStreamConfiguration()
    cfg.capturesAudio = true
    cfg.sampleRate = 48000
    cfg.channelCount = 2
    cfg.excludesCurrentProcessAudio = false
    cfg.width = 2; cfg.height = 2                                         // the picture is not wanted: the smallest and slowest possible
    cfg.minimumFrameInterval = CMTime(value: 1, timescale: 1)
    cfg.showsCursor = false
    let stream = SCStream(filter: filter, configuration: cfg, delegate: cap)
    do {
        try stream.addStreamOutput(cap, type: .audio, sampleHandlerQueue: DispatchQueue(label: "audio"))
        try stream.addStreamOutput(cap, type: .screen, sampleHandlerQueue: DispatchQueue(label: "video"))
    } catch { startError = "Could not attach to the capture: \(error.localizedDescription)"; return }
    cap.stream = stream
    stream.startCapture { err in
        if let err = err {
            let ns = err as NSError
            startError = ns.code == -3801 ? deniedText : "Could not start the capture: \(err.localizedDescription) (\(ns.code))"
        }
    }
}
_ = sem.wait(timeout: .now() + 20)
// startCapture reports asynchronously; give it a moment to fail before going on
Thread.sleep(forTimeInterval: 1.5)
if let e = startError { fail(e) }
debug("capture started for pid \(targetPid)")

Thread.detachNewThread { cap.pump() }
Thread.detachNewThread {                                                  // stop when the reader closes our stdin
    while FileHandle.standardInput.availableData.count > 0 {}
    debug("stdin closed: stopping")
    cap.stream?.stopCapture { _ in exit(0) }
    Thread.sleep(forTimeInterval: 2); exit(0)
}
RunLoop.main.run()
