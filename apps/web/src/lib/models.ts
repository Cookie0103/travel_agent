/** Model availability comes from the server; fetching it never starts a paid run. */
import { useEffect, useState } from "react";
import { api } from "./api";

export type Mode = "offline" | "deepseek" | "claude";
export type ModelOption = {
  id: Mode;
  label: string;
  available: boolean;
  reason: string | null;
};
export const offlineOption: ModelOption = {
  id: "offline",
  label: "离线演示",
  available: true,
  reason: null,
};
export const modeLabel = (mode: string) =>
  (
    ({
      offline: "离线演示",
      deepseek: "DeepSeek",
      claude: "Claude",
      live: "实时（旧）",
    }) as Record<string, string>
  )[mode] ?? mode;

export function useModels() {
  const [options, setOptions] = useState<ModelOption[]>([offlineOption]);
  const [mode, updateMode] = useState<Mode>("offline");
  useEffect(() => {
    let active = true;
    void api<ModelOption[]>("/models")
      .catch(() => [offlineOption])
      .then((loaded) => {
        if (!active) return;
        setOptions(loaded);
        let remembered: string | null = null;
        try {
          remembered = localStorage.getItem("travel-model-v2");
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
      localStorage.setItem("travel-model-v2", value);
    } catch {
      /* Storage is optional. */
    }
  };
  return { options, mode, setMode };
}
