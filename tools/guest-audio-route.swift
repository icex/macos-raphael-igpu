// Raphael guest audio routing: list CoreAudio devices, or create a stacked
// multi-output device (QEMU USB output + BlackHole 2ch) and make it the default
// output so host speakers and Sunshine capture both receive system audio.
import CoreAudio
import Foundation

let system = AudioObjectID(kAudioObjectSystemObject)

func address(_ selector: AudioObjectPropertySelector,
             _ scope: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal) -> AudioObjectPropertyAddress {
    return AudioObjectPropertyAddress(mSelector: selector, mScope: scope,
                                      mElement: kAudioObjectPropertyElementMain)
}

func string(_ object: AudioObjectID, _ selector: AudioObjectPropertySelector) -> String {
    var addr = address(selector)
    var size = UInt32(MemoryLayout<CFString?>.size)
    var value: CFString? = nil
    let status = withUnsafeMutablePointer(to: &value) {
        AudioObjectGetPropertyData(object, &addr, 0, nil, &size, $0)
    }
    guard status == noErr, let text = value else { return "" }
    return text as String
}

func channels(_ device: AudioObjectID, _ scope: AudioObjectPropertyScope) -> Int {
    var addr = address(kAudioDevicePropertyStreamConfiguration, scope)
    var size: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(device, &addr, 0, nil, &size) == noErr, size > 0 else { return 0 }
    let raw = UnsafeMutableRawPointer.allocate(byteCount: Int(size), alignment: 16)
    defer { raw.deallocate() }
    guard AudioObjectGetPropertyData(device, &addr, 0, nil, &size, raw) == noErr else { return 0 }
    let list = UnsafeMutableAudioBufferListPointer(raw.assumingMemoryBound(to: AudioBufferList.self))
    return list.reduce(0) { $0 + Int($1.mNumberChannels) }
}

func devices() -> [AudioObjectID] {
    var addr = address(kAudioHardwarePropertyDevices)
    var size: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(system, &addr, 0, nil, &size) == noErr else { return [] }
    var ids = [AudioObjectID](repeating: 0, count: Int(size) / MemoryLayout<AudioObjectID>.size)
    guard AudioObjectGetPropertyData(system, &addr, 0, nil, &size, &ids) == noErr else { return [] }
    return ids
}

func defaultDevice(_ selector: AudioObjectPropertySelector) -> AudioObjectID {
    var addr = address(selector)
    var size = UInt32(MemoryLayout<AudioObjectID>.size)
    var id: AudioObjectID = 0
    _ = AudioObjectGetPropertyData(system, &addr, 0, nil, &size, &id)
    return id
}

func setDefault(_ selector: AudioObjectPropertySelector, _ device: AudioObjectID) -> OSStatus {
    var addr = address(selector)
    var id = device
    return AudioObjectSetPropertyData(system, &addr, 0, nil, UInt32(MemoryLayout<AudioObjectID>.size), &id)
}

struct Info { let id: AudioObjectID; let name: String; let uid: String; let manufacturer: String
              let inputs: Int; let outputs: Int }
func inventory() -> [Info] {
    return devices().map { id in
        Info(id: id, name: string(id, kAudioObjectPropertyName), uid: string(id, kAudioDevicePropertyDeviceUID),
             manufacturer: string(id, kAudioObjectPropertyManufacturer),
             inputs: channels(id, kAudioObjectPropertyScopeInput),
             outputs: channels(id, kAudioObjectPropertyScopeOutput))
    }
}

let aggregateName = "Raphael Multi-Output"
let aggregateUID = "raphael-multi-output"
let mode = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "list"
let all = inventory()
let defaultOut = defaultDevice(kAudioHardwarePropertyDefaultOutputDevice)
let defaultSys = defaultDevice(kAudioHardwarePropertyDefaultSystemOutputDevice)
for d in all {
    let flags = (d.id == defaultOut ? " [default-output]" : "") + (d.id == defaultSys ? " [system-output]" : "")
    print("\(d.id)\t\(d.name)\tuid=\(d.uid)\tmaker=\(d.manufacturer)\tin=\(d.inputs) out=\(d.outputs)\(flags)")
}
if mode == "list" { exit(0) }
if mode == "default-input" {
    let needle = CommandLine.arguments.count > 2 ? CommandLine.arguments[2] : ""
    guard let target = all.first(where: { $0.inputs > 0 && $0.name.contains(needle) }) else {
        print("no input device matching \(needle)"); exit(2) }
    let s = setDefault(kAudioHardwarePropertyDefaultInputDevice, target.id)
    print("default input -> \(target.name) (\(target.id)): \(s)")
    exit(s == noErr ? 0 : 4)
}
if mode == "default" {
    // default <name substring>: make that device the default and system output.
    let needle = CommandLine.arguments.count > 2 ? CommandLine.arguments[2] : ""
    guard let target = all.first(where: { $0.outputs > 0 && $0.name.contains(needle) }) else {
        print("no output device matching \(needle)"); exit(2) }
    let s1 = setDefault(kAudioHardwarePropertyDefaultOutputDevice, target.id)
    let s2 = setDefault(kAudioHardwarePropertyDefaultSystemOutputDevice, target.id)
    print("default output -> \(target.name) (\(target.id)): \(s1) system output: \(s2)")
    exit(s1 == noErr && s2 == noErr ? 0 : 4)
}

guard let usb = all.first(where: { $0.manufacturer.contains("QEMU") && $0.outputs > 0 }) else {
    print("no QEMU USB output device"); exit(2) }
guard let hole = all.first(where: { $0.name == "BlackHole 2ch" }) else {
    print("no BlackHole 2ch device"); exit(2) }

var aggregate = all.first(where: { $0.uid == aggregateUID })?.id ?? 0
if aggregate == 0 {
    let description: [String: Any] = [
        kAudioAggregateDeviceNameKey: aggregateName,
        kAudioAggregateDeviceUIDKey: aggregateUID,
        kAudioAggregateDeviceIsStackedKey: 1,
        kAudioAggregateDeviceMainSubDeviceKey: usb.uid,
        kAudioAggregateDeviceSubDeviceListKey: [
            [kAudioSubDeviceUIDKey: usb.uid],
            [kAudioSubDeviceUIDKey: hole.uid, kAudioSubDeviceDriftCompensationKey: 1],
        ],
    ]
    let status = AudioHardwareCreateAggregateDevice(description as CFDictionary, &aggregate)
    guard status == noErr, aggregate != 0 else { print("create failed: \(status)"); exit(3) }
    print("created \(aggregateName) id=\(aggregate)")
} else {
    print("reusing \(aggregateName) id=\(aggregate)")
}
let s1 = setDefault(kAudioHardwarePropertyDefaultOutputDevice, aggregate)
let s2 = setDefault(kAudioHardwarePropertyDefaultSystemOutputDevice, aggregate)
print("default output -> \(aggregate): \(s1) system output: \(s2)")
exit(s1 == noErr && s2 == noErr ? 0 : 4)
