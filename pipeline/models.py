"""The app's models: downloaded once, resumable, checked, and pinned.

    python pipeline/models.py list                                     # JSON: each model, its size, ready or not
    python pipeline/models.py ensure mlx-community/Hy-MT2-1.8B-4bit    # download it (progress lines on stdout)
    python pipeline/models.py lock                                     # write models.lock.json (python3 dev.py lock)

models.lock.json pins every file of every model (name, size, SHA-256) and the exact revision on both
sites, so everyone gets the same files and a release can change a model on purpose. It has one section
per platform (backend.NAME), and so do the catalog rows. Files come from ModelScope first (fast from
mainland China), then Hugging Face, and each is checked against the lock.
A stopped download resumes. A model already in the Hugging Face cache ($HF_HUB_CACHE, $HF_HOME/hub or
~/.cache/huggingface/hub) or in ~/.cache/mandarin-kit/models (older versions) is used where it is when its files match.
Folder: $PIANPIAN_MODELS (the app sets it to <data>/models), else ~/.cache/pianpian/models.

Progress lines, for the installer:  @progress {"model": …, "file": …, "done": bytes, "total": bytes}
"""
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path
from urllib.request import Request, urlopen

import backend  # backend.NAME: which rows and lock section are this platform's

HERE = Path(__file__).resolve().parent

LOCKFILE = HERE / "models.lock.json"
LEGACY = Path.home() / ".cache" / "mandarin-kit" / "models"           # older versions: read, never written
NEEDED = re.compile(r"\.(json|safetensors|jinja|model|tiktoken|npz)$")       # weights, config, tokenizer; no images
CATALOG = [m for m in [
    # size: what the download weighs, for the setup page before anything is fetched
    {"id": "mlx-community/whisper-large-v3-turbo", "platform": "darwin", "task": "transcribe", "about": "Whisper large-v3-turbo: Chinese speech to text", "size": 1_614_000_000},
    {"id": "mlx-community/Hy-MT2-1.8B-4bit", "platform": "darwin", "task": "translate", "about": "Hy-MT2 1.8B (4-bit): Chinese to English, and the word links", "size": 1_017_000_000},
] if m["platform"] == backend.NAME]


def default(task: str) -> str:
    """The catalog's model for a task ("transcribe" or "translate") on this platform."""
    for m in CATALOG:
        if m["task"] == task:
            return m["id"]
    raise LookupError(f"no {task} model in the catalog for {backend.NAME}")


def cache() -> Path:
    return Path(os.environ.get("PIANPIAN_MODELS") or Path.home() / ".cache" / "pianpian" / "models")


def folder_name(repo: str) -> str:
    return repo.replace("/", "__")


def progress(**kw) -> None:
    print("@progress " + json.dumps(kw), flush=True)


# ---------------------------------------------------------------- the lock
def lock() -> dict:
    """This platform's section of models.lock.json: {repo: {"huggingface": revision, "files": [...]}}."""
    try:
        return json.loads(LOCKFILE.read_text(encoding="utf-8"))["platforms"].get(backend.NAME, {})
    except (OSError, ValueError, KeyError):
        return {}


def lock_id(entry: dict) -> str:
    """A short fingerprint of a model's pinned files: written into .complete, compared on every start."""
    return hashlib.sha256(json.dumps(sorted((f["name"], f["sha256"]) for f in entry["files"])).encode()).hexdigest()[:16]


def sources(repo: str, entry: dict | None, f: dict) -> list[str]:
    """Where one file comes from: ModelScope at the revision that file was pinned at (each file has its own:
    the commit that last changed it), ModelScope's current copy, then Hugging Face's pinned revision.
    The SHA-256 check makes sure that whichever answers, it is the pinned file."""
    ms, hf = f.get("modelscope", "master"), (entry or {}).get("huggingface", "main")
    urls = [f"https://www.modelscope.cn/models/{repo}/resolve/{ms}/", f"https://huggingface.co/{repo}/resolve/{hf}/"]
    if ms != "master":
        urls.insert(1, f"https://www.modelscope.cn/models/{repo}/resolve/master/")
    return [u + f["name"] for u in urls]


def make_lock() -> dict:
    """Ask both sites for every catalog model, check they serve the same files, and pin them in this
    platform's section (the other sections stay as they are)."""
    out = {}
    for m in CATALOG:
        repo = m["id"]
        ms = json.load(urlopen(f"https://www.modelscope.cn/api/v1/models/{repo}/repo/files?Recursive=true", timeout=30))["Data"]["Files"]
        files = [{"name": f["Path"], "size": f["Size"], "sha256": f["Sha256"], "modelscope": f.get("Revision") or "master"} for f in ms
                 if f["Type"] == "blob" and NEEDED.search(f["Path"]) and "/" not in f["Path"] and f["Path"] != "configuration.json"]
        hf = json.load(urlopen(f"https://huggingface.co/api/models/{repo}?blobs=true", timeout=60))
        hf_sha = {s["rfilename"]: (s.get("lfs") or {}).get("sha256") for s in hf["siblings"]}
        for f in files:                                       # small files have no LFS hash on Hugging Face: sizes only
            if hf_sha.get(f["name"]) and hf_sha[f["name"]] != f["sha256"]:
                sys.exit(f"{repo}/{f['name']}: ModelScope and Hugging Face serve different files; not locking")
        out[repo] = {"huggingface": hf["sha"], "files": files}
    try:
        sections = json.loads(LOCKFILE.read_text(encoding="utf-8"))["platforms"]
    except (OSError, ValueError, KeyError):
        sections = {}
    return {"platforms": {**sections, backend.NAME: out}}


