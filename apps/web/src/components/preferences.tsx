/** Read-only list of remembered preferences (items deletable one by one); current trip conditions take priority. */
"use client";
import { Button } from "./ui/button";
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
import { factGroups, factStatus } from "@/lib/preference-form";

type Preferences = components["schemas"]["Preferences"];
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
  const [busy, setBusy] = useState(true);
  const [status, setStatus] = useState("");
  const generation = useRef(0);
  const load = useCallback(async () => {
    const started = generation.current;
    try {
      const [value, rows] = await Promise.all([
        api<Preferences>("/preferences", identity.token),
        api<MemoryFact[]>("/memory?include_history=true", identity.token),
      ]);
      if (generation.current === started) {
        setSaved(value);
        setFacts(rows);
      }
    } catch (error) {
      if (generation.current === started) onError(error);
    } finally {
      if (generation.current === started) setBusy(false);
    }
  }, [identity.token, onError]);

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
      setSaved(value);
      const rows = await api<MemoryFact[]>(
        "/memory?include_history=true",
        identity.token,
      );
      if (generation.current !== started) return;
      setFacts(rows);
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
        在对话中逐条确认的偏好会保存，可随时删除。本次旅行条件优先。
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
      {status && (
        <p role="status" className="muted small">
          {status}
        </p>
      )}
    </section>
  );
}
