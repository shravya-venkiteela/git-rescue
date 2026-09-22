"""Generate golden.json for a scenario: uv run python -m bench.make_golden <scenario-id> [--heldout]"""
import json
import sys
import tempfile
from pathlib import Path
from bench.gitenv import GitRepo
from bench.loader import HELDOUT_DIR, SCENARIOS_DIR, load

args = [a for a in sys.argv[1:] if not a.startswith("--")]
scenario_dir = (HELDOUT_DIR if "--heldout" in sys.argv else SCENARIOS_DIR) / args[0]
if not (scenario_dir / "scenario.yaml").exists():
    sys.exit(f"No scenario at {scenario_dir}. Create scenario.yaml and setup.py first.")

scenario = load(scenario_dir)
tmp = Path(tempfile.mkdtemp())
repo = GitRepo.init(tmp / "repo", tmp / "home")
labels = scenario.module.build(repo)
scenario.module.verify_broken(repo, labels)  # never record SHAs for a wrong scenario

out = scenario.dir / "golden.json"
out.write_text(json.dumps(labels, indent=2) + "\n", encoding="utf-8")
print(f"wrote {out}")