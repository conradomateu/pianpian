# Contributing to Pianpian 片片

Small fixes are as welcome as big ones: a wrong pinyin, a grammar mark that misfires, a download that fails
on some site, a sentence in the docs that confused you.

- **Something went wrong:** press **Report** in the app (it fills in an issue without your files or links), or [open one](https://github.com/conradomateu/pianpian/issues/new/choose).
- **Wrong pinyin:** add the word to [`pipeline/pinyin_fixes.txt`](pipeline/pinyin_fixes.txt) and open a pull request. No code needed.
- **Wrong grammar mark:** fix the rule in `pipeline/grammar.py` and add the failing sentence to `tests/test_grammar.py`.
- **A new feature:** open an issue first. The app is one screen with menus on purpose, and a good idea can still not fit.

## Set up

Needs Python 3.12+, Git, uv, CMake 3.21+ and a C++17 compiler (Xcode command-line tools on Mac,
Visual Studio C++ tools on Windows). Node.js enables JavaScript syntax checks. These compiler tools
are for development; downloaded apps contain the speech and word-link helpers already.

```bash
git clone https://github.com/conradomateu/pianpian && cd pianpian
python3 dev.py engine     # the five-package pipeline environment in .venv and native helpers
python3 dev.py serve      # the app in your browser at http://127.0.0.1:8770
python3 dev.py check      # lint and tests: the same as CI
```

On Windows use `python` instead of `python3`. Development resolves dependencies from
`pyproject.toml`; packaged setup uses the platform's hashed requirements file.

| Command | Does |
|---|---|
| `python3 dev.py app` | Opens a dev app: `~/Applications/Pianpian.app` on Mac, `launcher.py` on Windows |
| `python3 dev.py native` | Rebuilds the pinned speech and word-link helpers |
| `python3 dev.py build` | Builds the app, DMG and ZIP on Mac; app, installer and ZIP on Windows (Inno Setup 6 required) |
| `python3 dev.py preview` | Serves the website and demo at http://127.0.0.1:8766 (AnkiConnect uses 8765) |
| `python3 dev.py shots` | Takes screenshots using the self-authored demo |
| `python3 dev.py lock` | Regenerates package and model pins; review the resulting changes |
| `python3 dev.py version` | Previews the version implied by the commits |

From mainland China set `UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple` first.
[`ARCHITECTURE.md`](ARCHITECTURE.md) explains how the pieces fit; [`AGENTS.md`](AGENTS.md) has the full rules.

### Updating a checkout

Close Pianpian before updating. From the checkout, run:

```bash
git pull --ff-only
python3 dev.py engine
python3 dev.py app
```

Use `python` on Windows. `dev.py engine` rebuilds native helpers and syncs the pipeline packages.

### CI and optional measurements

Routine CI runs code checks and, on Windows, builds the installer and exercises the packaged
CPU pipeline with the self-authored demo. That checks transcription, pinyin, translation, word
times, bilingual links and the output video.

Additional SenseVoice performance comparisons are **manual and off by default**. In GitHub Actions,
run the `windows` workflow with `benchmark_speech` enabled, or use:

```bash
gh workflow run windows.yml --ref YOUR_BRANCH -f benchmark_speech=true
```

Use this when changing the speech engine or investigating performance. The
[native speech README](tools/native/sensevoice/README.md) describes the diagnostic and its limits.

## A pull request

- `python3 dev.py check` passes.
- No videos, subtitles, textbook pages or other people's content, in the repository, tests or screenshots. Use the demo in `demo/`.
- Say what you tested, on what, and mark the rest "not tested". UI changes are tried with a real click in a real browser.
- Keep paths and the model engines behind their small interfaces shared by macOS and Windows, and the page free of frameworks and build steps.
- One change per pull request. Its title starts with `fix:`, `feat:`, `docs:` or `chore:`: releases and the changelog are made from it (`python3 dev.py version` shows what the commits so far would release).
- No personal data in commits, code or screenshots. An AI assistant is fine; you answer for what you send. No AI co-author trailers.

## Licence

Pianpian is [MIT licensed](LICENSE). By sending a pull request you agree that your contribution goes in under
the same licence, and you confirm you wrote it or have the right to send it.

The name Pianpian 片片 and the watermelon logo are not part of the licence. Say "based on Pianpian" and link
to it, but give your own version its own name and logo.
