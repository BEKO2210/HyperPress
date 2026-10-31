#!/usr/bin/env python3
"""Fill the <!-- BENCH:START/END --> blocks in README and docs from results.json.

Usage: python benchmarks/fill_docs.py [benchmarks/results.json]
Every number in the docs tables comes from this file, nothing is typed by hand.
"""

import html
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLOCK = re.compile(r"(<!-- BENCH:START -->)(.*?)(<!-- BENCH:END -->)", re.S)


def pct(a, b):
    return (a - b) / b * 100.0


def rows(res):
    out = []
    for f in res["files"]:
        best = f["best_stdlib_opponent"]
        xz = f["opponents"]["xz-9e"]["size"]
        z = f["opponents"].get("zstd-19", {}).get("size")
        out.append((f["corpus"], f["file"], f["size"], f["hp_best"]["size"],
                    best["name"], best["size"], xz, z))
    return out


def markdown(res):
    t = res["totals"]
    lines = [
        "| Corpus | File | Original | HyperPress | Best stdlib opponent | vs best | vs xz -9e | vs zstd -19 |",
        "|---|---|---:|---:|---|---:|---:|---:|",
    ]
    for corpus, name, size, hp, bname, bsize, xz, z in rows(res):
        zs = "%+.1f %%" % pct(hp, z) if z else "n/a"
        lines.append("| %s | %s | %s | %s | %s %s | %+d B (%+.2f %%) | %+.1f %% | %s |" % (
            corpus, name, format(size, ","), format(hp, ","), bname, format(bsize, ","),
            hp - bsize, pct(hp, bsize), pct(hp, xz), zs))
    hp = t["hp_best"]["size"]
    lines.append("| **Total** | %d files | **%s** | **%s** | per-file best %s | **%+.2f %%** | **%+.2f %%** | **%+.2f %%** |" % (
        len(res["files"]), format(t["size"], ","), format(hp, ","), format(t["sum_best_stdlib"], ","),
        pct(hp, t["sum_best_stdlib"]), pct(hp, t["opponents"]["xz-9e"]["size"]),
        pct(hp, t["opponents"]["zstd-19"]["size"])))
    env = res["env"]
    lines += [
        "",
        "Sizes are full HPRX containers (header included). Speed on this run: `best` compresses at "
        "%.2f MB/s and `fast` at %.2f MB/s; decompression runs at about %.0f MB/s. "
        "Python %s, zstd opponent: %s, %d violations of the guarantee. "
        "Reproduce with `python benchmarks/fair_bench.py`." % (
            t["hp_best"]["comp_mbs"], t["hp_fast"]["comp_mbs"], t["hp_best"]["decomp_mbs"],
            env["python"], env["zstd"], len(res["violations"])),
    ]
    return "\n" + "\n".join(lines) + "\n"


def html_table(res, cls):
    t = res["totals"]
    e = html.escape
    out = ['<table%s>' % (' class="%s"' % cls if cls else ""),
           "<thead><tr><th>File</th><th>Original</th><th>HyperPress</th><th>Best stdlib opponent</th>"
           "<th>vs best</th><th>vs xz -9e</th></tr></thead><tbody>"]
    for corpus, name, size, hp, bname, bsize, xz, z in rows(res):
        out.append("<tr><td>%s/%s</td><td>%s</td><td>%s</td><td>%s %s</td><td>%+.2f&nbsp;%%</td><td>%+.1f&nbsp;%%</td></tr>" % (
            e(corpus), e(name), format(size, ","), format(hp, ","), e(bname), format(bsize, ","),
            pct(hp, bsize), pct(hp, xz)))
    hp = t["hp_best"]["size"]
    out.append("<tr><td><strong>Total (%d files)</strong></td><td>%s</td><td><strong>%s</strong></td><td>%s</td>"
               "<td><strong>%+.2f&nbsp;%%</strong></td><td><strong>%+.2f&nbsp;%%</strong></td></tr>" % (
                   len(res["files"]), format(t["size"], ","), format(hp, ","), format(t["sum_best_stdlib"], ","),
                   pct(hp, t["sum_best_stdlib"]), pct(hp, t["opponents"]["xz-9e"]["size"])))
    out.append("</tbody></table>")
    out.append("<p>Header included. Compression speed: best %.2f MB/s, fast %.2f MB/s. "
               "Total vs zstd -19 --long=27: %+.2f&nbsp;%%. Python %s. Reproduce with "
               "<code>python benchmarks/fair_bench.py</code>.</p>" % (
                   t["hp_best"]["comp_mbs"], t["hp_fast"]["comp_mbs"],
                   pct(hp, t["opponents"]["zstd-19"]["size"]), e(res["env"]["python"])))
    return "\n" + "\n".join(out) + "\n"


def fill(path, body):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    new, n = BLOCK.subn(lambda m: m.group(1) + body + m.group(3), text)
    if n != 1:
        raise SystemExit("%s: expected one BENCH block, found %d" % (path, n))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(new)


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "benchmarks", "results.json")
    with open(src, encoding="utf-8") as fh:
        res = json.load(fh)
    fill(os.path.join(ROOT, "README.md"), markdown(res))
    fill(os.path.join(ROOT, "docs", "index.html"), html_table(res, "bench-table"))
    fill(os.path.join(ROOT, "docs", "whitepaper.html"), html_table(res, "data-table"))


if __name__ == "__main__":
    main()
