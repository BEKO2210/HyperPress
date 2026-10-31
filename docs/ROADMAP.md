# HyperPress Roadmap

Living document. Read at the start of every session, reorder the compass, then work.
Every find goes in the same day with an acceptance criterion. Done items get a proof (commit, number).

## Kompass (current focus, in order)

1. **Integrity first** — no `assert` validation, only `HyperPressError`, bomb cap.
   *Acceptance:* bit-flip / truncation fuzz under `python -O` → 0 silent wrong outputs; 1 GiB bomb rejected without allocating it.
2. **Never worse than the best standard tool** — format v2 with WHOLE candidates ([SPEC-v2](SPEC-v2.md)).
   *Acceptance:* on every file of the fair benchmark `HP <= min(xz-9e raw, bz2-9, zstd-19) + 16 B`; CI enforces it.
3. **Honest fair benchmark** — real public corpus (Canterbury + Silesia, SHA256-pinned), brutto sizes, zstd as opponent.
   *Acceptance:* `python benchmarks/fair_bench.py` reproduces the README table byte-exact.
4. **Honest docs** — README, website, whitepaper only with numbers the benchmark proves; no "parallel racing" claim.
   *Acceptance:* every number in README/docs traceable to benchmark output.
5. `level="fast"` for speed. *Acceptance:* ≥ 10 MB/s on validusage.json (9.5 MB).

## Backlog

- [ ] Beat xz on large structured JSON/CSV by more than 1 % (column/field-aware transform). *Acceptance:* ≥ 3 % on Silesia `xml` / `nci`.
- [ ] Block path: block boundaries lose context (validusage.json 2.4× worse than xz in v1). Idea: preprocess per block, compress all blocks as one stream.
- [ ] Speed of pure-Python transforms (1–2 MB/s). *Acceptance:* ≥ 5 MB/s on best level.
- [ ] Python 3.14 `compression.zstd` in CI matrix.

## Done

- [x] 2026-10-30 Independent audit of v1: 55/55 own tests green, 400/400 fuzz roundtrips OK; fair benchmark: v1 loses to xz -9e by 20 % on real files (validusage.json +144 %), `python -O` returns silently wrong data on a corrupted stored block.
- [x] 2026-10-30 Prototype "whole-file candidates": never worse than best opponent on 8 real files, −0.9 % total.

## Genom (lessons — never deleted, only refined)

- **Never advertise numbers from self-generated data.** v1 claimed "+23 % vs LZMA" from synthetic repeats; one dataset (sensor) carried the whole lead, ties counted as wins, header overhead was subtracted ("netto"). On real files v1 was 20 % worse.
- **Compare against the strongest settings of the opponents** (xz -9e, zstd -19 --long, bz2), not weakened presets.
- **Independent blocks destroy context.** Splitting a 9.5 MB file into 128 KB blocks made it 2.4× bigger than plain xz.
- **A meta-compressor must include the best plain tools as candidates on the whole input**, otherwise it can lose to them.
- **`assert` is not validation.** `python -O` strips it; integrity checks must raise.
- **No compressor wins on all data** (counting argument). The honest promise: never worse than the best candidate + a few header bytes.
