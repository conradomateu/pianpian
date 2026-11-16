# PLaMo word-link helper

`python tools/build_alignment.py` builds `pipeline/bin/pianpian-align[.exe]`, its
notices and build manifest. CMake 3.21+ and a C++17 compiler are build-time requirements
only. The builder fetches the small llama.cpp **b11851** header set by immutable
commit, size and SHA-256. It reuses the download verifier from `build_sensevoice.py`.

The executable dynamically loads the already installed b11851 translation runtime
from the explicit `--runtime` directory; it does not search for a system llama library
or download anything. Keep the runtime and pinned header ABI together when upgrading.
The helper itself links only system libraries. Windows uses a static C runtime and
UTF-8 application manifest. The Mac executable targets macOS 14.

## Contract

```
pianpian-align --runtime /path/to/llama-libraries --model plamo-Q3_K_M.gguf --layer 7
```

Input is one hex-encoded UTF-8 prompt per line, including its explicit BOS and PFML
control tokens. Tokenization uses `add_special=false` and `parse_special=true`.
Each flushed stdout line is JSON with `tokens` (`id`, `piece` as UTF-8 byte values)
and `vectors` (one finite float vector per token). Byte pieces preserve split Unicode
and control tokens exactly. Diagnostics go to stderr. The process loads the model
once and clears the context between lines. Malformed input, missing libraries,
more than 4,096 tokens or incomplete vectors cause a nonzero exit.

The CPU forward pass captures the selected intermediate `l_out-7` tensor through
llama.cpp's evaluation callback. This is the eighth transformer block, before final
normalization/output projection. It uses the same PLaMo Q3 weights as translation;
no alignment model, Python ML runtime or GPU runtime is added. Vector comparisons
and conversion to word offsets belong to `pipeline/align_srt.py`.

## Evidence and limits

On 16 Nov 2026, the macOS Apple Silicon build passed both CTest cases and produced
six complete prompt results whose token bytes exactly reconstructed the inputs.
All vectors were finite and had 1,536 dimensions. A separate 1,201-token prompt
verified accumulation across 512-token microbatches. The executable was 58,864 bytes
in this build; code signing may change its size. On 16 Nov 2026, the Windows packaged
CPU pipeline also produced 41 model links on the self-authored demo; this validates
execution and output structure, not linguistic accuracy. See the
[Windows test history](../../../ARCHITECTURE.md#windows-test-history) for the CI run and remaining checks.

Layer 7 was selected from a small exploratory comparison of six self-authored
Chinese/English sentence pairs. It produced useful links such as 天气↔weather,
公园↔park, 餐厅↔restaurant and 窗户↔window, with known mistakes such as 我↔help.
This is a heuristic, not a measured guarantee of word-alignment accuracy. Final-layer
HTTP embeddings performed poorly in that same exploration and are not used.
Detailed experiments are ignored under `scratch/plamo-integration/`.