# ---------------------------------------------------------------- ready or not
def matches(folder: Path, entry: dict) -> bool:
    """Every pinned file is there with its pinned size (a quick check; the hashes were checked on download)."""
    return all((folder / f["name"]).is_file() and (folder / f["name"]).stat().st_size == f["size"] for f in entry["files"])


def hf_cached(repo: str, entry: dict | None) -> Path | None:
    """A complete snapshot in the Hugging Face cache, if one is there (no download needed)."""
    hub = Path(os.environ.get("HF_HUB_CACHE") or Path(os.environ.get("HF_HOME") or Path.home() / ".cache" / "huggingface") / "hub")
    snaps = hub / f"models--{repo.replace('/', '--')}" / "snapshots"
    for snap in sorted(snaps.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True) if snaps.exists() else []:
        if entry and matches(snap, entry):
            return snap
        if not entry and (snap / "config.json").exists() and (any(snap.glob("*.safetensors")) or any(snap.glob("*.npz"))):
            return snap
    return None


def local_path(repo: str) -> Path | None:
    if Path(repo).expanduser().is_dir():
        return Path(repo).expanduser()
    entry = lock().get(repo)
    for base in (cache(), LEGACY):
        d = base / folder_name(repo)
        done = d / ".complete"
        if not done.exists():
            continue
        if not entry or done.read_text().strip() == lock_id(entry) or matches(d, entry):
            return d
    return hf_cached(repo, entry)


def status() -> list[dict]:
    return [{**m, "ready": (p := local_path(m["id"])) is not None, "path": str(p) if p else None} for m in CATALOG]


def unused() -> list[dict]:
    """Models in the app's own folder that no catalog entry uses any more, or that an update replaced."""
    keep = {str(p) for m in CATALOG if (p := local_path(m["id"]))}
    out = []
    for d in sorted(cache().glob("*__*")) if cache().exists() else []:
        if d.is_dir() and str(d) not in keep and cache() != LEGACY:   # the shared command-line folder is left alone
            out.append({"name": d.name.replace("__", "/"), "path": str(d), "bytes": sum(f.stat().st_size for f in d.rglob("*") if f.is_file())})
    return out


def remove_unused() -> int:
    """Delete what unused() lists (only inside the app's folder). Returns the bytes freed."""
    freed = 0
    for m in unused():
        path = Path(m["path"])
        if path.parent == cache():
            shutil.rmtree(path)
            freed += m["bytes"]
    return freed


# ---------------------------------------------------------------- downloading
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


def files_of(repo: str) -> list[dict]:
    """Without a lock entry: ModelScope's list of the files the app needs, else Hugging Face's."""
    try:
        info = json.load(urlopen(f"https://www.modelscope.cn/api/v1/models/{repo}/repo/files?Recursive=true", timeout=20))
        files = [{"name": f["Path"], "size": f["Size"], "sha256": f.get("Sha256")} for f in info["Data"]["Files"] if f["Type"] == "blob"]
    except (OSError, ValueError, KeyError, TypeError):
        info = json.load(urlopen(f"https://huggingface.co/api/models/{repo}?blobs=true", timeout=60))
        files = [{"name": f["rfilename"], "size": f.get("size"), "sha256": (f.get("lfs") or {}).get("sha256")} for f in info["siblings"]]
    return [f for f in files if NEEDED.search(f["name"]) and "/" not in f["name"] and f["name"] != "configuration.json"]


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 22):
            h.update(chunk)
    return h.hexdigest()


def download(urls: list[str], target: Path, size: int | None, sha256: str | None, label: str) -> None:
    """One pinned file from the first source that serves the right bytes; raises OSError when none does.
    sha256 is the pinned hash; small files have none, and then the size decides."""
    ok = target.exists() and target.stat().st_size == size and (not sha256 or file_sha256(target) == sha256)
    for url in urls * 2:                                      # each source twice: a dropped connection resumes where it stopped
        if ok:
            break
        try:
            fetch(url, target, size, label)
        except OSError as e:
            print(f"  {target.name}: {url.split('/')[2]}: {e}, trying the next source", flush=True)
            continue
        ok = not sha256 or file_sha256(target) == sha256
        if not ok:
            print(f"  {target.name}: checksum does not match the lock; deleted, trying the next source", flush=True)
            target.unlink()
    if not ok:
        raise OSError(f"no source served {target.name}")


def ensure(repo: str) -> str:
    """A local folder with the model, downloading what is missing."""
    if (have := local_path(repo)) is not None:
        return str(have)
    entry = lock().get(repo)
    files = entry["files"] if entry else files_of(repo)
    dest = cache() / folder_name(repo)
    dest.mkdir(parents=True, exist_ok=True)
    print(f"downloading {repo} ({sum(f['size'] or 0 for f in files) / 1e9:.2f} GB), once…", flush=True)
    for f in files:
        try:
            download(sources(repo, entry, f), dest / f["name"], f["size"], f.get("sha256"), repo)
        except OSError:
            sys.exit(f"could not download {f['name']} (check the connection and try again: it resumes)")
    (dest / ".complete").write_text((lock_id(entry) if entry else "") + "\n")
    return str(dest)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "list":
        print(json.dumps(status(), indent=1))
    elif cmd == "ensure" and len(sys.argv) > 2:
        for repo in sys.argv[2:]:
            print(ensure(repo), flush=True)
    elif cmd == "lock":
        LOCKFILE.write_text(json.dumps(make_lock(), indent=1) + "\n", encoding="utf-8")
        print(f"wrote {LOCKFILE.name}")
    else:
        sys.exit(__doc__)
