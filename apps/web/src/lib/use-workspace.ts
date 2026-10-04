/** Application state and recovery; only explicit user actions can submit or confirm. */
"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  ApiError,
  messageInput,
  readDraft,
  readConfirmedPlan,
  readEvents,
  readWhile,
  type Identity,
  type RequestState,
  type Run,
  type Plan,
  type Hotels,
  type AppEvent,
  type Booking,
} from "./api";
import type { components } from "./api-types";
import { isCardEvent } from "./early-cards";

const STORAGE = "travel-demo-v2";
const message = (error: unknown) =>
  error instanceof Error ? error.message : "操作失败，请重试。";

export function useWorkspace({
  savedOnly = false,
}: { savedOnly?: boolean } = {}) {
  const [identity, setIdentity] = useState<Identity>();
  const [request, setRequest] = useState<RequestState>();
  const [run, setRun] = useState<Run>();
  const [events, setEvents] = useState<AppEvent[]>([]);
  const [hotels, setHotels] = useState<Hotels>();
  const [plan, setPlan] = useState<Plan>();
  const [bookings, setBookings] = useState<Booking[]>([]);
  const [error, setError] = useState("");
  const [sendError, setSendError] = useState("");
  const [busy, setBusy] = useState(false);
  const [restoring, setRestoring] = useState(true);
  const stream = useRef<AbortController | null>(null);
  const cursor = useRef(0);
  const generation = useRef(0);

  const fail = useCallback((failure: unknown) => {
    if (failure instanceof ApiError && failure.status === 401) {
      generation.current += 1;
      stream.current?.abort();
      cursor.current = 0;
      localStorage.removeItem(STORAGE);
      setIdentity(undefined);
      setRequest(undefined);
      setRun(undefined);
      setEvents([]);
      setHotels(undefined);
      setPlan(undefined);
      setBookings([]);
      setBusy(false);
      setError("身份已失效，请重新创建演示会话。");
    } else setError(message(failure));
  }, []);

  const remember = useCallback((value: Identity) => {
    localStorage.setItem(STORAGE, JSON.stringify(value));
    setIdentity(value);
  }, []);

  const hydrate = useCallback(
    async (
      event: { presentation?: unknown },
      current: Identity,
      active: () => boolean,
      persist = true,
    ) => {
      const payload = event.presentation as
        { data?: Hotels | Plan } | undefined;
      const data = payload?.data;
      if (!data || !active()) return;
      if ("component" in data && data.component === "hotel_comparison")
        setHotels(data);
      else if ("draft_id" in data && data.draft_id) {
        const displayed = await readDraft(data.draft_id, current.token);
        if (!active()) return;
        setPlan(displayed);
        if (!displayed.draft_id && persist)
          remember({
            ...current,
            plan_id: displayed.plan_id,
            run_id: undefined,
          });
      } else if ("plan_id" in data && data.plan_id) {
        const displayed = await readConfirmedPlan({
          plan_id: data.plan_id,
          token: current.token,
        });
        if (!active() || !displayed) return;
        setPlan(displayed);
        if (persist)
          remember({
            ...current,
            plan_id: displayed.plan_id,
            run_id: undefined,
          });
      }
    },
    [remember],
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
            if (event.sequence <= cursor.current || !active()) return;
            cursor.current = event.sequence;
            setEvents((old) => [...old.slice(-79), event]);
            if (isCardEvent(event))
              early = early
                .then(() => hydrate(event, current, active, false))
                .catch(() => undefined);
          },
        );
        await early;
        if (!active()) return;
        const final = await api<Run>(`/runs/${runId}`, current.token);
        if (!active()) return;
        setRun(final);
        for (const event of final.presentations ?? [])
          await hydrate(event, current, active);
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
        if (final.error_code)
          setError(final.answer || `执行失败：${final.error_code}`);
      } catch (failure) {
        if (active()) fail(failure);
      } finally {
        if (active()) setBusy(false);
      }
    },
    [hydrate, fail],
  );

  useEffect(() => {
    let mounted = true;
    const started = generation.current;
    const active = () => mounted && generation.current === started;
    async function restore() {
      try {
        const stored = localStorage.getItem(STORAGE);
        if (!stored) return;
        const current = JSON.parse(stored) as Identity;
        if ((current.pending_message?.mode as string) === "live") {
          current.pending_message = undefined;
          remember(current);
          setSendError("旧版实时消息不能重试，请选择模型后重新发送。");
        }
        if (Date.parse(current.expires_at) <= Date.now()) {
          localStorage.removeItem(STORAGE);
          return;
        }
        if (!active()) return;
        // 网络断线不等于没有身份；保留原会话和待重试消息，避免误建新会话。
        setIdentity(current);
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
        if (current.plan_id) {
          const savedPlan = await readConfirmedPlan(current);
          if (!active()) return;
          setPlan(savedPlan);
        }
        if (current.run_id && !savedOnly) {
          const saved = await api<Run>(
            `/runs/${current.run_id}`,
            current.token,
          );
          if (!active()) return;
          setRun(saved);
          for (const event of saved.presentations ?? [])
            await hydrate(event, current, active);
          if (!active()) return;
          if (["running", "cancelling"].includes(saved.status)) {
            setBusy(true);
            void connect(current, saved.run_id, 0);
          }
        }
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
  }, [connect, hydrate, fail, remember, savedOnly]);

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
      const session = await read(
        api<components["schemas"]["SessionView"]>(
          "/sessions",
          user.token,
          "POST",
        ),
      );
      if (!active()) return;
      const current = { ...user, session_id: session.session_id };
      remember(current);
      setRun(undefined);
      setHotels(undefined);
      setPlan(undefined);
      setBookings([]);
      setEvents([]);
      const state = await read(
        api<RequestState>(
          `/sessions/${current.session_id}/request`,
          current.token,
        ),
      );
      if (active()) setRequest(state);
    });
  }
  async function saveConditions(
    fields: Partial<components["schemas"]["TravelConditions"]>,
  ) {
    if (!identity || !request) return;
    return await action(async (read, active) => {
      const result = await read(
        api<components["schemas"]["RequestUpdate"]>(
          `/sessions/${identity.session_id}/request`,
          identity.token,
          "PATCH",
          { expected_revision: request.revision, set: fields },
        ),
      );
      if (!active()) return;
      setRequest(result.request);
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
      if (savedOnly) {
        const displayed = await read(readConfirmedPlan(identity));
        if (active()) setPlan(displayed);
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
    });
  }
  async function send(text: string, mode: "offline" | "deepseek" | "claude") {
    if (!identity || !text.trim() || busy) return;
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
      if (generation.current !== started) return;
      const current = {
        ...identity,
        run_id: submitted.run_id,
        pending_message: undefined,
      };
      remember(current);
      setRun(submitted);
      setEvents([]);
      cursor.current = 0;
      await connect(current, submitted.run_id, 0);
    } catch (failure) {
      if (generation.current !== started) return;
      if (failure instanceof ApiError && failure.status < 500)
        remember({ ...identity, pending_message: undefined });
      fail(failure);
      setSendError(message(failure));
      setBusy(false);
    }
  }
  async function confirm() {
    if (!identity || !plan?.draft_id) return;
    await action(async (read, active) => {
      const saved = await read(
        api<components["schemas"]["SavedPlan"]>(
          `/plan-drafts/${plan.draft_id}/confirm`,
          identity.token,
          "POST",
        ),
      );
      if (!active()) return;
      remember({ ...identity, plan_id: saved.plan_id, run_id: undefined });
      const displayed = await read(
        api<Plan>(`/plans/${saved.plan_id}`, identity.token),
      );
      if (active()) setPlan(displayed);
    });
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
    events,
    hotels,
    plan,
    bookings,
    error,
    sendError,
    busy,
    restoring,
    fail,
    login,
    saveConditions,
    send,
    confirm,
    holdOffer,
    bookingAction,
    lock,
    reconnect,
    refresh,
    cancel,
  };
}
