import { useStatusEvents } from "./useStatusEvents";

export function ProcessingStatus() {
  const { connection } = useStatusEvents();
  const label = connection === "live" ? "Updates live" : connection === "connecting" ? "Connecting updates" : "Updates disconnected · checking periodically";
  return <span className={`processing-status is-${connection}`} aria-live="polite">{label}</span>;
}
