/** Explicit preference editor; saved values are references, current trip conditions take priority. */
"use client";
import { Button } from "./ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "./ui/popover";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Identity } from "@/lib/api";
import type { components } from "@/lib/api-types";
import {
  type MemoryFact,
  memoryLabels,
  memoryValue,
  memorySources,
} from "@/lib/memory";
import { formatTokyo } from "@/lib/format-time";
import {
  factGroups,
  factStatus,
  isDirty,
  preferenceLines as lines,
} from "@/lib/preference-form";

type Preferences = components["schemas"]["Preferences"];
type UserProfile = components["schemas"]["UserProfileView"];
export function PreferencePanel({
  identity,
  onError,
  refreshKey,
  active = true,
  onChanged,
}: {
  identity: Identity;
  onError: (error: unknown) => void;
  refreshKey?: string;
  /** False while the surrounding <details> is collapsed: no background reloads. */
  active?: boolean;
  onChanged: () => void;
}) {
  const [saved, setSaved] = useState<Preferences>();
  const [facts, setFacts] = useState<MemoryFact[]>([]);
  const [profile, setProfile] = useState<UserProfile>();
  const [interests, setInterests] = useState("");
  const [constraints, setConstraints] = useState("");
  const [transport, setTransport] = useState<Preferences["transport"]>(null);
  const [busy, setBusy] = useState(true);
  const [status, setStatus] = useState("");
  const [confirmClear, setConfirmClear] = useState(false);
  const generation = useRef(0);
  const dirty = isDirty(saved, { interests, constraints, transport });
  const dirtyRef = useRef(false);
  useEffect(() => {
    dirtyRef.current = dirty;
  }, [dirty]);

  const display = useCallback((value: Preferences) => {
    setSaved(value);
    setInterests((value.interests ?? []).join("\n"));
    setConstraints((value.soft_constraints ?? []).join("\n"));
    setTransport(value.transport ?? null);
  }, []);

  // Background refreshes keep unsaved edits (and the revision they were based on);
  // only the explicit "read latest" button overwrites the form.
  const load = useCallback(
    async (force = false) => {
      const started = generation.current;
      try {
        const [value, rows, summary] = await Promise.all([
          api<Preferences>("/preferences", identity.token),
          api<MemoryFact[]>("/memory?include_history=true", identity.token),
          api<UserProfile>("/profile-summary", identity.token),
        ]);
        if (generation.current === started) {
          if (force || !dirtyRef.current) display(value);
          setFacts(rows);
          setProfile(summary);
        }
      } catch (error) {
        if (generation.current === started) onError(error);
      } finally {
        if (generation.current === started) setBusy(false);
      }
    },
    [identity.token, onError, display],
  );

  useEffect(() => {
    if (!active) return;
    ++generation.current;
    // load 的全部 setState 都在 await 之后，规则无法跨 async 边界识别，实为误报。
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
    return () => {
      generation.current += 1;
    };
  }, [load, refreshKey, active]);

  async function change(clear: boolean) {
    if (!saved || busy) return;
    const started = ++generation.current;
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
      setProfile(undefined);
      const [rows, summary] = await Promise.all([
        api<MemoryFact[]>("/memory?include_history=true", identity.token),
        api<UserProfile>("/profile-summary", identity.token),
      ]);
      if (generation.current !== started) return;
      setFacts(rows);
      setProfile(summary);
      onChanged();
      setStatus(clear ? "偏好已清除。" : "偏好已保存。");
    } catch (error) {
      if (generation.current === started) onError(error);
    } finally {
      if (generation.current === started) setBusy(false);
    }
  }

  async function updateProfile() {
    if (!saved || busy || !profile?.can_update) return;
    const started = ++generation.current;
    setBusy(true);
    try {
      const summary = await api<UserProfile>(
        "/profile-summary",
        identity.token,
        "POST",
        { expected_revision: saved.revision },
      );
      if (generation.current !== started) return;
      setProfile(summary);
      setStatus(summary.text ? "画像已更新" : "还没有已确认的长期偏好");
      onChanged();
    } catch (error) {
      if (generation.current === started) onError(error);
    } finally {
      if (generation.current === started) setBusy(false);
    }
  }

  async function forget(fact: MemoryFact) {
    if (!saved || busy) return;
    const started = ++generation.current;
    setBusy(true);
    setStatus("");
    try {
      const value = await api<Preferences>(
        `/memory/${fact.fact_id}`,
        identity.token,
        "DELETE",
        { expected_revision: saved.revision },
      );
      if (generation.current !== started) return;
      display(value);
      setProfile(undefined);
      const [rows, summary] = await Promise.all([
        api<MemoryFact[]>("/memory?include_history=true", identity.token),
        api<UserProfile>("/profile-summary", identity.token),
      ]);
      if (generation.current !== started) return;
      setFacts(rows);
      setProfile(summary);
      onChanged();
      setStatus("这条偏好已删除；聊天记录仍保留，只是不再用于推荐。");
    } catch (error) {
      if (generation.current === started) onError(error);
    } finally {
      if (generation.current === started) setBusy(false);
    }
  }

  function factRow(fact: MemoryFact) {
    return (
      <li key={fact.fact_id}>
        <p>
          <strong>
            {memoryLabels[fact.key]}：{memoryValue(fact)}
          </strong>{" "}
          · {factStatus(fact, identity.session_id)} ·{" "}
          {fact.scope === "trip" ? "这次旅行" : "长期"}
        </p>
        <p className="muted small">
          {memorySources[fact.source]}
          {fact.valid_from ? ` · 生效于 ${formatTokyo(fact.valid_from)}` : ""}
          {fact.invalidated_at
            ? ` · 失效于 ${formatTokyo(fact.invalidated_at)}`
            : ""}
        </p>
        {fact.evidence_quote && (
          <p className="muted small">原话：{fact.evidence_quote}</p>
        )}
        {fact.superseded_by && <p className="muted small">已由新版本取代。</p>}
        {fact.status !== "deleted" && (
          <Button
            variant="outline"
            disabled={busy || !saved}
            type="button"
            onClick={() => void forget(fact)}
            aria-label={`删除${memoryLabels[fact.key]}：${memoryValue(fact)}`}
          >
            删除
          </Button>
        )}
      </li>
    );
  }
  const {
    current: currentFacts,
    elsewhere,
    history,
  } = factGroups(facts, identity.session_id);

  return (
    <section className="preference-panel conversation">
      <div className="section-heading">
        <h2>长期偏好</h2>
        <span className="tag">版本 {saved?.revision ?? "—"}</span>
      </div>
      <p className="muted small">
        你填写的偏好和在对话中逐条确认的偏好会保存。本次旅行条件优先。
      </p>
      <ul aria-label="已保存与待确认的偏好">{currentFacts.map(factRow)}</ul>
      {elsewhere.length > 0 && (
        <details>
          <summary>其他旅行的临时偏好（{elsewhere.length}）</summary>
          <ul>{elsewhere.map(factRow)}</ul>
        </details>
      )}
      {history.length > 0 && (
        <details>
          <summary>查看历史版本（{history.length}）</summary>
          <ul>{history.map(factRow)}</ul>
        </details>
      )}
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
        <Button variant="outline" type="submit" disabled={!saved || busy}>
          保存偏好
        </Button>
        <Popover open={confirmClear} onOpenChange={setConfirmClear}>
          <PopoverTrigger asChild>
            <Button variant="outline" type="button" disabled={!saved || busy}>
              清除偏好
            </Button>
          </PopoverTrigger>
          <PopoverContent>
            <p>清除全部长期偏好和历史记录？此操作不能撤销。</p>
            <Button
              variant="outline"
              type="button"
              onClick={() => {
                setConfirmClear(false);
                void change(true);
              }}
            >
              确认清除
            </Button>
            <Button
              variant="outline"
              type="button"
              onClick={() => setConfirmClear(false)}
            >
              取消
            </Button>
          </PopoverContent>
        </Popover>
        <Button
          variant="outline"
          type="button"
          disabled={busy}
          onClick={() => {
            setBusy(true);
            setStatus("");
            void load(true);
          }}
        >
          读取最新偏好
        </Button>
        <Button
          variant="outline"
          type="button"
          disabled={!saved || busy || !profile?.can_update}
          onClick={() => void updateProfile()}
        >
          更新我的画像
        </Button>
        {profile?.text && (
          <p className="small">
            {profile.text.replace(/\s*\[fact:[0-9a-f-]+\]/gi, "")}
            <span className="muted">（依据已确认的长期偏好）</span>
          </p>
        )}
        {status && (
          <p role="status" className="muted small">
            {status}
          </p>
        )}
      </form>
    </section>
  );
}
