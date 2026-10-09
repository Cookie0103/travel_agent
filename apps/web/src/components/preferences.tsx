/** Explicit preference editor; saved values are references, current trip conditions take priority. */
"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Identity } from "@/lib/api";
import type { components } from "@/lib/api-types";

type Preferences = components["schemas"]["Preferences"];
const lines = (text: string) =>
  text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

export function PreferencePanel({
  identity,
  onError,
}: {
  identity: Identity;
  onError: (error: unknown) => void;
}) {
  const [saved, setSaved] = useState<Preferences>();
  const [interests, setInterests] = useState("");
  const [constraints, setConstraints] = useState("");
  const [transport, setTransport] = useState<Preferences["transport"]>(null);
  const [busy, setBusy] = useState(true);
  const [status, setStatus] = useState("");
  const generation = useRef(0);

  const display = useCallback((value: Preferences) => {
    setSaved(value);
    setInterests((value.interests ?? []).join("\n"));
    setConstraints((value.soft_constraints ?? []).join("\n"));
    setTransport(value.transport ?? null);
  }, []);

  const load = useCallback(async () => {
    const started = generation.current;
    try {
      const value = await api<Preferences>("/preferences", identity.token);
      if (generation.current === started) display(value);
    } catch (error) {
      if (generation.current === started) onError(error);
    } finally {
      if (generation.current === started) setBusy(false);
    }
  }, [identity.token, onError, display]);

  useEffect(() => {
    ++generation.current;
    // load 的全部 setState 都在 await 之后，规则无法跨 async 边界识别，实为误报。
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
    return () => {
      generation.current += 1;
    };
  }, [load]);

  async function change(clear: boolean) {
    if (!saved || busy) return;
    const started = generation.current;
    setBusy(true);
    setStatus("");
    try {
      const value = await api<Preferences>(
        "/preferences",
        identity.token,
        clear ? "DELETE" : "PATCH",
        {
          expected_revision: saved.revision,
          ...(!clear
            ? {
                set: {
                  interests: lines(interests),
                  soft_constraints: lines(constraints),
                  transport,
                },
              }
            : {}),
        },
      );
      if (generation.current !== started) return;
      display(value);
      setStatus(clear ? "偏好已清除。" : "偏好已保存。");
    } catch (error) {
      if (generation.current === started) onError(error);
    } finally {
      if (generation.current === started) setBusy(false);
    }
  }

  return (
    <section className="preference-panel conversation">
      <div className="section-heading">
        <h2>长期偏好</h2>
        <span className="tag">版本 {saved?.revision ?? "—"}</span>
      </div>
      <p className="muted small">
        仅保存你在这里填写的偏好，本次旅行条件优先。
      </p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void change(false);
        }}
      >
        <label>
          兴趣（每行一项）
          <textarea
            aria-label="长期兴趣"
            value={interests}
            disabled={!saved || busy}
            onChange={(event) => setInterests(event.target.value)}
            rows={2}
          />
        </label>
        <label>
          其他偏好（每行一项）
          <textarea
            aria-label="其他长期偏好"
            value={constraints}
            disabled={!saved || busy}
            onChange={(event) => setConstraints(event.target.value)}
            rows={2}
          />
        </label>
        <label>
          偏好交通
          <select
            aria-label="偏好交通"
            value={transport ?? ""}
            disabled={!saved || busy}
            onChange={(event) =>
              setTransport(
                (event.target.value as Preferences["transport"]) || null,
              )
            }
          >
            <option value="">无偏好</option>
            <option value="walk">步行</option>
            <option value="transit">公共交通</option>
            <option value="taxi">出租车</option>
          </select>
        </label>
        <button type="submit" disabled={!saved || busy}>
          保存偏好
        </button>
        <button
          type="button"
          disabled={!saved || busy}
          onClick={() => void change(true)}
        >
          清除偏好
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            setBusy(true);
            setStatus("");
            void load();
          }}
        >
          读取最新偏好
        </button>
        {status && (
          <p role="status" className="muted small">
            {status}
          </p>
        )}
      </form>
    </section>
  );
}
