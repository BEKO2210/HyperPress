"""Fair benchmark: HyperPress v2 vs the strongest settings of standard tools.

All sizes are brutto: every byte of every output counts, HPRX header included.
Corpora: Canterbury + Silesia, SHA256-pinned (see corpus.py).

Opponents
  xz-9e      lzma.compress, .xz container, preset 9|EXTREME
  xz-raw-9e  lzma raw LZMA2, preset 9|EXTREME (no container)
  bz2-9      bz2.compress level 9
  zlib-9     zlib.compress level 9 (zlib container)
  zstd-19    stdlib compression.zstd level 19 if importable (Python >= 3.14),
             else `zstd -19 --ultra --long=27` CLI if on PATH, else skipped

--check fails (exit 1) if any file violates
  HP_best <= min(stdlib opponents) + 16
where "stdlib opponents" are all of the above except a CLI zstd.

    python benchmarks/fair_bench.py [--quick] [--check] [--output results.json]
"""

import argparse
import bz2
import json
import lzma
import os
import platform
import shutil
import subprocess
import sys
import time
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))
sys.path.insert(0, HERE)

import corpus  # noqa: E402
import hyperpress  # noqa: E402
from hyperpress import compress, decompress  # noqa: E402

HEADER_MAX = 16

try:
    from compression import zstd as _zstd  # Python >= 3.14
except ImportError:
    _zstd = None

ZSTD_CLI = shutil.which("zstd") if _zstd is None else None
ZSTD_CLI_ARGS = ["-19", "--ultra", "--long=27", "-q", "-c"]


def _xz_9e(d):
    return lzma.compress(d, format=lzma.FORMAT_XZ, preset=9 | lzma.PRESET_EXTREME)


def _xz_raw_9e(d):
    return lzma.compress(d, format=lzma.FORMAT_RAW,
                         filters=[{"id": lzma.FILTER_LZMA2,
                                   "preset": 9 | lzma.PRESET_EXTREME}])


def _zstd_cli(d):
    return subprocess.run([ZSTD_CLI] + ZSTD_CLI_ARGS, input=d,
                          stdout=subprocess.PIPE, check=True).stdout


# (name, function, counts for --check)
OPPONENTS = [
    ("xz-9e", _xz_9e, True),
    ("xz-raw-9e", _xz_raw_9e, True),
    ("bz2-9", lambda d: bz2.compress(d, 9), True),
    ("zlib-9", lambda d: zlib.compress(d, 9), True),
]
if _zstd is not None:
    OPPONENTS.append(("zstd-19", lambda d: _zstd.compress(d, level=19), True))
    ZSTD_SOURCE = "stdlib compression.zstd level 19"
elif ZSTD_CLI:
    OPPONENTS.append(("zstd-19", _zstd_cli, False))
    ZSTD_SOURCE = "CLI: zstd " + " ".join(ZSTD_CLI_ARGS[:3])
else:
    ZSTD_SOURCE = "skipped (no compression.zstd, no zstd CLI)"


def _timed(fn, arg):
    t0 = time.perf_counter()
    out = fn(arg)
    return out, time.perf_counter() - t0


def _mbs(nbytes, seconds):
    return round(nbytes / 1e6 / seconds, 3) if seconds > 0 else None


def bench_file(name, data, log):
    row = {"file": name, "size": len(data), "opponents": {}}
    for oname, fn, _ in OPPONENTS:
        out, dt = _timed(fn, data)
        row["opponents"][oname] = {"size": len(out), "comp_mbs": _mbs(len(data), dt)}
    for level in ("best", "fast"):
        out, ct = _timed(lambda d: compress(d, level=level), data)
        back, dt = _timed(decompress, out)
        if back != data:
            raise SystemExit("ROUNDTRIP FAILED: %s level=%s" % (name, level))
        row["hp_" + level] = {"size": len(out), "method_byte": out[6] if len(out) > 6 else None,
                              "comp_mbs": _mbs(len(data), ct),
                              "decomp_mbs": _mbs(len(data), dt), "roundtrip": True}
    checked = [(o, row["opponents"][o]["size"]) for o, _, c in OPPONENTS if c]
    best_name, best_size = min(checked, key=lambda x: x[1])
    row["best_stdlib_opponent"] = {"name": best_name, "size": best_size}
    row["delta_vs_best"] = row["hp_best"]["size"] - best_size
    row["violation"] = row["delta_vs_best"] > HEADER_MAX
    print("  %-14s %10d B  hp_best=%d (%+d vs %s)  %.2f MB/s" % (
        name, len(data), row["hp_best"]["size"], row["delta_vs_best"], best_name,
        row["hp_best"]["comp_mbs"] or 0), file=log, flush=True)
    return row


def _pct(new, ref):
    return "%+.2f %%" % ((new - ref) * 100.0 / ref) if ref else "n/a"


