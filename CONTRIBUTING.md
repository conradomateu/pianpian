# Contributing to Pianpian 片片

Small fixes are as welcome as big ones: a wrong pinyin, a grammar mark that misfires, a download that fails
on some site, a sentence in the docs that confused you.

- **Something went wrong:** press **Report** in the app (it fills in an issue without your files or links), or [open one](https://github.com/conradomateu/pianpian/issues/new/choose).
- **Wrong pinyin:** add the word to [`pipeline/pinyin_fixes.txt`](pipeline/pinyin_fixes.txt) and open a pull request. No code needed.
- **Wrong grammar mark:** fix the rule in `pipeline/grammar.py` and add the failing sentence to `tests/test_grammar.py`.
- **A new feature:** open an issue first. The app is one screen with menus on purpose, and a good idea can still not fit.

## Set up

```bash
git clone https://github.com/conradomateu/pianpian && cd pianpian
python3 dev.py engine     # the pipeline's environment in .venv (about 700 MB)
python3 dev.py serve      # the app in your browser at http://127.0.0.1:8770
python3 dev.py check      # lint and tests: the same as CI
```

From mainland China set `UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple` first.
[`ARCHITECTURE.md`](ARCHITECTURE.md) explains how the pieces fit; [`AGENTS.md`](AGENTS.md) has the full rules.

## A pull request

- `python3 dev.py check` passes.
- No videos, subtitles, textbook pages or other people's content, in the repository, tests or screenshots. Use the demo in `demo/`.
- Say what you tested, on what, and mark the rest "not tested". UI changes are tried with a real click in a real browser.
- Keep paths, OCR and the model engines behind their small interfaces (a Windows version is planned), and the page free of frameworks and build steps.
- One change per pull request. Its title starts with `fix:`, `feat:`, `docs:` or `chore:`: releases and the changelog are made from it (`python3 dev.py version` shows what the commits so far would release).
- No personal data in commits, code or screenshots. An AI assistant is fine; you answer for what you send. No AI co-author trailers.

## Licence

Pianpian is [MIT licensed](LICENSE). By sending a pull request you agree that your contribution goes in under
the same licence, and you confirm you wrote it or have the right to send it.

The name Pianpian 片片 and the watermelon logo are not part of the licence. Say "based on Pianpian" and link
to it, but give your own version its own name and logo.
