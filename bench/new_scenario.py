"""Create a scenario skeleton: uv run python -m bench.new_scenario <scenario-id> <category>"""
import sys
from bench.loader import SCENARIOS_DIR

scenario_id, category = sys.argv[1], sys.argv[2]
folder = SCENARIOS_DIR / scenario_id
if folder.exists():
    sys.exit(f"{folder} already exists; refusing to overwrite it.")
folder.mkdir()

(folder / "scenario.yaml").write_text(f"""id: {scenario_id}
source: TODO
category: {category}
recoverable: true
user_message: >
  TODO
hidden_intent: >
  TODO
clarifications: {{}}
assertions: []
""", encoding="utf-8")

(folder / "setup.py").write_text(f'''from bench.gitenv import GitRepo


def verify_broken(repo: GitRepo, labels: dict[str, str]) -> None:
    
    raise NotImplementedError


def build(repo: GitRepo) -> dict[str, str]:
    raise NotImplementedError
''', encoding="utf-8")
print(f"created {folder}")