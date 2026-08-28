import { Link } from "react-router-dom";

export function NotFoundPage() {
  return (
    <section className="empty-page">
      <p className="eyebrow">Not found</p>
      <h1>This page is not in your study plan.</h1>
      <Link className="primary-action compact-action" to="/">Return to Today</Link>
    </section>
  );
}
