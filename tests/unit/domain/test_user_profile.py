"""画像不接受缺失、外人、残缺引用；上限不截断引用。"""

from uuid import uuid4

from backend.domain.user_profile import ProfileGeneration, supported_profile


def test_profile_drops_whole_unsupported_sentences_and_caps_output() -> None:
    own, foreign = uuid4(), uuid4()
    output = ProfileGeneration(
        sentences=(
            f"喜欢公交 [fact:{own}]",
            f"虚构偏好 [fact:{foreign}]",
            "没有引用",
            f"混合引用 [fact:{own}] [fact:bad]",
            f"{'长' * 600} [fact:{own}]",
        )
    )
    text, ids = supported_profile(output, {own})
    assert text == f"喜欢公交 [fact:{own}]" and ids == (own,)
