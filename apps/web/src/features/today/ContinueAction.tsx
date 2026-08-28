import { Link } from "react-router-dom";
import type { TodayContinue } from "./api";

function destination(action: TodayContinue) {
  if (["review_feedback"].includes(action.kind)) return `/evidence/activities/${action.target_id}`;
  if (action.kind === "close_day") return `/?close=${action.target_id}#daily-close`;
  const suffix = action.kind === "complete_self_review" ? "#self-review" : "";
  return `/activities/${action.target_id}${suffix}`;
}

export function ContinueAction({ action }: { action: TodayContinue }) {
  return (
    <Link className="continue-action" to={destination(action)} aria-label={`Continue: ${action.label}`}>
      <span>
        <small>Continue</small>
        <strong>{action.label}</strong>
      </span>
      <span aria-hidden="true">→</span>
    </Link>
  );
}
