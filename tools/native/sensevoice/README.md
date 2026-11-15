# Native SenseVoice adapter

`python tools/build_sensevoice.py`
builds a CPU executable for release packaging. On Windows the filename ends in
`.exe`. CMake 3.21+, Python and a C++17 compiler are **build requirements only**.
Users download Q8 weights and FSMN VAD; they do not compile this program or install
PyTorch, CUDA, CMake or an alignment model.

`sources.lock.json` pins the required FunASR and ggml sources by immutable commit,
size and SHA256. The builder verifies cached files too. It applies `runtime.patch`
with exact context checking, builds static dependencies, runs CTest, and writes
the executable, `sensevoice-NOTICES.txt` and `build-manifest.json`. Source/build
caches remain under `scratch/build/sensevoice`; no weights or upstream source
tarballs are committed. The packaged CPU baseline disables machine-specific x86
ISA flags and dynamic OpenMP dependencies. MSVC uses a static C runtime and a UTF-8
application manifest for Chinese Windows paths. Windows execution is not yet
locally tested; CI must build and exercise the Windows executable.
The Mac build forces the macOS 14 deployment target before compiler detection;
the builder checks the resulting Mach-O minimum version before packaging it.

## JSON and timing

`-m sensevoice-small-q8.gguf --vad fsmn-vad.gguf -a audio.wav --json` emits one JSON
document on stdout. Diagnostics stay on stderr. It contains `segments`, each with
`start`, `end`, `text` and `words`; each word/token contains `word`, `start`, `end`.
Times are seconds from the beginning of the original audio. Silence returns an
empty segment array. `--threads` selects CPU threads (default 8); `--help` and
`--version` succeed without weights.

The neural forward pass and greedy decoded sequence are unchanged. The adapter
uses Viterbi CTC forced alignment of that same sequence against the same logits,
excluding the four query frames. Like the official SenseVoice Python
`output_timestamp` path, it uses 60 ms speech frames, a −30 ms offset, and zeroes
the blank log-probability where blank wins. Repeated labels require intervening
blank states. This produces intervals, rather than only greedy emission instants;
it does not distribute a line's duration uniformly among characters.

SentencePiece markers and UTF-8 byte fallback are decoded before JSON output.
Chinese model tokens retain their spans; Latin continuation pieces are joined.
Several characters can belong to one model token, so `words` are acoustic tokens,
not a promise of linguistic word segmentation. Downstream dictionary segmentation
still belongs to Pianpian.

**CTC spans are estimates and can be narrow peaks.** Structurally valid intervals
are not evidence of manually verified phonetic boundary accuracy or equality to
Whisper timing. Tests cover repeated labels, blanks, query offsets, invalid paths,
Chinese Unicode, byte fallback, absolute offsets, clipping and JSON escaping.
The local Mac smoke on 16 Nov 2026 preserved the demo transcript and produced
8 segments and 116 token intervals. All 32 exploratory clips passed the pipeline's
coverage, ordering and bounds validator (2,201 tokens). Four transcripts differed
slightly from the upstream prebuilt executable; `--srt` and `--json` agreed in
those four cases on this build, and changing 4 to 8 threads did not change them.
The 16-clip FLEURS CER remained 42/543 characters. Thus the portable build is not
claimed bit-identical to the upstream binary, and the sample is not proof of
unchanged accuracy on arbitrary audio. Detailed results live in ignored
`scratch/native-sensevoice/`.
