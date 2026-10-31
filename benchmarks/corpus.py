"""Download, verify and safely extract the public benchmark corpora.

Canterbury (11 files, 2.8 MB) and Silesia (12 files, 211 MB). Archives are
SHA256-pinned; a mismatch aborts. Extraction never trusts member paths: only
regular files with a plain basename are written.

Stdlib only, Python 3.8+.

    python benchmarks/corpus.py            # fetch both
    python benchmarks/corpus.py --quick    # Canterbury only
"""

import argparse
import hashlib
import os
import shutil
import sys
import tarfile
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS_DIR = os.path.join(HERE, ".corpus")
# Small archives are vendored here (same SHA256 pin) because some corpus hosts
# refuse requests from CI runners (canterbury.ac.nz returned 403 on GitHub Actions).
VENDOR_DIR = os.path.join(HERE, "data")

CORPORA = {
    "canterbury": {
        "url": "https://corpus.canterbury.ac.nz/resources/cantrbry.tar.gz",
        "archive": "cantrbry.tar.gz",
        "sha256": "f140e8a5b73d3f53198555a63bfb827889394a42f20825df33c810c3d5e3f8fb",
        "files": ["alice29.txt", "asyoulik.txt", "cp.html", "fields.c", "grammar.lsp",
                  "kennedy.xls", "lcet10.txt", "plrabn12.txt", "ptt5", "sum", "xargs.1"],
    },
    "silesia": {
        "url": "https://sun.aei.polsl.pl/~sdeor/corpus/silesia.zip",
        "archive": "silesia.zip",
        "sha256": "0626e25f45c0ffb5dc801f13b7c82a3b75743ba07e3a71835a41e3d9f63c77af",
        "files": ["dickens", "mozilla", "mr", "nci", "ooffice", "osdb", "reymont",
                  "samba", "sao", "webster", "x-ray", "xml"],
    },
}


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url, dest):
    tmp = dest + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": "hyperpress-fair-bench"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(tmp, "wb") as out:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
    os.replace(tmp, dest)


def _safe_name(name, allowed):
    """Return the plain basename if it is an expected file, else None."""
    norm = name.replace("\\", "/")
    if norm.startswith("/") or ".." in norm.split("/"):
        return None
    base = norm.rsplit("/", 1)[-1]
    if base not in allowed or base in ("", ".", ".."):
        return None
    return base


def _write(dest_dir, base, stream):
    path = os.path.join(dest_dir, base)
    # Final guard: the resolved path must stay inside dest_dir.
    if os.path.dirname(os.path.realpath(path)) != os.path.realpath(dest_dir):
        raise RuntimeError("Refusing to write outside corpus dir: %r" % base)
    with open(path, "wb") as out:
        while True:
            chunk = stream.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
    os.chmod(path, 0o644)


def _extract(archive, dest_dir, allowed):
    os.makedirs(dest_dir, exist_ok=True)
    written = set()
    if archive.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                base = _safe_name(info.filename, allowed)
                if base is None or base in written:
                    continue
                with zf.open(info) as src:
                    _write(dest_dir, base, src)
                written.add(base)
    else:
        with tarfile.open(archive, "r:*") as tf:
            for member in tf:
                if not member.isreg():  # skips links, devices, dirs
                    continue
                base = _safe_name(member.name, allowed)
                if base is None or base in written:
                    continue
                src = tf.extractfile(member)
                if src is None:
                    continue
                with src:
                    _write(dest_dir, base, src)
                written.add(base)
    missing = sorted(set(allowed) - written)
    if missing:
        raise RuntimeError("Archive %s lacks expected files: %s" % (archive, missing))


def ensure(name, log=sys.stderr):
    """Make sure corpus `name` is present and verified; return {file: path}."""
    spec = CORPORA[name]
    os.makedirs(CORPUS_DIR, exist_ok=True)
    dest_dir = os.path.join(CORPUS_DIR, name)
    paths = dict((f, os.path.join(dest_dir, f)) for f in spec["files"])
    stamp = os.path.join(dest_dir, ".verified-" + spec["sha256"])
    if os.path.exists(stamp) and all(os.path.isfile(p) for p in paths.values()):
        return paths

    archive = os.path.join(CORPUS_DIR, spec["archive"])
    vendored = os.path.join(VENDOR_DIR, spec["archive"])
    if not os.path.isfile(archive) or _sha256(archive) != spec["sha256"]:
        if os.path.isfile(vendored):
            print("using vendored %s" % vendored, file=log)
            shutil.copyfile(vendored, archive)
        else:
            print("downloading %s ..." % spec["url"], file=log)
            _download(spec["url"], archive)
    digest = _sha256(archive)
    if digest != spec["sha256"]:
        os.remove(archive)
        raise RuntimeError("SHA256 mismatch for %s: got %s, expected %s"
                           % (spec["archive"], digest, spec["sha256"]))
    _extract(archive, dest_dir, spec["files"])
    with open(stamp, "w") as f:
        f.write(spec["sha256"] + "\n")
    return paths


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--quick", action="store_true", help="Canterbury only")
    args = ap.parse_args(argv)
    names = ["canterbury"] if args.quick else ["canterbury", "silesia"]
    for name in names:
        paths = ensure(name)
        print("%s: %d files OK in %s" % (name, len(paths), os.path.join(CORPUS_DIR, name)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
