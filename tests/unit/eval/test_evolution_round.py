from pathlib import Path

from backend.tools.skill_config import BUILTIN_SKILLS, SkillConfig
from eval.commerce.parameters import load_parameters
from eval.commerce.trials import evaluate, market
from eval.evolve.codex import Proposal
from eval.evolve.round import first_round
from eval.v3.phase2_split import frozen_cases
from eval.v3.run import freeze_candidate


def test_first_round_keeps_improvement_in_candidate_only(tmp_path: Path) -> None:
    case = frozen_cases("reflection")[0]
    params = load_parameters()
    original = (BUILTIN_SKILLS / "hotel-comparison.md").read_text(encoding="utf-8")
    baseline = {
        "case_id": case.case_id,
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
        assert data["reflection_transcripts"] == {case.case_id: "本轮酒店卡未展示。"}
        return Proposal(
            skill="comparison-with-context",
            markdown="# 候选\n",
            trigger="当前已有酒店报价且用户需要取舍",
            self_assessment="补展示",
        )

    def replay(candidate: Path, tasks: tuple[tuple[str, int], ...]) -> list[dict[str, object]]:
        assert tasks == ((case.case_id, 1),)
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
        {case.case_id: "本轮酒店卡未展示。"},
        params,
        replay,
        propose=propose,
    )
    assert result.kept and result.baseline == 0 and result.candidate and result.candidate > 0
    assert (tmp_path / "review.md").is_file()
    assert (BUILTIN_SKILLS / "hotel-comparison.md").read_text(encoding="utf-8") == original
