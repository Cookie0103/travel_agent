"""旧"travel_details"选择卡改为"form"卡，并收紧choice_cards.kind的CHECK。

travel_details卡的content.details(交通/节奏预选、time_constraints原文)在迁移里转成
content.form(与domain.choices.make_form对TRANSPORT_PACE_GROUPS的输出同形，选项取值是写迁移时
冻结的快照)，删除details；question/options原样保留。details缺失或不是对象时按"无预选、无时间题"生成。
降级只重新允许travel_details取值；已转换的行保持form，旧代码同样能读。
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

NEW_KINDS = ("pace", "form", "budget_relaxation", "memory_confirm")
OLD_KINDS = (*NEW_KINDS, "travel_details")

TRANSPORT = (("walk", "步行"), ("transit", "公共交通（公交、地铁为主）"), ("taxi", "打车"))
PACE = (
    ("standard", "标准", "标准"),
    ("intensive", "特种兵", "特种兵"),
    ("relaxed", "比较轻松", "慢节奏"),
)
YES_NO = (("yes", "没问题"), ("no", "需要修改"))


def group(
    key: str,
    label: str,
    options: tuple[tuple[str, str], ...],
    selected: str | None,
    kind: str = "choice",
    shown: list[str] | None = None,
) -> dict[str, object]:
    return {
        "key": key,
        "label": label,
        "multi": False,
        "required": False,
        "options": [{"option_id": i, "label": text} for i, text in options],
        "kind": kind,
        "selected": [selected] if selected else [],
        "shown": shown or [],
    }


def form_from_details(details: object) -> dict[str, object]:
    details = details if isinstance(details, dict) else {}
    transport = details.get("transport")
    transport = transport if transport in {i for i, _ in TRANSPORT} else None
    pace = next((i for i, _, value in PACE if value == details.get("pace")), None)
    raw = details.get("time_constraints")
    times = (
        [text for text in raw if isinstance(text, str) and text] if isinstance(raw, list) else []
    )
    groups = [
        group("transport", "交通方式", TRANSPORT, transport),
        group("pace", "旅行节奏", tuple((i, label) for i, label, _ in PACE), pace),
    ]
    if times:
        groups.append(group("times", "抵达/离开时间", YES_NO, None, kind="times", shown=times))
    return {"groups": groups}


def set_check(values: tuple[str, ...]) -> None:
    op.execute("ALTER TABLE choice_cards DROP CONSTRAINT IF EXISTS ck_choice_cards_kind")
    listed = ", ".join(f"'{value}'" for value in values)
    op.execute(
        f"ALTER TABLE choice_cards ADD CONSTRAINT ck_choice_cards_kind "
        f"CHECK (kind IN ({listed})) NOT VALID"
    )
    op.execute("ALTER TABLE choice_cards VALIDATE CONSTRAINT ck_choice_cards_kind")


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, content FROM choice_cards WHERE kind = 'travel_details'")
    ).all()
    for row_id, content in rows:
        content = dict(content or {})
        details = content.pop("details", None)
        if isinstance(details, dict) or not isinstance(content.get("form"), dict):
            content["form"] = form_from_details(details)
        bind.execute(
            sa.text(
                "UPDATE choice_cards SET kind = 'form', content = CAST(:content AS jsonb) "
                "WHERE id = :id"
            ),
            {"id": row_id, "content": json.dumps(content, ensure_ascii=False)},
        )
    set_check(NEW_KINDS)


def downgrade() -> None:
    set_check(OLD_KINDS)
