import { useState } from "react";
import type { SelfReviewInput } from "./api";

const empty: SelfReviewInput = { main_answer: "", did_well: "", structure_weakness: "", vague_points: "", hesitation_points: "", change_next: "", self_score: 0 };

export function SelfReviewForm({ busy, onSubmit }: { busy: boolean; onSubmit: (review: SelfReviewInput) => void }) {
  const [review, setReview] = useState(empty);
  const set = (name: keyof SelfReviewInput, value: string | number) => setReview((current) => ({ ...current, [name]: value }));
  const complete = Object.entries(review).every(([key, value]) => key === "self_score" || String(value).trim());
  return (
    <section className="self-review-form" id="self-review" aria-labelledby="self-review-title">
      <header><p className="section-label">Before AI feedback</p><h2 id="self-review-title">Mandatory self-review</h2><p>Your score remains separate from the future AI score.</p></header>
      {[
        ["Main answer or decision", "main_answer"], ["What I did well", "did_well"], ["Where structure was weak", "structure_weakness"],
        ["Where I became vague", "vague_points"], ["Where I hesitated", "hesitation_points"], ["What I will change", "change_next"],
      ].map(([label, name]) => <label className="editor-field" key={name}><span>{label}</span><textarea rows={3} value={String(review[name as keyof SelfReviewInput])} onChange={(event) => set(name as keyof SelfReviewInput, event.target.value)} /></label>)}
      <label className="score-field"><span>My self-score</span><select value={review.self_score} onChange={(event) => set("self_score", Number(event.target.value))}>{[0, 1, 2, 3, 4].map((score) => <option value={score} key={score}>{score} — {score === 0 ? "not demonstrated" : score === 1 ? "heavily assisted" : score === 2 ? "developing" : score === 3 ? "independent" : "strong under pressure"}</option>)}</select></label>
      <button className="primary-button" type="button" disabled={busy || !complete} onClick={() => onSubmit(review)}>Submit self-review</button>
    </section>
  );
}
