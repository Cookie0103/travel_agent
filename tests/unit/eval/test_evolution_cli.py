"""正式入口走真实候选生成和闸门，回放输入为本地可控的成对记录。"""

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from backend.tools.skill_config import SkillConfig
from eval.evolve import cli
from eval.evolve.codex import Proposal


def trial(case_id: str, *, target: bool = False) -> cli.Row:
    return {
        "case_id": case_id,
        "repeat": 1,
        "trial": 1,
        "commerce": {"violations": [], "groups": []},
        "checks": [{"id": "draft", "tier": "hard", "outcome": "fail"}] if target else [],
        "rule_gate": {"passed": not target, "violations": []},
        "skills": [],
    }


def write_run(path: Path, rows: Sequence[cli.Row], skills: SkillConfig | None = None) -> Path:
    path.mkdir(parents=True)
    manifest = {
        "cases": [row["case_id"] for row in rows],
        "case_suite": "p2v2",
        "case_split": "reflection" if rows[0]["case_id"].startswith("reflect") else "validation",
        "repeat": 1,
        "profile": "human",
        "live": False,
        "cases_sha256": "fixed-test",
        "skills": {"versions": (skills or SkillConfig()).versions()},
    }
    (path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (path / "trials.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    return path


@pytest.fixture
def split(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def identity(name: str, *, archived_v1: bool = False) -> tuple[frozenset[str], str]:
        selected = {
            "reflection": ["reflect-a", "reflect-b"],
            "validation": ["validation-a", "validation-b", "validation-c", "validation-d"],
        }
        return frozenset(selected[name]), "legacy-test" if archived_v1 else "fixed-test"

    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "split_identity", identity)
    monkeypatch.setattr("eval.evolve.round.split_identity", identity)


def test_first_reuses_existing_pairs_with_matching_candidate_hash(
    split: None, tmp_path: Path
) -> None:
    baseline = write_run(tmp_path / "baseline", [trial("reflect-a")])
    staged = tmp_path / "staged"
    staged.mkdir()
    (staged / "hotel-comparison.md").write_text("候选句。", encoding="utf-8")
    candidate = write_run(
        tmp_path / "evaluated", [trial("reflect-a")], SkillConfig(directory=staged)
    )
    proposal = tmp_path / "proposal.json"
    proposal.write_text(
        Proposal(
            skill="hotel-comparison",
            markdown="候选句。",
            trigger="比较酒店",
            self_assessment="测试提案",
        ).model_dump_json(),
        encoding="utf-8",
    )
    output = tmp_path / ".cache" / "first"
    arguments = [
        "first",
        "--baseline",
        str(baseline),
        "--candidate-run",
        str(candidate),
        "--proposal",
        str(proposal),
        "--output",
        str(output),
    ]
    assert cli.main(arguments) == 0
    assert (output / "review.md").is_file()
    assert (output / "candidate/hotel-comparison.md").read_text(encoding="utf-8") == "候选句。"
    proposal.write_text(proposal.read_text(encoding="utf-8").replace("候选句", "不同句"), "utf-8")
    with pytest.raises(SystemExit) as caught:
        cli.main([*arguments[:-1], str(output.with_name("bad-hash"))])
    assert caught.value.code == 2


def test_guarded_runs_same_cases_offline_and_stages_review(
    split: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    starting = tmp_path / "starting"
    starting.mkdir()
    (starting / "hotel-comparison.md").write_text("旧句。\n", encoding="utf-8")
    skills = SkillConfig(directory=starting)
    reflection = write_run(
        tmp_path / "reflection",
        [trial("reflect-a", target=True), trial("reflect-b", target=True)],
        skills,
    )
    cases = [f"validation-{suffix}" for suffix in "abcd"]
    baseline = write_run(
        tmp_path / "validation",
        [trial(case, target=index < 2) for index, case in enumerate(cases)],
        skills,
    )
    edit = tmp_path / "edit.json"
    edit.write_text(
        json.dumps({"skill": "hotel-comparison", "old": "旧句。", "new": "新句。"}),
        encoding="utf-8",
    )
    output = tmp_path / ".cache" / "guarded"

    def offline(args: list[str], *, run_parent: Path) -> int:
        assert "--live" not in args and "--local-model" not in args
        assert args[:4] == ["--split", "validation", "--repeat", "1"]
        assert [
            args[index + 1] for index, value in enumerate(args) if value == "--case-id"
        ] == cases
        directory = Path(args[args.index("--candidate-skills") + 1])
        assert (directory / "hotel-comparison.md").read_text(encoding="utf-8") == "新句。\n"
        write_run(
            run_parent / "offline-run",
            [trial(case) for case in cases],
            SkillConfig(directory=directory),
        )
        return 0

    monkeypatch.setattr("eval.v3.run.main", offline)
    assert (
        cli.main(
            [
                "guarded",
                "--reflection-run",
                str(reflection),
                "--baseline",
                str(baseline),
                "--edit",
                str(edit),
                "--skills",
                str(starting),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    (review,) = output.glob("*/skill-*/review.md")
    assert "目标违规从 2 道变为 0 道" in review.read_text(encoding="utf-8")
    assert (review.parent / "pairs.json").is_file()
    assert (starting / "hotel-comparison.md").read_text(encoding="utf-8") == "旧句。\n"


def test_outside_cohort_is_rejected_before_trial_rows_are_opened(
    split: None, tmp_path: Path
) -> None:
    (tmp_path / "manifest.json").write_text(
        json.dumps({"cases": ["reflect-a", "validation-a"], "repeat": 1}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="所选反思或验证组"):
        cli.evidence(tmp_path, "reflection")


def test_reflection_rejects_transcript_for_a_different_case(split: None, tmp_path: Path) -> None:
    row = {**trial("reflect-a"), "transcript_path": "transcripts/unrelated-1.txt"}
    source = write_run(tmp_path / "reflection", [row])
    with pytest.raises(ValueError, match="同题同重复"):
        cli.transcripts(cli.evidence(source, "reflection"))


def test_archived_v1_records_require_explicit_archive_selection(
    split: None, tmp_path: Path
) -> None:
    runs = write_run(tmp_path / "old", [trial("reflect-a")])
    manifest = runs / "manifest.json"
    table = json.loads(manifest.read_text(encoding="utf-8"))
    table["cases_sha256"] = "legacy-test"
    table.pop("case_suite")
    table.pop("case_split")
    manifest.write_text(json.dumps(table), encoding="utf-8")
    with pytest.raises(ValueError, match="题库版本或分区不符"):
        cli.evidence(runs, "reflection")
    assert set(cli.evidence(runs, "reflection", archived_v1=True).rows) == {("reflect-a", 1)}