def render(rows, totals):
    onames = [o for o, _, _ in OPPONENTS]
    head = ["file", "original"] + onames + ["HP best", "HP fast", "HP best vs best stdlib",
                                           "best MB/s c/d", "fast MB/s c/d"]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]

    def line(r, label):
        cells = [label, str(r["size"])]
        cells += [str(r["opponents"][o]["size"]) for o in onames]
        cells += [str(r["hp_best"]["size"]), str(r["hp_fast"]["size"])]
        cells.append("%+d B (%s)" % (r["delta_vs_best"], r["best_stdlib_opponent"]["name"]))
        for lv in ("hp_best", "hp_fast"):
            cells.append("%.2f / %.2f" % (r[lv]["comp_mbs"] or 0, r[lv]["decomp_mbs"] or 0))
        return "| " + " | ".join(cells) + " |"

    for r in rows:
        lines.append(line(r, r["corpus"] + "/" + r["file"]))
    lines.append(line(totals, "**TOTAL**"))
    t = totals
    lines.append("")
    lines.append("Totals: HP best %d B vs sum of per-file best stdlib opponent %d B (%s); "
                 "vs xz-9e %s; vs xz-raw-9e %s." % (
                     t["hp_best"]["size"], t["sum_best_stdlib"],
                     _pct(t["hp_best"]["size"], t["sum_best_stdlib"]),
                     _pct(t["hp_best"]["size"], t["opponents"]["xz-9e"]["size"]),
                     _pct(t["hp_best"]["size"], t["opponents"]["xz-raw-9e"]["size"])))
    if "zstd-19" in t["opponents"]:
        lines.append("HP best vs zstd-19 (%s): %s." % (
            ZSTD_SOURCE, _pct(t["hp_best"]["size"], t["opponents"]["zstd-19"]["size"])))
    else:
        lines.append("zstd-19: %s." % ZSTD_SOURCE)
    return "\n".join(lines)


def totals_of(rows):
    total_size = sum(r["size"] for r in rows)
    t = {"size": total_size, "opponents": {}}
    for o, _, _ in OPPONENTS:
        osz = sum(r["opponents"][o]["size"] for r in rows)
        t["opponents"][o] = {"size": osz}
    for lv in ("hp_best", "hp_fast"):
        # Throughput totals = total bytes / total time (recomputed from per-file rates).
        ct = sum(r["size"] / 1e6 / r[lv]["comp_mbs"] for r in rows if r[lv]["comp_mbs"])
        dt = sum(r["size"] / 1e6 / r[lv]["decomp_mbs"] for r in rows if r[lv]["decomp_mbs"])
        t[lv] = {"size": sum(r[lv]["size"] for r in rows),
                 "comp_mbs": _mbs(total_size, ct), "decomp_mbs": _mbs(total_size, dt)}
    t["sum_best_stdlib"] = sum(r["best_stdlib_opponent"]["size"] for r in rows)
    t["delta_vs_best"] = t["hp_best"]["size"] - t["sum_best_stdlib"]
    t["best_stdlib_opponent"] = {"name": "per-file min", "size": t["sum_best_stdlib"]}
    return t


def main(argv=None):
    ap = argparse.ArgumentParser(description="HyperPress fair benchmark")
    ap.add_argument("--quick", action="store_true", help="Canterbury only")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if HP_best > min(stdlib opponents) + %d B on any file" % HEADER_MAX)
    ap.add_argument("--output", default=os.path.join(HERE, "results.json"))
    args = ap.parse_args(argv)

    names = ["canterbury"] if args.quick else ["canterbury", "silesia"]
    log = sys.stderr
    print("zstd-19: %s" % ZSTD_SOURCE, file=log)
    rows = []
    for cname in names:
        paths = corpus.ensure(cname, log=log)
        print("[%s]" % cname, file=log)
        for fname in corpus.CORPORA[cname]["files"]:
            with open(paths[fname], "rb") as f:
                data = f.read()
            row = bench_file(fname, data, log)
            row["corpus"] = cname
            rows.append(row)

    totals = totals_of(rows)
    violations = [r for r in rows if r["violation"]]
    result = {
        "mode": "quick" if args.quick else "full",
        "corpora": dict((n, corpus.CORPORA[n]["sha256"]) for n in names),
        "header_max": HEADER_MAX,
        "env": {"python": platform.python_version(), "platform": platform.platform(),
                "hyperpress": hyperpress.__version__, "zstd": ZSTD_SOURCE},
        "files": rows,
        "totals": totals,
        "violations": [r["corpus"] + "/" + r["file"] for r in violations],
    }
    with open(args.output, "w") as f:
        json.dump(result, f, indent=2, sort_keys=True)
        f.write("\n")

    print(render(rows, totals))
    print("results written to %s" % args.output)
    if violations:
        for r in violations:
            print("VIOLATION: %s/%s hp_best=%d > %s=%d + %d" % (
                r["corpus"], r["file"], r["hp_best"]["size"],
                r["best_stdlib_opponent"]["name"], r["best_stdlib_opponent"]["size"], HEADER_MAX))
    else:
        print("check: 0 violations (HP_best <= min(stdlib opponents) + %d B on all %d files)"
              % (HEADER_MAX, len(rows)))
    if args.check and violations:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
