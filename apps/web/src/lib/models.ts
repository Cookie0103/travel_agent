/** Model availability comes from the server; fetching it never starts a paid run. */
import { useEffect, useState } from "react";
import { api } from "./api.ts";
import type { components } from "./api-types";
export type ModelOption = components["schemas"]["ModelOption"];
/** 后端 MessageInput.mode 是唯一来源；本类型只是它的前端别名。 */
export type Mode = components["schemas"]["MessageInput"]["mode"];
export const offlineOption: ModelOption = {
  id: "offline",
  label: "离线演示",
  available: true,
  reason: null,
};
/** 读取失败时离线演示仍可选，但必须告诉用户这不是“服务端只开放离线”。 */
export async function loadModels(
  fetchModels: () => Promise<ModelOption[]> = () =>
    api<ModelOption[]>("/models"),
): Promise<{ options: ModelOption[]; error: string }> {
  try {
    return { options: await fetchModels(), error: "" };
  } catch {
    return {
      options: [offlineOption],
      error: "后端不可用，无法获取模型列表；仅可使用离线演示，请稍后刷新重试。",
    };
  }
}

export function useModels() {
  const [options, setOptions] = useState<ModelOption[]>([offlineOption]);
  const [error, setError] = useState("");
  const [mode, updateMode] = useState<Mode>("offline");
  useEffect(() => {
    let active = true;
    void loadModels().then(({ options: loaded, error: failure }) => {
      if (!active) return;
      setOptions(loaded);
      setError(failure);
      let remembered: string | null = null;
      try {
        remembered =
          sessionStorage.getItem("travel-model-v2") ??
          localStorage.getItem("travel-model-v2");
        if (remembered) sessionStorage.setItem("travel-model-v2", remembered);
        localStorage.removeItem("travel-model-v2");
      } catch {
        /* Storage is optional. */
      }
      updateMode(
        loaded.find((item) => item.id === remembered && item.available)?.id ??
          loaded.find((item) => item.available)?.id ??
          "offline",
      );
    });
    return () => {
      active = false;
    };
  }, []);
  const setMode = (value: Mode) => {
    if (!options.some((item) => item.id === value && item.available)) return;
    updateMode(value);
    try {
      sessionStorage.setItem("travel-model-v2", value);
    } catch {
      /* Storage is optional. */
    }
  };
  return { options, mode, setMode, error };
}
