"""The results table is what the write-up quotes, so it is tested like code."""
import json

from bench.report import main, table


def row(system, scenario, repeat, recovered, loss=0, category="recovered", run="runA"):
    return {"system": system, "scenario": scenario, "repeat": repeat, "recovered": recovered,
            "practical_loss": loss, "category": category, "run_dir": run}


def test_each_pass_is_reported_not_just_the_total():
    """One pass of 9 has swung by 2 with nothing changed; a single number hides that."""
    rows = [row("agent", f"s{i}", 0, True) for i in range(3)]
    rows += [row("agent", f"s{i}", 1, i == 0) for i in range(3)]
    out = table(rows)
    assert "4/6 (66%) (3, 1 per pass)" in out


def test_a_run_that_lost_data_is_named():
    rows = [row("shell", "rebase-01", 0, False, loss=2, category="command_failed")]
    out = table(rows)
    assert "Runs that lost data" in out and "`rebase-01` (pass 1)" in out and "2 item(s)" in out


def test_no_loss_section_when_nothing_was_lost():
    assert "Runs that lost data" not in table([row("agent", "s1", 0, True)])


def test_writes_a_file_from_run_folders(tmp_path):
    run = tmp_path / "run"; (run / "transcripts").mkdir(parents=True)
    (run / "results.jsonl").write_text("\n".join(json.dumps(r) for r in [
        {"system": "agent", "scenario": "s1", "repeat": 0, "recovered": True,
         "practical_loss": 0, "category": "recovered"}]))
    (run / "transcripts" / "s1__agent__0.json").write_text(json.dumps(
        [{"type": "model_reply", "tokens": 1200}, {"type": "model_reply", "tokens": 800}]))
    out = tmp_path / "table.md"
    main([str(out), str(run)])
    text = out.read_text()
    assert "1/1 (100%)" in text and "2,000" in text
