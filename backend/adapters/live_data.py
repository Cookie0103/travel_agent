"""实时工具的数据源组合；离线入口不构造此对象，不新增运行时。"""

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

import httpx

from backend.adapters.external_api import ApiUsage
from backend.adapters.google_maps import GoogleMaps
from backend.adapters.rakuten import Rakuten
from backend.domain.evidence import EvidenceRecord
from backend.persistence.database import Database


@dataclass
class LiveData:
    google: GoogleMaps | None
    rakuten: Rakuten | None
    usage: ApiUsage
    http: httpx.AsyncClient
    evidence: dict[UUID, EvidenceRecord]

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str], database: Database, *, run_limits: bool = True
    ) -> "LiveData":
        http = httpx.AsyncClient()
        usage = ApiUsage(database, environment, run_limits=run_limits)
        key = environment.get("GOOGLE_MAPS_API_KEY", "").strip()
        app, access = (
            environment.get("RAKUTEN_APP_ID", "").strip(),
            environment.get("RAKUTEN_ACCESS_KEY", "").strip(),
        )
        rakuten = (
            Rakuten(
                app,
                access,
                environment.get("RAKUTEN_AFFILIATE_ID", ""),
                environment.get("RAKUTEN_REFERER", ""),
                http,
                usage,
            )
            if app and access
            else None
        )
        return cls(GoogleMaps(key, http, usage) if key else None, rakuten, usage, http, {})

    async def close(self) -> None:
        await self.http.aclose()
