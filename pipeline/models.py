"""The app's models: downloaded once, resumable, checked.

    python pipeline/models.py list                                     # JSON: each model, its size, ready or not
    python pipeline/models.py ensure mlx-community/Hy-MT2-1.8B-4bit    # download it (progress lines on stdout)

Files come from ModelScope's copy first (fast from mainland China) and Hugging Face second, and each
one is checked against the size and SHA-256 that the same site publishes. A download that stops resumes
where it left off. A model already in the Hugging Face cache (~/.cache/huggingface) or in ~/.cache/mandarin-kit/models
(the command-line tools' folder) is used where it is.
Folder: $PIANPIAN_MODELS (the app sets it to <data>/models), else ~/.cache/mandarin-kit/models.

Progress lines, for the installer:  @progress {"model": …, "file": …, "done": bytes, "total": bytes}
"""
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from urllib.request import Request, urlopen

LEGACY = Path.home() / ".cache" / "mandarin-kit" / "models"


def cache() -> Path:
    return Path(os.environ.get("PIANPIAN_MODELS") or LEGACY)
NEEDED = re.compile(r"\.(json|safetensors|jinja|model|tiktoken|npz)$")       # weights, config, tokenizer; no images
CATALOG = [
    # size: what the download weighs, for the setup page before anything is fetched
    {"id": "mlx-community/whisper-large-v3-turbo", "task": "transcribe", "about": "Whisper large-v3-turbo: Chinese speech to text", "size": 1_614_000_000},
    {"id": "mlx-community/Hy-MT2-1.8B-4bit", "task": "translate", "about": "Hy-MT2 1.8B (4-bit): Chinese to English, and the word links", "size": 1_017_000_000},
]


def progress(**kw) -> None:
    print("@progress " + json.dumps(kw), flush=True)


def files_of(repo: str) -> tuple[str, list[dict]]:
    """(download base, [{name, size, sha256}]) of the files the app needs: ModelScope's list, else Hugging Face's."""
    try:
        info = json.load(urlopen(f"https://www.modelscope.cn/api/v1/models/{repo}/repo/files?Recursive=true", timeout=20))
        files = [{"name": f["Path"], "size": f["Size"], "sha256": f.get("Sha256")} for f in info["Data"]["Files"] if f["Type"] == "blob"]
        base = f"https://www.modelscope.cn/models/{repo}/resolve/master/"
    except (OSError, ValueError, KeyError, TypeError):
        info = json.load(urlopen(f"https://huggingface.co/api/models/{repo}?blobs=true", timeout=60))
        files = [{"name": f["rfilename"], "size": f.get("size"), "sha256": (f.get("lfs") or {}).get("sha256")} for f in info["siblings"]]
        base = f"https://huggingface.co/{repo}/resolve/main/"
    return base, [f for f in files if NEEDED.search(f["name"]) and "/" not in f["name"] and f["name"] != "configuration.json"]


def hf_cached(repo: str) -> Path | None:
    """A complete snapshot in the Hugging Face cache, if one is there (no download needed)."""
    snaps = Path.home() / ".cache" / "huggingface" / "hub" / f"models--{repo.replace('/', '--')}" / "snapshots"
    for snap in sorted(snaps.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True) if snaps.exists() else []:
        if (snap / "config.json").exists() and (any(snap.glob("*.safetensors")) or any(snap.glob("*.npz"))):
            return snap
    return None


def local_path(repo: str) -> Path | None:
    if Path(repo).expanduser().is_dir():
        return Path(repo).expanduser()
    for base in (cache(), LEGACY):
        if (base / repo.replace("/", "__") / ".complete").exists():
            return base / repo.replace("/", "__")
    return hf_cached(repo)


def fetch(url: str, target: Path, size: int | None, repo: str) -> None:
    """Download url into target, resuming a .part file; raises OSError on failure."""
    part = target.with_name(target.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    req = Request(url, headers={"Range": f"bytes={have}-"} if have else {})
    with urlopen(req, timeout=60) as r:
        if have and r.status != 206:                         # the server ignored the range: start over
            have = 0
        with part.open("ab" if have else "wb") as f:
            done, last = have, 0
            while chunk := r.read(1 << 20):
                f.write(chunk)
                done += len(chunk)
                if done - last >= 8 << 20 or (size and done >= size):
                    progress(model=repo, file=target.name, done=done, total=size)
                    last = done
    if size and part.stat().st_size != size:
        raise OSError(f"got {part.stat().st_size} of {size} bytes")
    part.replace(target)


def ensure(repo: str) -> str:
    """A local folder with the model, downloading what is missing."""
    if (have := local_path(repo)) is not None:
        return str(have)
    dest = cache() / repo.replace("/", "__")
    dest.mkdir(parents=True, exist_ok=True)
    base, files = files_of(repo)
    total = sum(f["size"] or 0 for f in files)
    print(f"downloading {repo} ({total / 1e9:.2f} GB), once…", flush=True)
    for f in files:
        target = dest / f["name"]
        for tries in range(3):                               # a dropped connection resumes where it stopped
            if target.exists() and target.stat().st_size == f["size"]:
                break
            try:
                fetch(base + f["name"], target, f["size"], repo)
            except OSError as e:
                print(f"  {f['name']}: {e}, trying again", flush=True)
        if not target.exists() or target.stat().st_size != f["size"]:
            sys.exit(f"could not download {f['name']} (check the connection and try again: it resumes)")
        if f["sha256"]:
            h = hashlib.sha256()
            with target.open("rb") as fh:
                while chunk := fh.read(1 << 22):
                    h.update(chunk)
            if h.hexdigest() != f["sha256"]:
                target.unlink()
                sys.exit(f"{f['name']}: checksum does not match; deleted it, try again")
    (dest / ".complete").touch()
    return str(dest)


def status() -> list[dict]:
    return [{**m, "ready": (p := local_path(m["id"])) is not None, "path": str(p) if p else None} for m in CATALOG]


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "list":
        print(json.dumps(status(), indent=1))
    elif cmd == "ensure" and len(sys.argv) > 2:
        for repo in sys.argv[2:]:
            print(ensure(repo), flush=True)
    else:
        sys.exit(__doc__)
