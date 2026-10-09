"""从FastAPI与工作台输出模型生成本地契约；不连接数据库、不读取.env或密钥。"""

import json
from pathlib import Path

from pydantic import TypeAdapter
from pydantic.json_schema import models_json_schema
from sqlalchemy import URL

from backend.api.app import create_app
from backend.domain.execution import RuntimeEvent
from backend.services.sessions import SessionService
from backend.services.views import HotelPresentation, PlanView

ROOT = Path(__file__).resolve().parents[1]


def schema() -> dict[str, object]:
    sessions = SessionService(URL.create("postgresql+psycopg", database="schema_only"))
    result = create_app(sessions).openapi()
    _, ui = models_json_schema(
        [(HotelPresentation, "serialization"), (PlanView, "serialization")],
        ref_template="#/components/schemas/Ui{model}",
    )
    definitions = result["components"]["schemas"]
    definitions.update({"Ui" + key: value for key, value in ui["$defs"].items()})
    events = TypeAdapter(RuntimeEvent).json_schema(ref_template="#/components/schemas/Ui{model}")
    definitions.update({"Ui" + key: value for key, value in events.pop("$defs", {}).items()})
    definitions["UiRuntimeEvent"] = events
    return result


def main() -> None:
    target = ROOT / "data" / "contracts" / "web-openapi.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(schema(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print("Generated data/contracts/web-openapi.json (no database or credentials)")


if __name__ == "__main__":
    main()
