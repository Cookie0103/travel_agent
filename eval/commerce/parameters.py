"""商业期望分参数登记表的只读加载。"""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

type Persona = str

REGISTRY = Path(__file__).with_name("parameters.json")
FEATURES = ("price_ratio", "rating", "log_reviews", "station_minutes", "breakfast", "rank", "soft")


class Prior(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    value: float
    bounds: tuple[float, float]
    source: str
    unit: str


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    top_count: int = Field(ge=1)
    max_partner_share: float = Field(ge=0, le=1)
    min_partner_relevance: float = Field(ge=0, le=1)
    gamma: float = Field(ge=0, le=1)
    partner_value: float = Field(ge=0)


class Registry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    version: str
    state: str
    priors: dict[str, Prior]
    persona_multipliers: dict[Persona, dict[str, Prior]]
    soft_items: dict[str, Prior]
    policy: Policy
    policy_sources: dict[str, str]

    def weights(self, persona: Persona) -> dict[str, float]:
        multipliers = self.persona_multipliers[persona]
        return {
            name: self.priors[name].value * (multipliers[name].value if name in multipliers else 1)
            for name in FEATURES
        }


def load_parameters(path: Path = REGISTRY) -> Registry:
    return Registry.model_validate_json(path.read_bytes())
