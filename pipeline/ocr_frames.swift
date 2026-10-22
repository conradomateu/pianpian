// Read Chinese text out of image files with macOS's built-in OCR (Vision framework). No downloads.
//
//   swift ocr_frames.swift frames_dir   →   one line per image on stdout:  <file name>\t<text>
//
// Used by hardsubs_to_srt.py to turn subtitles that are burned into a video into a real .srt.
import Foundation
import Vision

guard CommandLine.arguments.count == 2 else {
    FileHandle.standardError.write("usage: swift ocr_frames.swift frames_dir\n".data(using: .utf8)!)
    exit(2)
}
let dir = URL(fileURLWithPath: CommandLine.arguments[1])
let files = try FileManager.default.contentsOfDirectory(atPath: dir.path).filter { $0.hasSuffix(".png") || $0.hasSuffix(".jpg") }.sorted()

for name in files {
    let handler = VNImageRequestHandler(url: dir.appendingPathComponent(name), options: [:])
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["zh-Hans", "zh-Hant"]
    request.usesLanguageCorrection = false   // lyrics and memes are not ordinary prose
    try handler.perform([request])
    let lines = (request.results ?? [])
        .compactMap { $0.topCandidates(1).first }
        .filter { $0.confidence >= 0.4 }
        .map { $0.string }
    print("\(name)\t\(lines.joined(separator: " "))")
}
