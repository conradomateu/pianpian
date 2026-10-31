"""The app's models: downloaded once, resumable, checked, and pinned.

    python pipeline/models.py list                                     # JSON: each model, its size, ready or not
    python pipeline/models.py ensure mlx-community/Hy-MT2-1.8B-4bit    # download it (progress lines on stdout)
    python pipeline/models.py lock                                     # write models.lock.json (python3 dev.py lock)

models.lock.json pins every file of every model (name, size, SHA-256) and the exact revision on both
sites, so everyone gets the same files and a release can change a model on purpose. It has one section
per platform (backend.NAME), and so do the catalog rows; `lock` pins every platform from any machine.
Files come from ModelScope first (the row's own id, or its mirrored repo on Windows; fast from mainland
China), then Hugging Face, then hf-mirror.com, and each is checked against the lock. The Windows models
are mirrored on ModelScope under different ids (OllmOne/whisper.cpp and
Tencent-Hunyuan/Hy-MT2-1.8B-GGUF), with the same files as Hugging Face (checked 31 Oct 2026).
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
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import backend  # backend.NAME: which rows and lock section are this platform's

HERE = Path(__file__).resolve().parent

LOCKFILE = HERE / "models.lock.json"
LEGACY = Path.home() / ".cache" / "mandarin-kit" / "models"           # older versions: read, never written
# weights, config, tokenizer; no images. .bin and .gguf are the whisper.cpp / llama.cpp builds.
NEEDED = re.compile(r"\.(json|safetensors|jinja|model|tiktoken|npz|bin|gguf)$")
ROWS = [
    # size: what the download weighs, for the setup page before anything is fetched;
    # include: the one file the app uses, when the repo holds more
    {"id": "mlx-community/whisper-large-v3-turbo", "platform": "darwin", "task": "transcribe", "about": "Whisper large-v3-turbo: Chinese speech to text", "size": 1_614_000_000},
    {"id": "mlx-community/Hy-MT2-1.8B-4bit", "platform": "darwin", "task": "translate", "about": "Hy-MT2 1.8B (4-bit): Chinese to English, and the word links", "size": 1_017_000_000},
    {"id": "ggerganov/whisper.cpp", "platform": "win32", "task": "transcribe", "about": "Whisper large-v3-turbo (whisper.cpp): Chinese speech to text",
     "size": 1_624_555_275, "include": r"^ggml-large-v3-turbo\.bin$", "modelscope_repo": "OllmOne/whisper.cpp"},
    {"id": "tencent/Hy-MT2-1.8B-GGUF", "platform": "win32", "task": "translate", "about": "Hy-MT2 1.8B (Q4_K_M, llama.cpp): Chinese to English",
     "size": 1_133_080_448, "include": r"^Hy-MT2-1\.8B-Q4_K_M\.gguf$", "modelscope_repo": "Tencent-Hunyuan/Hy-MT2-1.8B-GGUF"},
]
CATALOG = [m for m in ROWS if m["platform"] == backend.NAME]


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
    """This platform's section of models.lock.json: {repo: {"huggingface": revision, "modelscope_repo": id if
    it differs, "files": [...]}}."""
    try:
        return json.loads(LOCKFILE.read_text(encoding="utf-8"))["platforms"].get(backend.NAME, {})
    except (OSError, ValueError, KeyError):
        return {}


def lock_id(entry: dict) -> str:
    """A short fingerprint of a model's pinned files: written into .complete, compared on every start."""
    return hashlib.sha256(json.dumps(sorted((f["name"], f["sha256"]) for f in entry["files"])).encode()).hexdigest()[:16]


def modelscope_repo(repo: str, entry: dict | None = None) -> str:
    """The ModelScope repository for a model: its own id, or the row's mirror (the Windows models
    live on ModelScope under other owners)."""
    if entry and entry.get("modelscope_repo"):
        return entry["modelscope_repo"]
    return next((m["modelscope_repo"] for m in ROWS if m["id"] == repo and m.get("modelscope_repo")), repo)


