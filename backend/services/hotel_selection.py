"""酒店按段选择：按钮、聊天与跳过共用同一套服务端校验和存储；模型不能提供酒店身份。"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.domain.choices import AssignInfo, ChoiceOption, ChoiceSelection
from backend.domain.evidence import EvidenceRecord
from backend.domain.execution import RunContext
from backend.domain.hotel_flow import (
    HotelPick,
    PickSource,
    current_picks,
    flow_from_details,
    lodging_segments,
    mentions_city,
    selection_state,
    store,
    with_pick,
    with_skip,
)
from backend.domain.hotels import HotelOffer
from backend.domain.itinerary import HotelStay
from backend.domain.rakuten_links import match_hotel_names, rakuten_hotel_numbers
from backend.domain.travel_request import TravelRequest, TripSegment, same_city
from backend.persistence import travel as requests
from backend.persistence.models import ChoiceCardRow, TravelRequestRow
from backend.services import conversation
from backend.services.choices import ChoiceService
from backend.services.common import ServiceError, transaction
from backend.services.hotels import HotelService, validate_hotel_selection
from backend.services.travel import TravelService, request_from_row, require_revision
from backend.services.views import (
    HotelSelectionPick,
    HotelSelectionSegment,
    HotelSelectionView,
)

CITY_ANSWER_MAX = 40
SEARCH_LIMIT = 6


def selected_stays(row: TravelRequestRow, stays: tuple[HotelStay, ...], run_id: UUID) -> None:
    """本轮可强制的规范选择(与按钮路径同一结构)；下一轮不沿用，见conversation.selected_hotel_stays。"""
    revision = row.revision
    row.request_details = {
        **(row.request_details or {}),
        "selected_hotels": {
            "run_id": str(run_id),
            "revision": revision,
            "stays": [
                stay.model_dump(mode="json") for stay in sorted(stays, key=lambda s: s.check_in)
            ],
        },
    }


def write_picks(
    row: TravelRequestRow,
    request: TravelRequest,
    stays: tuple[HotelStay, ...],
    source: PickSource,
    run_id: UUID,
) -> bool:
    """写入各段选择；各住宿段选齐时同时写入本轮selected_hotels并返回True。调用方已校验。"""
    flow = flow_from_details(row.request_details)
    for stay in stays:
        flow = with_pick(
            flow,
            stay.check_in,
            HotelPick(check_out=stay.check_out, evidence_id=stay.hotel_evidence_id, source=source),
        )
    row.request_details = store(row.request_details, flow)
    picks = current_picks(flow, request)
    if len(picks) != len(lodging_segments(request)):
        return False
    selected_stays(
        row,
        tuple(
            HotelStay(
                check_in=check_in, check_out=pick.check_out, hotel_evidence_id=pick.evidence_id
            )
            for check_in, pick in picks.items()
        ),
        run_id,
    )
    return True


async def record_picks(
    db: AsyncSession,
    context: RunContext,
    row: TravelRequestRow,
    request: TravelRequest,
    stays: tuple[HotelStay, ...],
    source: PickSource,
) -> bool:
    """聊天/确认卡路径：先过与按钮相同的validate_hotel_selection(partial)，再写入。"""
    await validate_hotel_selection(db, context, request, stays, partial=True)
    return write_picks(row, request, stays, source, context.run_id)


def skip_hotels(row: TravelRequestRow, request: TravelRequest) -> None:
    if not lodging_segments(request):
        raise ServiceError(422, "validation", "当前没有需要选择酒店的住宿段")
    row.request_details = store(
        row.request_details, with_skip(flow_from_details(row.request_details), request)
    )


async def answer_assignment(
    db: AsyncSession,
    context: RunContext,
    card: ChoiceCardRow,
    option: ChoiceOption,
    selection: ChoiceSelection,
    request: TravelRequest,
) -> None:
    """hotel_assign卡的点击在消息事务内处理(只读写DB，不调外部)。"""
    info = AssignInfo.model_validate(card.content["assign"])
    answers = selection.answers
    if option.option_id == "deny":
        typed = (answers or {}).get("city")
        if (
            set(answers or {}) != {"city"}
            or not typed
            or len(typed) != 1
            or not typed[0].strip()
            or len(typed[0].strip()) > CITY_ANSWER_MAX
        ):
            raise ServiceError(422, "validation", "请填写酒店所在的城市(1至40字)")
        card.content = {**card.content, "city_answer": typed[0].strip()}
        return
    if answers is not None:
        raise ServiceError(422, "validation", "此选项不需要填写答案")
    if option.option_id != "confirm":
        return
    row = await requests.owned_request(db, context)
    assert row is not None and info.check_in and info.check_out
    stay = HotelStay(
        check_in=info.check_in,
        check_out=info.check_out,
        hotel_evidence_id=UUID(str(card.content["evidence_id"])),
    )
    await record_picks(db, context, row, request, (stay,), "assign_confirm")


@dataclass(frozen=True)
class Shown:
    record: EvidenceRecord
    offer: HotelOffer
    fresh: bool


@dataclass(frozen=True)
class Target:
    hotel_id: str
    name: str | None = None
    city_hint: str | None = None  # 用户在“否”卡里填写的城市
    denial_id: UUID | None = None


def segment_of(offer: HotelOffer, segments: tuple[TripSegment, ...]) -> TripSegment | None:
    return next(
        (
            s
            for s in segments
            if (s.arrive, s.depart) == (offer.request.start_date, offer.request.end_date)
            and same_city(s.city, offer.request.city or "")
        ),
        None,
    )


def best(items: list[Shown]) -> Shown:
    return min(
        items,
        key=lambda i: (
            i.offer.total is None,
            i.offer.total if i.offer.total is not None else 0,
        ),
    )


def brief(segment: TripSegment) -> dict[str, object]:
    return {
        "city": segment.city,
        "check_in": segment.arrive.isoformat(),
        "check_out": segment.depart.isoformat(),
    }


class HotelSelectionService:
    def __init__(self, travel: TravelService) -> None:
        self.travel = travel
        self.hotels = HotelService(travel)
        self.choices = ChoiceService(travel)

    async def view(self, user_id: UUID, session_id: UUID) -> HotelSelectionView:
        context = RunContext(user_id, session_id)
        async with transaction(self.travel.database) as db:
            row = await requests.read_request(db, context)
            request = request_from_row(row)
            assert row is not None
            flow = flow_from_details(row.request_details)
            picks = current_picks(flow, request)
            evidence = {
                r.id: r
                for r in await requests.find_evidence(
                    db, context, [p.evidence_id for p in picks.values()]
                )
            }
        state = selection_state(flow, request)
        segments = []
        for segment in lodging_segments(request):
            pick = picks.get(segment.arrive)
            found = evidence.get(pick.evidence_id) if pick else None
            selected = None
            if pick and found is not None and found.kind == "hotel_offer":
                value = found.payload.get("value")
                name = str(value.get("hotel_name", "")) if isinstance(value, dict) else ""
                selected = HotelSelectionPick(
                    evidence_id=pick.evidence_id, hotel_name=name, source=pick.source
                )
            segments.append(
                HotelSelectionSegment(
                    city=segment.city,
                    check_in=segment.arrive,
                    check_out=segment.depart,
                    selected=selected,
                )
            )
        return HotelSelectionView(
            state=state, segments=tuple(segments), can_skip=state == "awaiting"
        )

    # ---- 聊天选酒店(select_hotel_from_chat工具) ----

    async def from_chat(self, context: RunContext, revision: int) -> dict[str, object]:
        request = await self.travel.read_request(context)
        require_revision(request, revision)
        segments = lodging_segments(request)
        if not segments:
            return {
                "status": "nothing_to_select",
                "message": "当前没有需要选择酒店的住宿段（条件未齐或当天往返）。",
            }
        text = await self.travel.trusted_user_text(context)
        shown = await self._shown(context, request)
        denial = await self._denial(context)
        picked = await self._picked_hotels(context, request, shown)
        if denial is not None:
            targets = [denial]
        else:
            targets = [Target(number) for number in rakuten_hotel_numbers(text)]
            if not targets:
                names = sorted({s.offer.hotel_name for s in shown})
                hits = match_hotel_names(text, names)
                if len(hits) > 1:
                    listed = "、".join(names[i] for i in hits)
                    return {
                        "status": "ambiguous",
                        "candidates": [names[i] for i in hits],
                        "message": f"用户的话同时对得上多家已展示的候选：{listed}。"
                        "请列出这几家，问用户是哪一家，不要猜测。",
                    }
                if not hits:
                    return {
                        "status": "need_link",
                        "message": "没能在已展示的候选里对上这家酒店。请让用户把乐天链接贴过来，"
                        "不要猜测，也不要自行搜索关键词。",
                    }
                index = hits[0]
                found = next(s for s in shown if s.offer.hotel_name == names[index])
                targets = [Target(found.offer.hotel_id, found.offer.hotel_name)]
        todo = [t for t in targets if t.hotel_id not in picked]
        if not todo:
            return {
                "status": "nothing_to_select",
                "message": "用户提到的酒店都已记录为所选酒店；以服务端选择状态为准继续。",
            }
        data = await self._select(context, request, todo[0], text, shown, segments)
        if len(todo) > 1:
            data["more_hotels"] = len(todo) - 1
            data["message"] = (
                str(data.get("message", "")) + "还有其他链接未处理，可再次调用本工具。"
            )
        return data

    async def _shown(self, context: RunContext, request: TravelRequest) -> list[Shown]:
        async with transaction(self.travel.database) as db:
            rows = await requests.hotel_offer_rows(db, context)
        now = datetime.now(UTC)
        result = []
        for row in rows:
            record = requests.evidence_from_row(row)
            result.append(
                Shown(
                    record, HotelOffer.model_validate(record.value), record.applicable(request, now)
                )
            )
        return result

    async def _picked_hotels(
        self, context: RunContext, request: TravelRequest, shown: list[Shown]
    ) -> set[str]:
        async with transaction(self.travel.database) as db:
            row = await requests.read_request(db, context)
            assert row is not None
            ids = {
                p.evidence_id
                for p in current_picks(flow_from_details(row.request_details), request).values()
            }
        return {s.offer.hotel_id for s in shown if s.record.evidence_id in ids}

    async def _denial(self, context: RunContext) -> Target | None:
        """用户刚在本轮点了“否”并填了城市的归段卡。"""
        async with transaction(self.travel.database) as db:
            card = await db.scalar(
                select(ChoiceCardRow)
                .where(
                    ChoiceCardRow.session_id == context.session_id,
                    ChoiceCardRow.kind == "hotel_assign",
                    ChoiceCardRow.answered_option_id == "deny",
                    ChoiceCardRow.answered_run_id == context.run_id,
                    ChoiceCardRow.content["resolved"].as_boolean().is_not(True),
                )
                .order_by(ChoiceCardRow.created_at.desc())
            )
        if card is None or not card.content.get("city_answer"):
            return None
        return Target(
            hotel_id=str(card.content["hotel_id"]),
            name=AssignInfo.model_validate(card.content["assign"]).hotel_name,
            city_hint=str(card.content["city_answer"]),
            denial_id=card.id,
        )

    async def _search(
        self, context: RunContext, request: TravelRequest, hotel_id: str, segment: TripSegment
    ) -> list[Shown]:
        records = await self.hotels.search(
            context,
            request.revision,
            hotel_id,
            SEARCH_LIMIT,
            segment_arrive=segment.arrive if request.segments else None,
        )
        return [Shown(r, HotelOffer.model_validate(r.value), True) for r in records]

    async def _select(
        self,
        context: RunContext,
        request: TravelRequest,
        target: Target,
        text: str,
        shown: list[Shown],
        segments: tuple[TripSegment, ...],
    ) -> dict[str, object]:
        mine = [s for s in shown if s.offer.hotel_id == target.hotel_id and s.fresh]
        seen: dict[date, tuple[TripSegment, list[Shown]]] = {}
        for item in mine:
            segment = segment_of(item.offer, segments)
            if segment is not None:
                seen.setdefault(segment.arrive, (segment, []))[1].append(item)
        name = target.name or (mine[0].offer.hotel_name if mine else None)
        chosen: tuple[TripSegment, Shown] | None = None
        try:
            if target.city_hint is not None:
                hits = [s for s in segments if mentions_city(target.city_hint, s.city)]
                if len(hits) != 1:
                    return await self._ask_city(context, request, target, name or "这家酒店")
                chosen = await self._quote(context, request, target.hotel_id, hits[0], seen)
            elif len(segments) == 1:
                chosen = await self._quote(context, request, target.hotel_id, segments[0], seen)
            elif len(seen) == 1:
                segment, items = next(iter(seen.values()))
                chosen = (segment, best(items))
            else:
                located = await self._locate(context, request, target.hotel_id, segments)
                if isinstance(located, str):
                    return await self._ask_city(context, request, target, name or "这家酒店")
                chosen = located
        except ServiceError as error:
            return {"status": "search_failed", "message": f"酒店查询失败：{error}。如实告诉用户。"}
        if chosen is None:
            return {
                "status": "not_found",
                "hotel_name": name,
                "message": "按当前入住日期没有查到这家酒店的报价（可能满房或不在这些日期开放）。"
                "如实告诉用户，请他另选或贴别的链接。",
            }
        segment, item = chosen
        info = {"hotel_name": item.offer.hotel_name, "segment": brief(segment)}
        direct = (
            len(segments) == 1 or target.city_hint is not None or mentions_city(text, segment.city)
        )
        if not direct:
            async with transaction(self.travel.database) as db:
                card = await self.choices.create_assign_card(
                    db,
                    context,
                    request.revision,
                    AssignInfo(
                        hotel_name=item.offer.hotel_name,
                        city=segment.city,
                        check_in=segment.arrive,
                        check_out=segment.depart,
                    ),
                    {"hotel_id": target.hotel_id, "evidence_id": str(item.record.evidence_id)},
                )
            return {
                "status": "needs_confirmation",
                **info,
                "choice": card.model_dump(mode="json"),
                "message": "用户没说城市，已按酒店所在城市暂归一段并发出确认卡；"
                "请只说一句“请在卡片里确认归段”，等待用户点击，不要自行记录。",
            }
        stay = HotelStay(
            check_in=segment.arrive,
            check_out=segment.depart,
            hotel_evidence_id=item.record.evidence_id,
        )
        async with transaction(self.travel.database) as db:
            row = await requests.owned_request(db, context)
            assert row is not None
            current = request_from_row(row)
            require_revision(current, request.revision)
            await conversation.require_current_run(db, context)
            complete = await record_picks(db, context, row, current, (stay,), "chat")
            if target.denial_id is not None:
                card_row = await db.get(ChoiceCardRow, target.denial_id)
                if card_row is not None:
                    card_row.content = {**card_row.content, "resolved": True}
            flow = flow_from_details(row.request_details)
            remaining = [
                brief(s)
                for s in lodging_segments(current)
                if s.arrive not in current_picks(flow, current)
            ]
        address = item.record.display_details.address if item.record.display_details else None
        mismatch = bool(
            len(segments) == 1
            and self.travel.live
            and address
            and not mentions_city(address, segment.city)
        )
        return {
            "status": "selected",
            **info,
            "remaining_segments": remaining,
            "all_selected": complete,
            "city_mismatch": mismatch,
            "message": (
                "各住宿段酒店已选齐，服务端已记录；直接继续规划（用selected_hotel_stays）。"
                if complete
                else "已记录这一段；用一句话告诉用户还差哪些住宿段要选酒店，然后等待，不要规划。"
            )
            + ("酒店地址似乎不在所选城市，请提醒用户核对。" if mismatch else ""),
        }

    async def _quote(
        self,
        context: RunContext,
        request: TravelRequest,
        hotel_id: str,
        segment: TripSegment,
        seen: dict[date, tuple[TripSegment, list[Shown]]],
    ) -> tuple[TripSegment, Shown] | None:
        known = seen.get(segment.arrive)
        if known is not None:
            return segment, best(known[1])
        found = await self._search(context, request, hotel_id, segment)
        return (segment, best(found)) if found else None

    async def _locate(
        self,
        context: RunContext,
        request: TravelRequest,
        hotel_id: str,
        segments: tuple[TripSegment, ...],
    ) -> tuple[TripSegment, Shown] | None | str:
        """多城市下判断酒店属于哪一段：实时模式靠地址(最多2次乐天查询)，离线夹具逐段试。"""
        if self.travel.live:
            first = await self._search(context, request, hotel_id, segments[0])
            if not first:
                return None
            record = first[0].record
            address = record.display_details.address if record.display_details else None
            hits = [s for s in segments if address and mentions_city(address, s.city)]
            if len(hits) != 1:
                return "undetermined"
            if hits[0] == segments[0]:
                return hits[0], best(first)
            found = await self._search(context, request, hotel_id, hits[0])
            return (hits[0], best(found)) if found else None
        hits_found = []
        for segment in segments:
            found = await self._search(context, request, hotel_id, segment)
            if found:
                hits_found.append((segment, best(found)))
        if len(hits_found) > 1:
            return "undetermined"
        return hits_found[0] if hits_found else None

    async def _ask_city(
        self, context: RunContext, request: TravelRequest, target: Target, name: str
    ) -> dict[str, object]:
        async with transaction(self.travel.database) as db:
            card = await self.choices.create_assign_card(
                db,
                context,
                request.revision,
                AssignInfo(hotel_name=name, needs_city=True),
                {"hotel_id": target.hotel_id},
            )
            if target.denial_id is not None:
                old = await db.get(ChoiceCardRow, target.denial_id)
                if old is not None:
                    old.content = {**old.content, "resolved": True}
        return {
            "status": "needs_confirmation",
            "hotel_name": name,
            "choice": card.model_dump(mode="json"),
            "message": "判断不出这家酒店属于哪个住宿段，已发出填写城市的卡片；"
            "请只说一句“请在卡片里告诉我是哪个城市”，等待用户，不要猜。",
        }
