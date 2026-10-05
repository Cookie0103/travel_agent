"""实时数据边界的坐标与安全错误；不依赖 HTTP 或数据库。"""

from pydantic import BaseModel, Field


class Coordinates(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class GeoPoint(Coordinates):
    name: str
    viewport: dict[str, Coordinates] | None = None
    broad: bool = False


class ExternalDataError(ValueError):
    def __init__(self, message: str, *, validation: bool = False) -> None:
        super().__init__(message)
        self.validation = validation
