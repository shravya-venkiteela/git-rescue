import shutil
import pytest
from bench.gitenv import GitRepo

_templates: dict[str, tuple] = {}


@pytest.fixture(scope="session")
def template(tmp_path_factory):
    """template(scenario) -> (root folder, labels). Built on first use."""
    def get(scenario):
        if scenario.id not in _templates:
            root = tmp_path_factory.mktemp(f"template-{scenario.id}")
            repo = GitRepo.init(root / "repo", root / "home")
            labels = scenario.module.build(repo)
            _templates[scenario.id] = (root, labels)
        return _templates[scenario.id]
    return get


@pytest.fixture
def built(template, tmp_path):
    """built(scenario) -> (repo, labels): a private copy of the broken state.

    The whole root is copied, not just repo/, because some scenarios keep a
    second repository beside it (accidental-pull-merge's ../upstream remote).
    """
    def make(scenario):
        root, labels = template(scenario)
        dest = tmp_path / "copy"
        shutil.copytree(root, dest, symlinks=True)
        return GitRepo(path=dest / "repo", home=dest / "home"), dict(labels)
    return make


@pytest.fixture(autouse=True)
def sealed_git_environment():
    """The CLI switches git to the person's own config and identity, through a
    module-level flag. A test that ran the CLI used to leave that flag set, and
    the next test's commits then used whatever config the machine had."""
    from src.git_rescue import gitenv

    gitenv.use_user_environment(False)
    yield
    gitenv.use_user_environment(False)
