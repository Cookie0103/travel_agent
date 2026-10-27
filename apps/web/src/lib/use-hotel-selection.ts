/** Reads the server's per-segment hotel selection state; failures just hide the skip button. */
"use client";
import { useEffect, useState } from "react";
import { api, type Identity } from "./api";
import type { HotelSelectionView } from "./hotel-flow";

export function useHotelSelection(
  identity: Pick<Identity, "session_id" | "token"> | undefined,
  refreshKey: string,
) {
  const [view, setView] = useState<{
    session_id: string;
    value?: HotelSelectionView;
  }>();
  const session = identity?.session_id;
  const token = identity?.token;
  useEffect(() => {
    if (!session || !token) return;
    let active = true;
    api<HotelSelectionView>(`/sessions/${session}/hotel-selection`, token)
      .then((value) => active && setView({ session_id: session, value }))
      .catch(() => active && setView({ session_id: session }));
    return () => {
      active = false;
    };
  }, [session, token, refreshKey]);
  return view && view.session_id === session ? view.value : undefined;
}
