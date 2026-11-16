# Native SenseVoice adapter

`python tools/build_sensevoice.py`
builds a CPU executable for release packaging. On Windows the filename ends in
`.exe`. CMake 3.21+, Python and a C++17 compiler are **build requirements only**.
Users download Q8 weights and FSMN VAD; they do not compile this program or install
PyTorch, CUDA, CMake or an alignment model.

`sources.lock.json` pins the required FunASR and ggml sources by immutable commit,
size and SHA256. The builder verifies cached files too. It applies `runtime.patch`
with exact context checking, builds static dependencies, runs CTest, and writes
the executables, `sensevoice-NOTICES.txt` and `build-manifest.json`. Source/build
caches remain under `scratch/build/sensevoice`; no weights or upstream source
tarballs are committed. Windows ships a portable x64 entry point and a separate
`pianpian-sensevoice-avx2.exe`. The entry point selects the optimized sibling only
when CPUID advertises SSE4.2, FMA, XSAVE/OSXSAVE, AVX, F16C, BMI1/2 and AVX2, and
XGETBV confirms OS support for saving XMM/YMM registers. Otherwise it uses the
baseline. Both helpers are static and CPU-only, without dynamic OpenMP or CUDA
dependencies. The optimized helper adds executable bytes, not another model.
MSVC uses a static C runtime and UTF-8 application manifests; forwarding to the
optimized helper uses an absolute path and UTF-16 arguments without a shell.
`--cpu-profile` prints the selected profile without loading models.
`PIANPIAN_SENSEVOICE_CPU=baseline` disables dispatch for a diagnostic comparison;
other values never force an unsupported instruction set.

The 16 Nov 2026 Windows CI compiled the earlier baseline successfully, but timed
out after 20 minutes during speech on the 44.8-second demo. The new AVX2 dispatch
has not yet been executed on Windows; CI must measure both speed and output.
The Mac build forces the macOS 14 deployment target before compiler detection;
the builder checks the resulting Mach-O minimum version before packaging it.

## JSON and timing

`-m sensevoice-small-q8.gguf --vad fsmn-vad.gguf -a audio.wav --json` emits one JSON
document on stdout. Diagnostics stay on stderr. It contains `segments`, each with
`start`, `end`, `text` and `words`; each word/token contains `word`, `start`, `end`.
Times are seconds from the beginning of the original audio. Silence returns an
empty segment array. `--threads` selects CPU threads (by default, detected hardware
threads capped at 8 and at least 1); `--help` and
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

The CPU optimization comparison on **16 Nov 2026**, Apple M1 Pro (10 hardware
threads), produced byte-identical JSON before/after on all 32 clips: transcripts
and 2,201 token intervals. The 709 seconds of audio took 29.88 vs 30.02 seconds
at four threads. The 44.8-second demo at default threads had median wall times
of 0.967 vs 0.955 seconds over three runs, including model loading with warm file
caches. Mac performance is effectively unchanged; this is not a Windows speedup
claim. The graph metadata reservation falls from 1 GiB to about 13.4 MB, but Mac
peak resident memory stayed around 317 MB. Reports live in ignored
`scratch/sensevoice-optimization/`.

`tools/check_sensevoice.py --pipeline <packaged pipeline>` runs the short baseline
and selected CPU profile, the full demo and silence. CI saves JSON and stderr
logs under `scratch/native-acceptance/数据/speech/`. It rejects invalid timing,
unexpected silence/speech, changed short-sample transcription and a 180-second
per-case timeout; interval differences are recorded for inspection. This is a
single-run diagnostic, not a statistical benchmark or a general accuracy score.
