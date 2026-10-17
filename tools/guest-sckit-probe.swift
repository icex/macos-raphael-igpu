// ScreenCaptureKit timing probe for the main display: prints, for the first
// frames, the sample's presentation timestamp and displayTime relative to now,
// and every attachment key the stream delivers (the Screen Sharing agent reads
// a capture-latency metric from them). Needs the Screen Recording permission.
import ScreenCaptureKit
import CoreMedia
import Foundation

final class Output: NSObject, SCStreamOutput {
    var count = 0
    var latencies: [Double] = []
    var keysPrinted = false
    func stream(_ stream: SCStream, didOutputSampleBuffer sample: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .screen else { return }
        let now = CACurrentMediaTime()
        let pts = CMSampleBufferGetPresentationTimeStamp(sample).seconds
        var displayTime = Double.nan, status = -1
        var extra = ""
        if let attachments = CMSampleBufferGetSampleAttachmentsArray(sample, createIfNecessary: false) as? [[SCStreamFrameInfo: Any]],
           let first = attachments.first {
            if let t = first[.displayTime] as? Double { displayTime = t }
            if let s = first[.status] as? Int { status = s }
            if !keysPrinted {
                keysPrinted = true
                let names = first.keys.map { $0.rawValue }.sorted()
                print("attachment keys: \(names.joined(separator: ", "))")
                for (k, v) in first where !(v is [Any]) { extra += "\(k.rawValue)=\(v) " }
                print("first frame: \(extra)")
            }
        }
        count += 1
        if !displayTime.isNaN { latencies.append((now - displayTime) * 1000) }
        if count <= 5 || count % 60 == 0 {
            print(String(format: "frame %d status %d  now-pts %.1f ms  now-displayTime %.1f ms",
                         count, status, (now - pts) * 1000, (now - displayTime) * 1000))
        }
    }
}

let semaphore = DispatchSemaphore(value: 0)
var stream: SCStream?
let output = Output()
SCShareableContent.getExcludingDesktopWindows(false, onScreenWindowsOnly: false) { content, error in
    guard let content = content, let display = content.displays.first else {
        print("no shareable content: \(String(describing: error))"); exit(2)
    }
    print("display \(display.displayID) \(display.width)x\(display.height)")
    let filter = SCContentFilter(display: display, excludingWindows: [])
    let config = SCStreamConfiguration()
    config.width = display.width * 2; config.height = display.height * 2
    config.minimumFrameInterval = CMTime(value: 1, timescale: 60)
    config.queueDepth = 5
    config.showsCursor = true
    let s = SCStream(filter: filter, configuration: config, delegate: nil)
    do {
        try s.addStreamOutput(output, type: .screen, sampleHandlerQueue: DispatchQueue(label: "probe"))
        s.startCapture { error in
            if let error = error { print("start failed: \(error)"); exit(3) }
        }
    } catch { print("setup failed: \(error)"); exit(3) }
    stream = s
    DispatchQueue.global().asyncAfter(deadline: .now() + 6) {
        s.stopCapture { _ in
            let l = output.latencies.sorted()
            if !l.isEmpty {
                print(String(format: "frames %d  now-displayTime ms: min %.1f med %.1f max %.1f",
                             output.count, l.first!, l[l.count / 2], l.last!))
            } else { print("frames \(output.count), no displayTime attachment") }
            semaphore.signal()
        }
    }
}
_ = semaphore.wait(timeout: .now() + 15)
exit(0)