def sources(repo: str, entry: dict | None, f: dict) -> list[str]:
    """Where one file comes from: ModelScope at the revision that file was pinned at (each file has its own:
    the commit that last changed it), ModelScope's current copy, then Hugging Face's pinned revision, then
    hf-mirror.com (the usual route to Hugging Face from mainland China). The SHA-256 check makes sure that
    whichever answers, it is the pinned file."""
    hf = (entry or {}).get("huggingface", "main")
    ms = f.get("modelscope") or (None if entry else "master")
    urls = [f"https://www.modelscope.cn/models/{modelscope_repo(repo, entry)}/resolve/{ms or 'master'}/"]
    if ms and ms != "master":
        urls.append(f"https://www.modelscope.cn/models/{modelscope_repo(repo, entry)}/resolve/master/")
    urls += [f"https://huggingface.co/{repo}/resolve/{hf}/", f"https://hf-mirror.com/{repo}/resolve/{hf}/"]
    return [u + f["name"] for u in urls]


def _keep(m: dict, name: str) -> bool:
    return bool(NEEDED.search(name) and "/" not in name and name != "configuration.json"
                and (not m.get("include") or re.search(m["include"], name)))


def hf_files(m: dict) -> tuple[str, list[dict]]:
    """(revision, files) a Hugging Face repo serves for a catalog row."""
    info = json.load(urlopen(f"https://huggingface.co/api/models/{m['id']}?blobs=true", timeout=60))
    files = [{"name": f["rfilename"], "size": f.get("size"), "sha256": (f.get("lfs") or {}).get("sha256")}
             for f in info["siblings"] if _keep(m, f["rfilename"])]
    return info["sha"], files


def ms_files(m: dict) -> list[dict]:
    """The files a catalog row's ModelScope repo serves, each with the revision that last changed it."""
    repo = m.get("modelscope_repo") or m["id"]
    info = json.load(urlopen(f"https://www.modelscope.cn/api/v1/models/{repo}/repo/files?Recursive=true", timeout=30))["Data"]["Files"]
    return [{"name": f["Path"], "size": f["Size"], "sha256": f["Sha256"], "modelscope": f.get("Revision") or "master"}
            for f in info if f["Type"] == "blob" and _keep(m, f["Path"])]


def make_lock() -> dict:
    """Ask the sites for every catalog row on every platform and pin them, so `dev.py lock` works the
    same from any machine. ModelScope and Hugging Face must serve the same files; a Windows mirror that
    cannot be reached falls back to Hugging Face's files with ModelScope's current revision unpinned."""
    sections: dict = {}
    for m in ROWS:
        repo = m["id"]
        rev, hf = hf_files(m)
        try:
            files = ms_files(m)
        except (OSError, ValueError, KeyError, TypeError) as e:
            if m["platform"] != "win32":
                raise
            print(f"  {repo}: ModelScope mirror unavailable ({e}); pinning Hugging Face only", flush=True)
            files = [{**f, "modelscope": "master"} for f in hf]
        hf_sha = {f["name"]: f["sha256"] for f in hf}
        for f in files:                                       # small files have no LFS hash on Hugging Face: sizes only
            if hf_sha.get(f["name"]) and hf_sha[f["name"]] != f["sha256"]:
                sys.exit(f"{repo}/{f['name']}: ModelScope and Hugging Face serve different files; not locking")
        entry = {"huggingface": rev, "files": files}
        if m.get("modelscope_repo"):
            entry["modelscope_repo"] = m["modelscope_repo"]
        sections.setdefault(m["platform"], {})[repo] = entry
    return {"platforms": sections}


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
        if not entry and (snap / "config.json").exists() and (any(snap.glob("*.safetensors")) or any(snap.glob("*.npz"))
                                                              or any(snap.glob("*.gguf")) or any(snap.glob("*.bin"))):
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
    if size and have > size:                         # corrupt (two writers appended at once): start over
        part.unlink()
        have = 0
    if size and have == size:                        # a past run fetched it all, then stopped
        part.replace(target)
        return
    req = Request(url, headers={"Range": f"bytes={have}-"} if have else {})
    try:
        r = urlopen(req, timeout=60)
    except HTTPError as e:
        if e.code != 416 or not have:                # 416: the server can't continue from `have`
            raise
        part.unlink(missing_ok=True)                 # don't trust the bytes: download() hashes target
        have = 0
        r = urlopen(Request(url), timeout=60)
    with r:
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
    """Without a lock entry: ModelScope's list of the files the app needs (the row's mirror on Windows),
    else Hugging Face's."""
    m = next((x for x in ROWS if x["id"] == repo), {"id": repo})
    try:
        files = ms_files(m)
    except (OSError, ValueError, KeyError, TypeError):
        files = hf_files(m)[1]
    return [f for f in files if _keep(m, f["name"])]


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
