from __future__ import annotations
import importlib.util
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
import yaml

SCENARIOS_DIR = Path(__file__).parent / "scenarios"
#The final test set. Normal runs never load it: a scenario the agent has been
#developed against measures the development, not the agent.
HELDOUT_DIR = Path(__file__).parent / "heldout"
REQUIRED_KEYS = {"id", "category", "recoverable", "user_message", "hidden_intent", "assertions"}


@dataclass
class Scenario:
    id: str
    dir: Path
    spec: dict
    module: ModuleType  #the scenario's setup.py


def load(scenario_dir: Path) -> Scenario:
    spec = yaml.safe_load((scenario_dir / "scenario.yaml").read_text(encoding="utf-8"))

    missing = REQUIRED_KEYS - spec.keys()
    if missing:
        raise ValueError(f"{scenario_dir.name}: scenario.yaml is missing {sorted(missing)}")
    if spec["id"] != scenario_dir.name:
        raise ValueError(f"{scenario_dir.name}: scenario.yaml has id '{spec['id']}'; it belongs in that folder")

    #Folder names contain hyphens, so they can't be imported normally.
    module_name = "scenario_" + scenario_dir.name.replace("-", "_")
    import_spec = importlib.util.spec_from_file_location(module_name, scenario_dir / "setup.py")
    module = importlib.util.module_from_spec(import_spec)
    import_spec.loader.exec_module(module)

    #Same check for setup.py: a file pasted into the wrong folder fails here,
    #with a message naming where it belongs, instead of as confusing test failures.
    declared = getattr(module, "SCENARIO_ID", None)
    if declared != scenario_dir.name:
        raise ValueError(f"{scenario_dir.name}: setup.py has SCENARIO_ID {declared!r}; it belongs in that folder")

    for fn in ("build", "verify_broken"):
        if not callable(getattr(module, fn, None)):
            raise ValueError(f"{scenario_dir.name}: setup.py must define {fn}()")

    return Scenario(id=spec["id"], dir=scenario_dir, spec=spec, module=module)


def load_all(root: Path = SCENARIOS_DIR) -> list[Scenario]:
    if not root.is_dir():
        return []
    return [
        load(d)
        for d in sorted(root.iterdir())
        if d.is_dir() and (d / "scenario.yaml").exists()
    ]