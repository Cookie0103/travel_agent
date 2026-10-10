"""稳定行程项与局部patch规则；保留未改项，模型只暂存草稿，确认由业务事务完成。"""

from typing import Annotated, Literal, Self
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from backend.domain.itinerary import (
    PLAN_ITEM_LIMIT,
    HotelStay,
    ItineraryProposal,
    ProposedItem,
    ValidationReport,
)
from backend.domain.travel_request import TravelRequest


class PlanItem(ProposedItem):
    item_id: UUID = Field(default_factory=uuid4)
    locked: bool = False

    def proposed(self) -> ProposedItem:
        return ProposedItem.model_validate(self.model_dump(exclude={"item_id", "locked"}))


class PlanContent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    items: tuple[PlanItem, ...] = Field(min_length=1, max_length=PLAN_ITEM_LIMIT)
    hotel_evidence_id: UUID | None = None
    hotel_stays: tuple[HotelStay, ...] = Field(
        default=(), max_length=6, exclude_if=lambda value: not value
    )

    @model_validator(mode="after")
    def unique_items(self) -> Self:
        if len({item.item_id for item in self.items}) != len(self.items):
            raise ValueError("行程item_id不能重复")
        if self.hotel_evidence_id is not None and self.hotel_stays:
            raise ValueError("旧酒店引用与分段住宿不能同时设置")
        return self

    def proposal(self, revision: int) -> ItineraryProposal:
        return ItineraryProposal.model_validate(
            {
                "expected_revision": revision,
                "items": tuple(item.proposed() for item in self.items),
                "hotel_evidence_id": self.hotel_evidence_id,
                **({"hotel_stays": self.hotel_stays} if self.hotel_stays else {}),
            },
        )


class AddItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    op: Literal["add"]
    after_item_id: UUID | None = None
    item: ProposedItem


class UpdateItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    op: Literal["update"]
    item_id: UUID
    item: ProposedItem


class RemoveItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    op: Literal["remove"]
    item_id: UUID


Operation = Annotated[AddItem | UpdateItem | RemoveItem, Field(discriminator="op")]


class PlanPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    base_version: int = Field(strict=True, ge=1)
    expected_revision: int = Field(strict=True, ge=0)
    operations: tuple[Operation, ...] = Field(default=(), max_length=PLAN_ITEM_LIMIT)
    hotel_evidence_id: UUID | None = None
    hotel_stays: tuple[HotelStay, ...] | None = Field(
        default=None,
        max_length=6,
        exclude_if=lambda value: value is None,
    )

    @model_validator(mode="after")
    def valid_operations(self) -> Self:
        if self.hotel_evidence_id is not None and self.hotel_stays is not None:
            raise ValueError("旧酒店引用与分段住宿不能同时设置")
        if "hotel_stays" in self.model_fields_set and self.hotel_stays is None:
            raise ValueError("清除住宿请提供空列表，不以null代替")
        ids = [op.item_id for op in self.operations if isinstance(op, UpdateItem | RemoveItem)]
        if len(ids) != len(set(ids)):
            raise ValueError("同一行程项一次patch只能修改一次")
        if not self.operations and not (
            {"hotel_evidence_id", "hotel_stays"} & self.model_fields_set
        ):
            raise ValueError("patch需要明确的项目操作或住宿操作")
        return self


class InitialStage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["initial"]
    proposal: ItineraryProposal


class PatchStage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["patch"]
    plan_id: UUID
    patch: PlanPatch


class StageInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    change: Annotated[InitialStage | PatchStage, Field(discriminator="kind")]


class ItemDiff(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    item_id: UUID
    op: Literal["add", "update", "remove"]
    before: PlanItem | None = None
    after: PlanItem | None = None


class PlanDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    draft_id: UUID = Field(default_factory=uuid4)
    plan_id: UUID
    base_version: int
    request_revision: int
    content: PlanContent
    changes: tuple[ItemDiff, ...]
    hotel_changed: bool
    validation: ValidationReport
    expires_at: AwareDatetime

    def summary(self) -> dict[str, object]:
        return {
            **self.model_dump(mode="json", exclude={"content", "changes", "validation"}),
            "validation": self.validation.feedback(),
            "changes": [change.model_dump(mode="json") for change in self.changes[:6]],
            "change_count": len(self.changes),
            "changes_truncated": len(self.changes) > 6,
            "guidance": "仅暂存草稿，未保存；用户从确认API保存前会再次校验",
        }


class SavedPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    plan_id: UUID
    version: int = Field(strict=True, ge=1)
    request_revision: int
    content: PlanContent
    validation: ValidationReport
    saved_at: AwareDatetime


def initial_content(proposal: ItineraryProposal) -> PlanContent:
    return PlanContent(
        items=tuple(PlanItem(**item.model_dump()) for item in proposal.items),
        hotel_evidence_id=proposal.hotel_evidence_id,
        hotel_stays=proposal.hotel_stays,
    )


def apply_plan_patch(current: SavedPlan, patch: PlanPatch) -> PlanContent:
    if patch.base_version != current.version:
        raise ValueError("正式行程版本已变化")
    items = list(current.content.items)
    for operation in patch.operations:
        if isinstance(operation, AddItem):
            if operation.after_item_id is None:
                index = 0
            else:
                index = next(
                    (
                        i + 1
                        for i, item in enumerate(items)
                        if item.item_id == operation.after_item_id
                    ),
                    -1,
                )
                if index == -1:
                    raise ValueError("新增项的定位item_id不存在")
            items.insert(index, PlanItem(**operation.item.model_dump()))
            continue
        index = next((i for i, item in enumerate(items) if item.item_id == operation.item_id), -1)
        if index == -1:
            raise ValueError("待修改item_id不存在")
        if items[index].locked:
            raise ValueError("不能修改用户锁定的行程项，请先由用户解锁")
        if isinstance(operation, RemoveItem):
            items.pop(index)
        else:
            items[index] = PlanItem(item_id=operation.item_id, **operation.item.model_dump())
    hotel, stays = current.content.hotel_evidence_id, current.content.hotel_stays
    if "hotel_stays" in patch.model_fields_set:
        hotel, stays = None, patch.hotel_stays or ()
    elif "hotel_evidence_id" in patch.model_fields_set:
        hotel, stays = patch.hotel_evidence_id, ()
    return PlanContent(items=tuple(items), hotel_evidence_id=hotel, hotel_stays=stays)


def stays_of(
    content: PlanContent | ItineraryProposal, request: TravelRequest
) -> tuple[HotelStay, ...]:
    """统一读取住宿引用；旧单城按已知旅行日期投影，不填补未知日期。"""
    if content.hotel_stays:
        return content.hotel_stays
    if content.hotel_evidence_id is None or request.start_date is None or request.end_date is None:
        return ()
    return (
        HotelStay(
            check_in=request.start_date,
            check_out=request.end_date,
            hotel_evidence_id=content.hotel_evidence_id,
        ),
    )


def differences(before: PlanContent | None, after: PlanContent) -> tuple[ItemDiff, ...]:
    old = {item.item_id: item for item in before.items} if before else {}
    new = {item.item_id: item for item in after.items}
    return tuple(
        ItemDiff(
            item_id=id,
            op="add" if id not in old else "remove" if id not in new else "update",
            before=old.get(id),
            after=new.get(id),
        )
        for id in dict.fromkeys((*old, *new))
        if old.get(id) != new.get(id)
    )
