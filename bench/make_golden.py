"""Generate golden.json for a scenario: uv run python -m bench.make_golden <scenario-id>"""
import json
import sys
import tempfile
from pathlib import Path
from bench.gitenv import GitRepo
from bench.loader import SCENARIOS_DIR, load

scenario_dir = SCENARIOS_DIR / sys.argv[1]
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