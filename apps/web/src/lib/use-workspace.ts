/** Application state and recovery; only explicit user actions can submit or confirm. */
"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  ApiError,
  messageInput,
  readDraft,
  readEvents,
  type Identity,
  type RequestState,
  type Run,
  type Plan,
  type Hotels,
  type AppEvent,
  type Booking,
} from "./api";
import type { components } from "./api-types";

const STORAGE = "travel-demo-v1";
const message = (error: unknown) =>
  error instanceof Error ? error.message : "操作失败，请重试。";

export function useWorkspace() {
  const [identity, setIdentity] = useState<Identity>();
  const [request, setRequest] = useState<RequestState>();
  const [run, setRun] = useState<Run>();
  const [events, setEvents] = useState<AppEvent[]>([]);
  const [hotels, setHotels] = useState<Hotels>();
  const [plan, setPlan] = useState<Plan>();
  const [bookings, setBookings] = useState<Booking[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const stream = useRef<AbortController | null>(null);
  const cursor = useRef(0);

  const remember = useCallback((value: Identity) => {
    sessionStorage.setItem(STORAGE, JSON.stringify(value));
    setIdentity(value);
  }, []);

  const hydrate = useCallback(
    async (event: { presentation?: unknown }, current: Identity) => {
      const payload = event.presentation as
        { data?: Hotels | Plan } | undefined;
      const data = payload?.data;
      if (!data) return;
      if ("component" in data && data.component === "hotel_comparison")
        setHotels(data);
      else if ("draft_id" in data && data.draft_id) {
        const displayed = await readDraft(data.draft_id, current.token);
        setPlan(displayed);
        if (!displayed.draft_id)
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
      cursor.current = after;
      try {
        await readEvents(
          runId,
          current.token,
          after,
          controller.signal,
          (event) => {
            if (event.sequence <= cursor.current || controller.signal.aborted)
              return;
            cursor.current = event.sequence;
            setEvents((old) => [...old.slice(-79), event]);
          },
        );
        if (controller.signal.aborted) return;
        const final = await api<Run>(`/runs/${runId}`, current.token);
        setRun(final);
        for (const event of final.presentations ?? [])
          await hydrate(event, current);
        setRequest(
          await api<RequestState>(
            `/sessions/${current.session_id}/request`,
            current.token,
          ),
        );
        setBookings(
          await api<Booking[]>(
            `/sessions/${current.session_id}/bookings`,
            current.token,
          ),
        );
        if (final.error_code)
          setError(final.answer || `执行失败：${final.error_code}`);
      } catch (failure) {
        if (!controller.signal.aborted) setError(message(failure));
      } finally {
        if (!controller.signal.aborted) setBusy(false);
      }
    },
    [hydrate],
  );

  useEffect(() => {
    let mounted = true;
    async function restore() {
      try {
        const stored = sessionStorage.getItem(STORAGE);
        if (!stored) return;
        const current = JSON.parse(stored) as Identity;
        if (Date.parse(current.expires_at) <= Date.now()) {
          sessionStorage.removeItem(STORAGE);
          return;
        }
        const state = await api<RequestState>(
          `/sessions/${current.session_id}/request`,
          current.token,
        );
        if (!mounted) return;
        setIdentity(current);
        setRequest(state);
        setBookings(
          await api<Booking[]>(
            `/sessions/${current.session_id}/bookings`,
            current.token,
          ),
        );
        if (current.plan_id)
          setPlan(await api<Plan>(`/plans/${current.plan_id}`, current.token));
        if (current.run_id) {
          const saved = await api<Run>(
            `/runs/${current.run_id}`,
            current.token,
          );
          if (!mounted) return;
          setRun(saved);
          for (const event of saved.presentations ?? [])
            await hydrate(event, current);
          if (["running", "cancelling"].includes(saved.status)) {
            setBusy(true);
            void connect(current, saved.run_id, 0);
          }
        }
      } catch (failure) {
        if (mounted) setError(message(failure));
      }
    }
    void restore();
    return () => {
      mounted = false;
      stream.current?.abort();
    };
  }, [connect, hydrate]);

  async function action(work: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await work();
    } catch (failure) {
      setError(message(failure));
    } finally {
      setBusy(false);
    }
  }
  async function login() {
    await action(async () => {
      const user = await api<components["schemas"]["DemoIdentity"]>(
        "/demo/login",
        undefined,
        "POST",
        { display_name: "旅行者" },
      );
      const session = await api<components["schemas"]["SessionView"]>(
        "/sessions",
        user.token,
        "POST",
      );
      const current = { ...user, session_id: session.session_id };
      remember(current);
      setRun(undefined);
      setHotels(undefined);
      setPlan(undefined);
      setBookings([]);
      setEvents([]);
      setRequest(
        await api<RequestState>(
          `/sessions/${current.session_id}/request`,
          current.token,
        ),
      );
    });
  }
  async function saveConditions(
    fields: Partial<components["schemas"]["TravelConditions"]>,
  ) {
    if (!identity || !request) return;
    await action(async () => {
      const result = await api<components["schemas"]["RequestUpdate"]>(
        `/sessions/${identity.session_id}/request`,
        identity.token,
        "PATCH",
        { expected_revision: request.revision, set: fields },
      );
      setRequest(result.request);
      setHotels(undefined);
      if (plan?.draft_id)
        setPlan(await readDraft(plan.draft_id, identity.token));
      else if (plan)
        setPlan(await api<Plan>(`/plans/${plan.plan_id}`, identity.token));
    });
  }
  async function refresh() {
    if (!identity) return;
    await action(async () => {
      setRequest(
        await api<RequestState>(
          `/sessions/${identity.session_id}/request`,
          identity.token,
        ),
      );
      setHotels(undefined);
      setBookings(
        await api<Booking[]>(
          `/sessions/${identity.session_id}/bookings`,
          identity.token,
        ),
      );
      if (plan)
        setPlan(
          await api<Plan>(
            plan.draft_id
              ? `/plan-drafts/${plan.draft_id}`
              : `/plans/${plan.plan_id}`,
            identity.token,
          ),
        );
    });
  }
  async function send(text: string, mode: "offline" | "live") {
    if (!identity || !text.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      const body = messageInput(identity.pending_message, text, mode);
      remember({ ...identity, pending_message: body });
      const submitted = await api<Run>(
        `/sessions/${identity.session_id}/messages`,
        identity.token,
        "POST",
        body,
      );
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
      if (failure instanceof ApiError && failure.status < 500)
        remember({ ...identity, pending_message: undefined });
      setError(message(failure));
      setBusy(false);
    }
  }
  async function confirm() {
    if (!identity || !plan?.draft_id) return;
    await action(async () => {
      const saved = await api<components["schemas"]["SavedPlan"]>(
        `/plan-drafts/${plan.draft_id}/confirm`,
        identity.token,
        "POST",
      );
      remember({ ...identity, plan_id: saved.plan_id, run_id: undefined });
      setPlan(await api<Plan>(`/plans/${saved.plan_id}`, identity.token));
    });
  }
  async function holdOffer(offerId: string, revision: number) {
    if (!identity) return;
    await action(async () => {
      try {
        await api(
          `/sessions/${identity.session_id}/hotel-holds`,
          identity.token,
          "POST",
          {
            offer_id: offerId,
            expected_revision: revision,
          },
        );
      } finally {
        setBookings(
          await api<Booking[]>(
            `/sessions/${identity.session_id}/bookings`,
            identity.token,
          ),
        );
      }
    });
  }
  async function bookingAction(
    bookingId: string,
    operation: "confirm" | "reconcile",
  ) {
    if (!identity) return;
    await action(async () => {
      try {
        await api(
          `/bookings/${bookingId}/${operation}`,
          identity.token,
          "POST",
        );
      } finally {
        setBookings(
          await api<Booking[]>(
            `/sessions/${identity.session_id}/bookings`,
            identity.token,
          ),
        );
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
    await action(async () => {
      await api(`/plans/${plan.plan_id}/locks`, identity.token, "PATCH", {
        expected_version: plan.version,
        locked_item_ids: [...ids],
      });
      setPlan(await api<Plan>(`/plans/${plan.plan_id}`, identity.token));
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
      try {
        setRun(
          await api<Run>(`/runs/${run.run_id}/cancel`, identity.token, "POST"),
        );
      } catch (failure) {
        setError(message(failure));
      }
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
    busy,
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
