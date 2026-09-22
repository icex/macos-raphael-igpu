// Measure display-link timing on the main display: nominal refresh, callback
// interval, and the offset between the link's output timestamp and the clock.
// A virtual display whose frames carry stale timestamps shows a large,
// constant offset here.
import CoreVideo
import CoreGraphics
import Foundation

var timebase = mach_timebase_info_data_t(); mach_timebase_info(&timebase)
func ns(_ t: UInt64) -> Double { Double(t) * Double(timebase.numer) / Double(timebase.denom) }
let display = CGMainDisplayID()
var link: CVDisplayLink?
CVDisplayLinkCreateWithCGDisplay(display, &link)
guard let dl = link else { print("no display link"); exit(1) }
let nominal = CVDisplayLinkGetNominalOutputVideoRefreshPeriod(dl)
print("display \(display) model \(String(CGDisplayModelNumber(display), radix: 16)) nominal period \(Double(nominal.timeValue) / Double(nominal.timeScale) * 1000) ms")
var samples: [(Double, Double)] = []   // (callback interval ms, output-now offset ms)
var lastNow: Double = 0
let lock = NSLock()
CVDisplayLinkSetOutputHandler(dl) { _, inNow, inOutput, _, _ in
    let now = ns(mach_absolute_time())
    let outNs = ns(inOutput.pointee.hostTime), nowNs = ns(inNow.pointee.hostTime)
    lock.lock()
    let interval = lastNow == 0 ? 0 : (now - lastNow) / 1e6
    lastNow = now
    samples.append((interval, (outNs - nowNs) / 1e6))
    lock.unlock()
    return kCVReturnSuccess
}
CVDisplayLinkStart(dl)
Thread.sleep(forTimeInterval: 4)
CVDisplayLinkStop(dl)
lock.lock()
let intervals = samples.dropFirst().map { $0.0 }, offsets = samples.map { $0.1 }
lock.unlock()
func stats(_ a: [Double]) -> String {
    guard !a.isEmpty else { return "none" }
    let s = a.sorted(); return String(format: "n=%d min=%.2f med=%.2f max=%.2f", a.count, s.first!, s[s.count / 2], s.last!)
}
print("callbacks in 4 s: \(samples.count)  interval ms: \(stats(intervals))")
print("output-now offset ms: \(stats(offsets))")
