import type { TripSummary } from "./api";

/** Absence is only known after a successful, authenticated list with no remaining page. */
export function savedTripList(
  trips: readonly TripSummary[],
  state: {
    identityPresent: boolean;
    restoring: boolean;
    busy: boolean;
    error: string;
    nextCursor: string | null;
  },
) {
  const items = trips.filter(
    (trip) => trip.plan_id && trip.current_version && trip.current_version > 0,
  );
  const phase =
    state.restoring || state.busy
      ? "loading"
      : state.error
        ? "error"
        : !state.identityPresent
          ? "identity_missing"
          : items.length
            ? "ready"
            : state.nextCursor
              ? "more"
              : "empty";
  return { items, phase };
}
