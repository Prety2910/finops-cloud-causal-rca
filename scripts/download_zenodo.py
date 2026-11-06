"""Download (parallel ranged, retrying) + md5-verify + extract the canonical RCAEval Zenodo
archives (record 14590730) into data/raw/zenodo/. Idempotent: verified archives leave <name>.ok.
Usage: python -I scripts/download_zenodo.py [RE1-OB RE2-SS ...]   (default: all nine)"""
import hashlib, json, sys, time, urllib.request, zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REC, SEG, WORKERS = "14590730", 16 << 20, 32
out = Path("data/raw/zenodo"); out.mkdir(parents=True, exist_ok=True)
meta = json.load(urllib.request.urlopen(f"https://zenodo.org/api/records/{REC}"))
want = set(sys.argv[1:])


def fetch(url, path, start, end):
    for attempt in range(8):
        try:
            req = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            if len(data) != end - start + 1:
                raise IOError("short read")
            with open(path, "r+b") as fh:
                fh.seek(start); fh.write(data)
            return
        except Exception:
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"segment {start} failed")


for f in sorted(meta["files"], key=lambda f: f["size"]):
    name, size = f["key"], f["size"]
    stem = name.removesuffix(".zip")
    if want and stem not in want:
        continue
    if (out / f"{stem}.ok").exists():
        print("skip", stem); continue
    z = out / name
    url = f"https://zenodo.org/records/{REC}/files/{name}?download=1"
    with open(z, "wb") as fh:
        fh.truncate(size)
    segs = [(s, min(s + SEG, size) - 1) for s in range(0, size, SEG)]
    t0 = time.time()
    with ThreadPoolExecutor(WORKERS) as ex:
        list(ex.map(lambda se: fetch(url, z, *se), segs))
    h = hashlib.md5()
    with open(z, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 24), b""):
            h.update(chunk)
    md5 = f["checksum"].split(":")[1]
    assert h.hexdigest() == md5, f"md5 mismatch for {name}"
    with zipfile.ZipFile(z) as zf:
        zf.extractall(out)
    (out / f"{stem}.ok").write_text(md5 + "\n")
    z.unlink()
    print(f"ok {stem} md5={md5} {size/1e6:.0f}MB in {time.time()-t0:.0f}s", flush=True)
print("all done")
