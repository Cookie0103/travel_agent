"""choice_cards.kind的CHECK加入hotel_assign(聊天选酒店的归段确认卡)；只放宽约束，不改数据。

取值是写迁移时从domain.choices.ChoiceKind冻结的快照；
tests/integration/test_schema_constraints.py 断言CHECK与当前代码枚举一致。
降级：旧集合没有hotel_assign，行不能删（会丢用户数据）也不能原样留下。所以把它们改成
旧代码能读的“已失效”form卡——kind=form、content.superseded=true、清空已答选项，原归段信息
(content.assign等)保留在content里，不丢数据；再收紧CHECK。升级后这些行仍是失效的form卡。
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

OLD_KINDS = ("pace", "form", "budget_relaxation", "memory_confirm")
NEW_KINDS = (*OLD_KINDS, "hotel_assign")
# 旧代码读form卡需要的最小合法形状（至少1组、每组2个选项）；superseded保证它永远是失效卡。
INERT_OPTIONS = [{"option_id": "confirm", "label": "已失效", "value": "confirm"}]
INERT_FORM = {
    "groups": [
        {
            "key": "retired",
            "label": "已失效",
            "kind": "choice",
            "multi": False,
            "required": False,
            "selected": [],
            "shown": [],
            "options": [
                {"option_id": "yes", "label": "已失效"},
                {"option_id": "no", "label": "已失效"},
            ],
        }
    ]
}


def set_check(values: tuple[str, ...]) -> None:
    op.execute("ALTER TABLE choice_cards DROP CONSTRAINT IF EXISTS ck_choice_cards_kind")
    listed = ", ".join(f"'{value}'" for value in values)
    op.execute(
        f"ALTER TABLE choice_cards ADD CONSTRAINT ck_choice_cards_kind "
        f"CHECK (kind IN ({listed})) NOT VALID"
    )
    op.execute("ALTER TABLE choice_cards VALIDATE CONSTRAINT ck_choice_cards_kind")


def upgrade() -> None:
    set_check(NEW_KINDS)


def downgrade() -> None:
    bind = op.get_bind()
    for row_id, content in bind.execute(
        sa.text("SELECT id, content FROM choice_cards WHERE kind = 'hotel_assign'")
    ).all():
        old = dict(content or {})
        if "assign" in old:  # 归段信息改存retired_assign，避免新代码把form卡误读成hotel_assign
            old["retired_assign"] = old.pop("assign")
        retired = {**old, "options": INERT_OPTIONS, "form": INERT_FORM, "superseded": True}
        bind.execute(
            sa.text(
                "UPDATE choice_cards SET kind = 'form', answered_option_id = NULL, "
                "content = CAST(:content AS jsonb) WHERE id = :id"
            ),
            {"id": row_id, "content": json.dumps(retired, ensure_ascii=False)},
        )
    set_check(OLD_KINDS)
