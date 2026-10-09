/** Reuse already-read request facts for the same trip's label, without changing saved-plan metadata. */
import type { RequestState, TripSummary } from "./api";

export function updateTripSummary(
  trips: TripSummary[],
  sessionId: string,
  request: RequestState,
): TripSummary[] {
  return trips.map((trip) =>
    trip.session_id === sessionId
      ? {
          ...trip,
          city: request.city ?? null,
          start_date: request.start_date ?? null,
          end_date: request.end_date ?? null,
        }
      : trip,
  );
}
