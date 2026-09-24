"""Turn run folders into a results table.

    uv run python -m bench.report results/tables/dev-set.md results/runs/<dir> [...]

Runs are grouped by system. Each system's passes are reported separately as
well as pooled: with 9 scenarios, one pass has swung by 2 recoveries with
nothing changed, so a single number hides more than it shows.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

LOSS_FREE = "practical_loss"


def read(run_dir: Path) -> list[dict]:
    rows = [json.loads(line) for line in (run_dir / "results.jsonl").read_text().splitlines() if line.strip()]
    for r in rows:
        r["run_dir"] = run_dir.name
    return rows


def tokens(row: dict) -> int:
    return 0  # per-run tokens live in the transcript, added below when present


def with_tokens(rows: list[dict], run_dir: Path) -> None:
    for r in rows:
        path = run_dir / "transcripts" / f"{r['scenario']}__{r['system']}__{r['repeat']}.json"
        if not path.exists():
            continue
        events = json.loads(path.read_text())
        r["tokens"] = sum(e.get("tokens", 0) for e in events if e.get("type") == "model_reply")


def pass_key(row: dict) -> tuple[str, int]:
    """A pass is one sweep over the scenarios: a run folder plus its repeat."""
    return (row["run_dir"], row["repeat"])


def table(rows: list[dict]) -> str:
    systems = sorted({r["system"] for r in rows})
    scenarios = sorted({r["scenario"] for r in rows})
    out = ["| system | runs | recovered | data loss | unparsed replies | tokens/run |",
           "|---|---|---|---|---|---|"]
    for name in systems:
        rs = [r for r in rows if r["system"] == name]
        by_pass = defaultdict(list)
        for r in rs:
            by_pass[pass_key(r)].append(r)
        per_pass = [sum(x["recovered"] for x in p) for p in by_pass.values()]
        spread = f" ({', '.join(str(n) for n in per_pass)} per pass)" if len(per_pass) > 1 else ""
        loss = sum(r[LOSS_FREE] > 0 for r in rs)
        unparsed = sum(r["category"] == "unparsable_output" for r in rs)
        tok = [r.get("tokens", 0) for r in rs if r.get("tokens")]
        avg = f"{sum(tok) // len(tok):,}" if tok else "n/a"
        out.append(f"| {name} | {len(rs)} | {sum(r['recovered'] for r in rs)}/{len(rs)}"
                   f" ({100 * sum(r['recovered'] for r in rs) // len(rs)}%){spread}"
                   f" | {loss}/{len(rs)} | {unparsed}/{len(rs)} | {avg} |")

    out += ["", "Recovered per scenario (one column per system):", "",
            "| scenario | " + " | ".join(systems) + " |", "|---" * (len(systems) + 1) + "|"]
    for scenario in scenarios:
        cells = []
        for name in systems:
            rs = [r for r in rows if r["system"] == name and r["scenario"] == scenario]
            cells.append(f"{sum(r['recovered'] for r in rs)}/{len(rs)}" if rs else "-")
        out.append(f"| {scenario} | " + " | ".join(cells) + " |")

    out += ["", "Why runs ended:", ""]
    for name in systems:
        counts = Counter(r["category"] for r in rows if r["system"] == name)
        out.append(f"- **{name}**: " + ", ".join(f"{k}={v}" for k, v in counts.most_common()))

    losses = [r for r in rows if r[LOSS_FREE] > 0]
    if losses:
        out += ["", "Runs that lost data:", ""]
        for r in losses:
            out.append(f"- **{r['system']}** on `{r['scenario']}` (pass {r['repeat'] + 1}): "
                       f"{r[LOSS_FREE]} item(s) unreachable afterwards; ended as `{r['category']}`.")
    return "\n".join(out)


def main(argv: list[str]) -> None:
    if len(argv) < 2:
        sys.exit(__doc__)
    out_path, run_dirs = Path(argv[0]), [Path(p) for p in argv[1:]]
    rows: list[dict] = []
    for d in run_dirs:
        batch = read(d)
        with_tokens(batch, d)
        rows += batch
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(table(rows) + "\n", encoding="utf-8")
    print(f"wrote {out_path} from {len(rows)} runs")


if __name__ == "__main__":
    main(sys.argv[1:])
