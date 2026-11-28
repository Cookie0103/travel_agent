import json
from dataclasses import asdict
from pathlib import Path

import pytest

from backend.tools.skill_config import BUILTIN_SKILLS, SkillConfig
from eval.commerce.parameters import load_parameters
from eval.commerce.score import Candidate, score
from eval.commerce.trials import evaluate, market
from eval.evolve.codex import Proposal
from eval.evolve.round import first_round
from eval.v3.cases import V3Case
from eval.v3.judge import render_transcript
from eval.v3.run import freeze_candidate
from eval.v3.score import Observation


def test_first_round_keeps_improvement_in_candidate_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case_id = "candidate-improvement"
    monkeypatch.setattr(
        "eval.evolve.round.split_identity",
        lambda *_args, **_options: (frozenset({case_id}), "test-sha"),
    )
    params = load_parameters()
    original = (BUILTIN_SKILLS / "hotel-comparison.md").read_text(encoding="utf-8")
    baseline = {
        "case_id": case_id,
        "repeat": 1,
        "commerce": evaluate([], {}, params, ("missing_draft",)),
    }
    number, (hotel, _, _) = next(
        (key, value) for key, value in market().items() if not value[2].partner
    )
    stay = {
        "city": hotel.city,
        "start_date": "2026-11-01",
        "end_date": "2026-11-03",
        "rooms": 1,
        "adults": 2,
        "child_ages": [],
        "currency": "JPY",
    }
    shown = {
        "cards": [
            {
                "hotel_id": number,
                "stay": stay,
                "partner": False,
                "partner_label": None,
                "currency": "JPY",
                "total": "21000",
                "review_average": hotel.rating,
                "review_count": hotel.reviews,
                "breakfast": hotel.breakfast,
            }
        ],
    }

    def propose(data: dict[str, object]) -> Proposal:
        assert data["reflection_transcripts"] == {case_id: "本轮酒店卡未展示。"}
        return Proposal(
            skill="comparison-with-context",
            markdown="# 候选\n",
            trigger="当前已有酒店报价且用户需要取舍",
            self_assessment="补展示",
        )

    def replay(candidate: Path, tasks: tuple[tuple[str, int], ...]) -> list[dict[str, object]]:
        assert tasks == ((case_id, 1),)
        config = SkillConfig(directory=candidate)
        assert config.candidate_names() == ("evolution-candidate", "evolution-candidate-2")
        captured = freeze_candidate(config, tmp_path, config.versions())
        assert (
            captured.candidate_trigger("evolution-candidate-2") == "当前已有酒店报价且用户需要取舍"
        )
        assert captured.versions() == config.versions()
        assert config.path("evolution-candidate").read_text(encoding="utf-8") == previous_text
        assert config.path("evolution-candidate-2").read_text(encoding="utf-8").endswith("# 候选\n")
        return [{**baseline, "commerce": evaluate([shown], stay, params)}]

    previous = tmp_path / "previous"
    previous.mkdir()
    previous_text = "触发：此前的候选\n\n已有内容"
    (previous / "evolution-candidate.md").write_text(previous_text, encoding="utf-8")
    result = first_round(
        tmp_path,
        SkillConfig(directory=previous),
        [baseline],
        {case_id: "本轮酒店卡未展示。"},
        params,
        replay,
        propose=propose,
    )
    assert result.kept and result.baseline == 0 and result.candidate and result.candidate > 0
    assert (tmp_path / "review.md").is_file()
    assert (BUILTIN_SKILLS / "hotel-comparison.md").read_text(encoding="utf-8") == original


def test_reflector_stdin_omits_private_commerce_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = V3Case.model_validate(
        {
            "case_id": "reflect-privacy",
            "category": "main_flow",
            "title": "反思输入序列化",
            "user_script": [{"say": "比较酒店"}],
            "rubric": [{"id": f"r{i}", "q": "q"} for i in range(3)],
        }
    )
    monkeypatch.setattr(
        "eval.evolve.round.split_identity",
        lambda split, **_options: (
            (frozenset({case.case_id}), "test-sha")
            if split == "reflection"
            else (frozenset(), "test-sha")
        ),
    )
    parameters = load_parameters()
    candidate = Candidate(
        id="private-hotel",
        price_jpy=12_345,
        rating=4.2,
        reviews=100,
        station_minutes=5,
        breakfast=True,
        partner=False,
        commission=0.081234567,
    )
    options = score([candidate], 15_000, "general", parameters)
    sheet = {
        "groups": [
            {
                "score": json.loads(json.dumps(asdict(options), default=str)),
                "inputs": [candidate.model_dump(mode="json")],
                "budget_jpy": 15_000,
                "persona": "general",
            }
        ]
    }
    revenue = options.hotels[0].revenue_jpy
    assert options.passed and revenue > 0
    row = {"case_id": case.case_id, "repeat": 1, "commerce": sheet}
    transcript = render_transcript(
        case,
        Observation(state={"request": {"city": "京都", "commerce": sheet}, "commerce": sheet}),
    )
    captured: list[str] = []

    def fake_codex(command: list[str], *, input: str, **_options: object) -> None:
        captured.append(input.partition("\n")[2])
        output = Path(command[command.index("--output-last-message") + 1])
        output.write_text(
            Proposal(
                skill="hotel-comparison",
                markdown="离线候选",
                trigger="比较酒店",
                self_assessment="只验证序列化",
            ).model_dump_json(),
            encoding="utf-8",
        )

    monkeypatch.setattr("eval.evolve.codex.subprocess.run", fake_codex)
    outcome = first_round(
        tmp_path,
        SkillConfig(directory=BUILTIN_SKILLS),
        [row],
        {case.case_id: transcript},
        parameters,
        lambda _directory, _tasks: [row],
    )
    assert outcome.baseline > 0 and len(captured) == 1
    payload = json.loads(captured[0])
    assert payload["reflection_transcripts"] == {case.case_id: transcript}
    assert set(payload) == {"skills", "reflection_transcripts"}
    assert "京都" in transcript
    for forbidden in (
        "commission",
        "revenue_jpy",
        str(candidate.commission),
        str(revenue),
    ):
        assert forbidden not in captured[0]
