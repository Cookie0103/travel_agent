/** Application state and recovery; only explicit user actions can submit or confirm. */
"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  ApiError,
  messageInput,
  readDraft,
  readConfirmedPlan,
  readRunHistory,
  readTripHistory,
  createTrip,
  confirmPlan,
  type TripSummary,
  readEvents,
  readWhile,
  type Identity,
  type RequestState,
  type Run,
  type HistoricalRun,
  type Plan,
  type Hotels,
  type AppEvent,
  type Booking,
} from "./api";
import type { components } from "./api-types";
import {
  isCardEvent,
  belongsToRun,
  matchesRun,
  type RunBinding,
} from "./early-cards";
import {
  persistIdentity,
  restoreIdentity,
  forgetIdentity,
  pendingFor,
} from "./identity-storage";
import { mergeHistory, mergeRun } from "./history";
import type { Mode } from "./models";
import type { ConditionPatch } from "./condition-patch";

const message = (error: unknown) =>
  error instanceof Error ? error.message : "操作失败，请重试。";

export function useWorkspace({
  savedOnly = false,
}: { savedOnly?: boolean } = {}) {
  const [identity, setIdentity] = useState<Identity>();
  const [request, setRequest] = useState<RequestState>();
  const [run, setRun] = useState<Run>();
  const [history, setHistory] = useState<HistoricalRun[]>([]);
  const [historyBefore, setHistoryBefore] = useState<string | null>(null);
  const [historyError, setHistoryError] = useState("");
  const [trips, setTrips] = useState<TripSummary[]>([]);
  const [tripCursor, setTripCursor] = useState<string | null>(null);
  const [events, setEvents] = useState<AppEvent[]>([]);
  const [hotels, setHotels] = useState<Hotels>();
  const [plan, setPlan] = useState<Plan>();
  const [confirmation, setConfirmation] = useState<{
    session_id: string;
    draft_id: string;
    plan_id: string;
    version: number;
  }>();
  const confirming = useRef(false);
  const [planOrigin, setPlanOrigin] = useState<RunBinding>();
  const [hotelOrigin, setHotelOrigin] = useState<RunBinding>();
  const [bookings, setBookings] = useState<Booking[]>([]);
  const [error, setError] = useState("");
  const [sendError, setSendError] = useState("");
  const [busy, setBusy] = useState(false);
  const [restoring, setRestoring] = useState(true);
  const stream = useRef<AbortController | null>(null);
  const cursor = useRef(0);
  const generation = useRef(0);
  const historyLoaded = useRef(false);
  const tripsLoaded = useRef(false);
  const owner = useRef<string | undefined>(undefined);

  const fail = useCallback((failure: unknown) => {
    if (failure instanceof ApiError && failure.status === 401) {
      generation.current += 1;
      stream.current?.abort();
      cursor.current = 0;
      forgetIdentity(localStorage, sessionStorage, owner.current);
      owner.current = undefined;
      setIdentity(undefined);
      setRequest(undefined);
      setRun(undefined);
      setHistory([]);
      setHistoryBefore(null);
      historyLoaded.current = false;
      tripsLoaded.current = false;
      setTrips([]);
      setTripCursor(null);
      setEvents([]);
      setHotels(undefined);
      setPlan(undefined);
      setConfirmation(undefined);
      setPlanOrigin(undefined);
      setHotelOrigin(undefined);
      setBookings([]);
      setBusy(false);
      setRestoring(false);
      setError("身份已失效，请重新创建演示会话。");
    } else setError(message(failure));
  }, []);

  const remember = useCallback((value: Identity) => {
    persistIdentity(localStorage, sessionStorage, value);
    owner.current = value.token;
    setIdentity(value);
  }, []);

  const hydrate = useCallback(
    async (
      event: { presentation?: unknown; context?: unknown },
      current: Identity,
      active: () => boolean,
      binding: RunBinding,
    ) => {
      const payload = event.presentation as
        { data?: Hotels | Plan } | undefined;
      const data = payload?.data;
      if (!data || !active() || !belongsToRun(event, binding)) return;
      if ("component" in data && data.component === "hotel_comparison") {
        setHotels(data);
        setHotelOrigin(binding);
      } else if ("draft_id" in data && data.draft_id) {
        const displayed = await readDraft(data.draft_id, current.token);
        if (!active()) return;
        setPlan(displayed);
        setPlanOrigin(binding);
      } else if ("plan_id" in data && data.plan_id) {
        const displayed = await readConfirmedPlan({
          plan_id: data.plan_id,
          token: current.token,
        });
        if (!active() || !displayed) return;
        setPlan(displayed);
        setPlanOrigin(binding);
      }
    },
    [],
  );

  const connect = useCallback(
    async (current: Identity, runId: string, after: number) => {
      stream.current?.abort();
      const controller = new AbortController();
      stream.current = controller;
      const started = generation.current;
      const active = () =>
        !controller.signal.aborted && generation.current === started;
      cursor.current = after;
      // 早期出卡按事件顺序串行；失败静默，运行结束后的 hydrate 为准。
      let early = Promise.resolve();
      try {
        await readEvents(
          runId,
          current.token,
          after,
          controller.signal,
          (event) => {
            const binding = { session_id: current.session_id, run_id: runId };
            if (
              !belongsToRun(event, binding) ||
              event.sequence <= cursor.current ||
              !active()
            )
              return;
            cursor.current = event.sequence;
            setEvents((old) => [...old.slice(-79), event]);
            if (isCardEvent(event))
              early = early
                .then(() => hydrate(event, current, active, binding))
                .catch(() => undefined);
          },
        );
        await early;
        if (!active()) return;
        const final = await api<Run>(`/runs/${runId}`, current.token);
        if (!active()) return;
        if (
          !matchesRun(final, { session_id: current.session_id, run_id: runId })
        )
          throw new Error("执行记录不属于当前旅行或轮次。");
        setRun((old) => mergeRun(old, final));
        setHistory((old) =>
          old.map((row) =>
            row.run_id === final.run_id
              ? { ...row, ...mergeRun(row, final) }
              : row,
          ),
        );
        for (const event of final.presentations ?? [])
          await hydrate(event, current, active, final);
        if (!active()) return;
        const state = await api<RequestState>(
          `/sessions/${current.session_id}/request`,
          current.token,
        );
        if (!active()) return;
        setRequest(state);
        const savedBookings = await api<Booking[]>(
          `/sessions/${current.session_id}/bookings`,
          current.token,
        );
        if (!active()) return;
        setBookings(savedBookings);
        if (final.error_code && final.business_result?.kind !== "stage_failed")
          setError(final.answer || `执行失败：${final.error_code}`);
      } catch (failure) {
        if (active()) fail(failure);
      } finally {
        if (active()) setBusy(false);
      }
    },
    [hydrate, fail],
  );

  const restoreConversation = useCallback(
    async (current: Identity, active: () => boolean) => {
      let latestId = current.run_id;
      try {
        const page = await readRunHistory(current);
        if (!active()) return;
        setHistory((old) =>
          active() ? mergeHistory(old, page.items, current.session_id) : old,
        );
        if (!historyLoaded.current) {
          setHistoryBefore(page.next_before);
          historyLoaded.current = true;
        }
        setHistoryError("");
        latestId = page.items.at(-1)?.run_id;
      } catch (failure) {
        if (!active()) return;
        if (!(failure instanceof ApiError && failure.status === 404))
          throw failure;
        setHistoryError("当前服务版本暂不支持旅行历史。");
      }
      if (!latestId || !active()) return;
      const saved = await api<Run>(`/runs/${latestId}`, current.token);
      if (!active()) return;
      if (
        !matchesRun(saved, { session_id: current.session_id, run_id: latestId })
      )
        throw new Error("执行记录不属于当前旅行或轮次。");
      setRun((old) => (active() ? mergeRun(old, saved) : old));
      setHistory((old) =>
        old.map((row) =>
          row.run_id === saved.run_id
            ? { ...row, ...mergeRun(row, saved) }
            : row,
        ),
      );
      for (const event of saved.presentations ?? [])
        await hydrate(event, current, active, saved);
      if (!active()) return;
      if (["running", "cancelling"].includes(saved.status)) {
        setBusy(true);
        void connect(current, saved.run_id, 0);
      }
    },
    [connect, hydrate],
  );

  const readTrips = useCallback(
    async (current: Identity, active: () => boolean) => {
      let page = await readTripHistory(current.token);
      if (!active()) return;
      let selected = page.items.find(
        (item) => item.session_id === current.session_id,
      );
      const loaded = [...page.items];
      while (!selected && page.next_cursor && active()) {
        page = await readTripHistory(current.token, page.next_cursor);
        if (!active()) return;
        loaded.push(...page.items);
        selected = page.items.find(
          (item) => item.session_id === current.session_id,
        );
      }
      if (!active()) return;
      setTrips((old) => {
        if (!active()) return old;
        const rows = new Map(
          [...old, ...loaded].map((item) => [item.session_id, item]),
        );
        return [...rows.values()].sort(
          (a, b) =>
            Date.parse(b.created_at) - Date.parse(a.created_at) ||
            b.session_id.localeCompare(a.session_id),
        );
      });
      if (!tripsLoaded.current) {
        setTripCursor(page.next_cursor);
        tripsLoaded.current = true;
      }
      if (!selected) throw new Error("旅行历史中未找到当前旅行，请重试读取。");
      return selected;
    },
    [],
  );
  const loadTrip = useCallback(
    async (current: Identity, active: () => boolean) => {
      if (!savedOnly) {
        const state = await api<RequestState>(
          `/sessions/${current.session_id}/request`,
          current.token,
        );
        if (!active()) return;
        setRequest(state);
        const savedBookings = await api<Booking[]>(
          `/sessions/${current.session_id}/bookings`,
          current.token,
        );
        if (!active()) return;
        setBookings(savedBookings);
      }
      let planId = current.plan_id;
      try {
        const selected = await readTrips(current, active);
        if (!active()) return;
        planId = selected?.plan_id ?? undefined;
        if (savedOnly) setHistoryError("");
      } catch (failure) {
        if (!active()) return;
        if (!(failure instanceof ApiError && failure.status === 404))
          throw failure;
        setHistoryError("当前服务版本暂不支持旅行历史。");
      }
      const savedPlan = await readConfirmedPlan({
        token: current.token,
        plan_id: planId,
      });
      if (!active()) return;
      setPlan(savedPlan);
      if (savedPlan) setConfirmation(undefined);
      setPlanOrigin(undefined);
      setIdentity((old) =>
        old?.token === current.token && old.session_id === current.session_id
          ? { ...old, plan_id: planId }
          : old,
      );
      if (!savedOnly) await restoreConversation(current, active);
    },
    [readTrips, restoreConversation, savedOnly],
  );

  useEffect(() => {
    let mounted = true;
    const started = generation.current;
    const active = () => mounted && generation.current === started;
    async function restore() {
      try {
        const current = restoreIdentity(localStorage, sessionStorage);
        if (!current || !active()) return;
        // Server authentication decides validity; a network error keeps this identity.
        owner.current = current.token;
        setIdentity(current);
        await loadTrip(current, active);
      } catch (failure) {
        if (active()) fail(failure);
      } finally {
        if (mounted) setRestoring(false);
      }
    }
    void restore();
    return () => {
      mounted = false;
      // 导航后迟到的请求不能覆盖新页面已经保存的身份。
      generation.current += 1;
      stream.current?.abort();
    };
  }, [loadTrip, fail]);

  async function action(
    work: (
      read: ReturnType<typeof readWhile>,
      active: () => boolean,
    ) => Promise<void>,
  ) {
    const started = generation.current;
    setBusy(true);
    setError("");
    try {
      const active = () => generation.current === started;
      await work(readWhile(active), active);
      return active();
    } catch (failure) {
      if (generation.current === started) fail(failure);
      return false;
    } finally {
      if (generation.current === started) setBusy(false);
    }
  }
  async function login() {
    generation.current += 1;
    stream.current?.abort();
    await action(async (read, active) => {
      const user = await read(
        api<components["schemas"]["DemoIdentity"]>(
          "/demo/login",
          undefined,
          "POST",
          { display_name: "旅行者" },
        ),
      );
      if (!active()) return;
      const session = await read(createTrip(user.token));
      if (!active()) return;
      const current = { ...user, session_id: session.session_id };
      remember(current);
      setRun(undefined);
      setHistory([]);
      setHistoryBefore(null);
      setHistoryError("");
      historyLoaded.current = true;
      tripsLoaded.current = false;
      setTrips([]);
      setTripCursor(null);
      setHotels(undefined);
      setPlan(undefined);
      setConfirmation(undefined);
      setPlanOrigin(undefined);
      setHotelOrigin(undefined);
      setBookings([]);
      setEvents([]);
      const state = await read(
        api<RequestState>(
          `/sessions/${current.session_id}/request`,
          current.token,
        ),
      );
      if (!active()) return;
      setRequest(state);
      await readTrips(current, active);
    });
  }
  async function changeTrip(sessionId?: string) {
    if (!identity || busy || restoring) return false;
    const started = ++generation.current;
    setRestoring(true);
    stream.current?.abort();
    cursor.current = 0;
    try {
      return await action(async (read, active) => {
        const selected = await read(
          sessionId
            ? api<components["schemas"]["SessionView"]>(
                `/sessions/${sessionId}`,
                identity.token,
              )
            : createTrip(identity.token),
        );
        if (!active()) return;
        const current: Identity = {
          token: identity.token,
          session_id: selected.session_id,
        };
        current.pending_message = pendingFor(sessionStorage, current);
        setRequest(undefined);
        setRun(undefined);
        setHistory([]);
        setHistoryBefore(null);
        historyLoaded.current = false;
        setHistoryError("");
        setSendError("");
        setEvents([]);
        setHotels(undefined);
        setPlan(undefined);
        setConfirmation(undefined);
        setPlanOrigin(undefined);
        setHotelOrigin(undefined);
        setBookings([]);
        remember(current);
        await loadTrip(current, active);
      });
    } finally {
      if (generation.current === started) setRestoring(false);
    }
  }
  async function loadMoreTrips() {
    if (!identity || !tripCursor || busy) return;
    await action(async (read, active) => {
      const page = await read(readTripHistory(identity.token, tripCursor));
      if (!active()) return;
      setTrips((old) =>
        active()
          ? [
              ...new Map(
                [...old, ...page.items].map((item) => [item.session_id, item]),
              ).values(),
            ]
          : old,
      );
      setTripCursor(page.next_cursor);
    });
  }
  async function saveConditions(patch: ConditionPatch) {
    if (!identity || !request) return;
    if (
      Object.keys(patch.set ?? {}).length === 0 &&
      !(patch.clear ?? []).length
    )
      return true;
    return await action(async (read, active) => {
      const result = await read(
        api<components["schemas"]["RequestUpdate"]>(
          `/sessions/${identity.session_id}/request`,
          identity.token,
          "PATCH",
          { expected_revision: request.revision, ...patch },
        ),
      );
      if (!active()) return;
      setRequest(result.request);
      setTrips((old) =>
        active()
          ? old.map((trip) =>
              trip.session_id === identity.session_id
                ? {
                    ...trip,
                    city: result.request.city ?? null,
                    start_date: result.request.start_date ?? null,
                    end_date: result.request.end_date ?? null,
                  }
                : trip,
            )
          : old,
      );
      setHotels(undefined);
      if (plan) {
        const displayed = await read(
          plan.draft_id
            ? readDraft(plan.draft_id, identity.token)
            : api<Plan>(`/plans/${plan.plan_id}`, identity.token),
        );
        if (active()) setPlan(displayed);
      }
    });
  }
  async function refresh() {
    if (!identity) return;
    await action(async (read, active) => {
      if (savedOnly) {
        await loadTrip(identity, active);
        return;
      }
      const state = await read(
        api<RequestState>(
          `/sessions/${identity.session_id}/request`,
          identity.token,
        ),
      );
      if (!active()) return;
      setRequest(state);
      setHotels(undefined);
      const savedBookings = await read(
        api<Booking[]>(
          `/sessions/${identity.session_id}/bookings`,
          identity.token,
        ),
      );
      if (!active()) return;
      setBookings(savedBookings);
      if (confirmation?.session_id === identity.session_id) {
        const displayed = await read(
          api<Plan>(`/plans/${confirmation.plan_id}`, identity.token),
        );
        if (!active()) return;
        setPlan(displayed);
        setPlanOrigin(undefined);
        setConfirmation(undefined);
      } else if (plan) {
        const displayed = await read(
          api<Plan>(
            plan.draft_id
              ? `/plan-drafts/${plan.draft_id}`
              : `/plans/${plan.plan_id}`,
            identity.token,
          ),
        );
        if (active()) setPlan(displayed);
      }
      if (active()) await restoreConversation(identity, active);
    });
  }
  async function send(text: string, mode: Mode) {
    if (!identity || !text.trim() || busy) return false;
    const started = generation.current;
    const read = readWhile(() => generation.current === started);
    setBusy(true);
    setError("");
    try {
      setSendError("");
      const body = messageInput(identity.pending_message, text, mode);
      remember({ ...identity, pending_message: body });
      const submitted = await read(
        api<Run>(
          `/sessions/${identity.session_id}/messages`,
          identity.token,
          "POST",
          body,
        ),
      );
      if (generation.current !== started) return false;
      const current = {
        ...identity,
        run_id: submitted.run_id,
        pending_message: undefined,
      };
      remember(current);
      setRun(submitted);
      setHistory((old) =>
        generation.current === started
          ? mergeHistory(
              old,
              [{ ...submitted, prompt: body.text }],
              current.session_id,
            )
          : old,
      );
      setEvents([]);
      cursor.current = 0;
      await connect(current, submitted.run_id, 0);
      return generation.current === started;
    } catch (failure) {
      if (generation.current !== started) return false;
      if (failure instanceof ApiError && failure.status < 500)
        remember({ ...identity, pending_message: undefined });
      fail(failure);
      setSendError(message(failure));
      setBusy(false);
      return false;
    }
  }
  async function confirm() {
    if (
      !identity ||
      !plan?.draft_id ||
      confirming.current ||
      confirmation?.draft_id === plan.draft_id ||
      plan.status === "confirmed"
    )
      return;
    confirming.current = true;
    try {
      await action(async (read, active) => {
        const displayed = await read(
          confirmPlan(plan.draft_id!, identity.token, (saved) => {
            if (!active()) return;
            setConfirmation({
              session_id: identity.session_id,
              draft_id: plan.draft_id!,
              plan_id: saved.plan_id,
              version: saved.version,
            });
            setPlan(undefined);
            if (planOrigin) {
              const business_result: NonNullable<Run["business_result"]> = {
                kind: "confirmed",
                plan_id: saved.plan_id,
                version: saved.version,
              };
              setRun((old) =>
                old && matchesRun(old, planOrigin)
                  ? { ...old, business_result }
                  : old,
              );
              setHistory((old) =>
                old.map((row) =>
                  matchesRun(row, planOrigin)
                    ? { ...row, business_result }
                    : row,
                ),
              );
            }
            remember({
              ...identity,
              plan_id: saved.plan_id,
              run_id: undefined,
            });
          }),
        );
        if (!active()) return;
        setPlan(displayed);
        setConfirmation(undefined);
        if (planOrigin) {
          const source = await read(
            api<Run>(`/runs/${planOrigin.run_id}`, identity.token),
          );
          if (!active()) return;
          if (!matchesRun(source, planOrigin))
            throw new Error("确认结果不属于原旅行或轮次。");
          setRun((old) =>
            old?.run_id === source.run_id ? mergeRun(old, source) : old,
          );
          setHistory((old) =>
            old.map((row) =>
              row.run_id === source.run_id
                ? { ...row, ...mergeRun(row, source) }
                : row,
            ),
          );
        }
      });
    } finally {
      confirming.current = false;
    }
  }
  async function holdOffer(offerId: string, revision: number) {
    if (!identity) return;
    await action(async (read, active) => {
      try {
        await read(
          api(
            `/sessions/${identity.session_id}/hotel-holds`,
            identity.token,
            "POST",
            {
              offer_id: offerId,
              expected_revision: revision,
            },
          ),
        );
      } finally {
        const savedBookings = await read(
          api<Booking[]>(
            `/sessions/${identity.session_id}/bookings`,
            identity.token,
          ),
        );
        if (active()) setBookings(savedBookings);
      }
    });
  }
  async function bookingAction(
    bookingId: string,
    operation: "confirm" | "reconcile",
  ) {
    if (!identity) return;
    await action(async (read, active) => {
      try {
        await read(
          api(`/bookings/${bookingId}/${operation}`, identity.token, "POST"),
        );
      } finally {
        const savedBookings = await read(
          api<Booking[]>(
            `/sessions/${identity.session_id}/bookings`,
            identity.token,
          ),
        );
        if (active()) setBookings(savedBookings);
      }
    });
  }
  async function lock(itemId: string) {
    if (!identity || !plan?.version) return;
    const ids = new Set(
      plan.cards.filter((item) => item.locked).map((item) => item.item_id),
    );
    if (ids.has(itemId)) ids.delete(itemId);
    else ids.add(itemId);
    await action(async (read, active) => {
      await read(
        api(`/plans/${plan.plan_id}/locks`, identity.token, "PATCH", {
          expected_version: plan.version,
          locked_item_ids: [...ids],
        }),
      );
      if (!active()) return;
      const displayed = await read(
        api<Plan>(`/plans/${plan.plan_id}`, identity.token),
      );
      if (active()) setPlan(displayed);
    });
  }
  async function reconnect() {
    if (!identity || !run) return;
    setError("");
    setBusy(true);
    await connect(identity, run.run_id, cursor.current);
  }
  async function viewRunPlan(runId: string) {
    if (!identity || busy || restoring) return false;
    return await action(async (read, active) => {
      const selected = await read(api<Run>(`/runs/${runId}`, identity.token));
      const binding = { session_id: identity.session_id, run_id: runId };
      if (!active()) return;
      if (!matchesRun(selected, binding))
        throw new Error("行程引用不属于当前旅行或轮次。");
      for (const event of selected.presentations ?? [])
        await hydrate(event, identity, active, binding);
    });
  }
  async function loadEarlier() {
    if (!identity || !historyBefore || busy) return;
    await action(async (read, active) => {
      const page = await read(readRunHistory(identity, historyBefore));
      if (!active()) return;
      setHistory((old) =>
        active() ? mergeHistory(old, page.items, identity.session_id) : old,
      );
      setHistoryBefore(page.next_before);
    });
  }
  async function cancel() {
    if (identity && run) {
      await action(async (read, active) => {
        const cancelled = await read(
          api<Run>(`/runs/${run.run_id}/cancel`, identity.token, "POST"),
        );
        if (active()) setRun(cancelled);
      });
    }
  }
  return {
    identity,
    request,
    run,
    history,
    historyBefore,
    historyError,
    trips,
    tripCursor,
    events,
    hotels,
    plan,
    confirmation,
    planOrigin,
    hotelOrigin,
    bookings,
    error,
    sendError,
    busy,
    restoring,
    fail,
    login,
    newTrip: () => changeTrip(),
    switchTrip: changeTrip,
    loadMoreTrips,
    saveConditions,
    send,
    confirm,
    holdOffer,
    bookingAction,
    lock,
    reconnect,
    loadEarlier,
    viewRunPlan,
    refresh,
    cancel,
  };
}
