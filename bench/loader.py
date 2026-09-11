from __future__ import annotations
import importlib.util
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
import yaml

SCENARIOS_DIR = Path(__file__).parent / "scenarios"
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
        raise ValueError(f"{scenario_dir.name}: id '{spec['id']}' must match the folder name")

    #Folder names contain hyphens, so they can't be imported normally.
    module_name = "scenario_" + scenario_dir.name.replace("-", "_")
    import_spec = importlib.util.spec_from_file_location(module_name, scenario_dir / "setup.py")
    module = importlib.util.module_from_spec(import_spec)
    import_spec.loader.exec_module(module)

    for fn in ("build", "verify_broken"):
        if not callable(getattr(module, fn, None)):
            raise ValueError(f"{scenario_dir.name}: setup.py must define {fn}()")

    return Scenario(id=spec["id"], dir=scenario_dir, spec=spec, module=module)


def load_all() -> list[Scenario]:
    return [
        load(d)
        for d in sorted(SCENARIOS_DIR.iterdir())
        if d.is_dir() and (d / "scenario.yaml").exists()
    ]