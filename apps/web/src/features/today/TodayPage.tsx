import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { getToday, localIsoDate } from "./api";
import { ContinueAction } from "./ContinueAction";
import { DailyCloseForm } from "./DailyCloseForm";
import { TaskCard } from "./TaskCard";

const todayKey = (date: string) => ["today", date] as const;

function formatTime(value: string) {
  return new Intl.DateTimeFormat(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" }).format(new Date(value));
}

export function TodayPage() {
  const date = localIsoDate();
  const [searchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: todayKey(date), queryFn: () => getToday(date) });

  useEffect(() => {
    const refresh = (event: Event) => {
      const detail = (event as CustomEvent<{ query?: string }>).detail;
      if (!detail?.query || detail.query === "today") void queryClient.invalidateQueries({ queryKey: todayKey(date) });
    };
    window.addEventListener("tamforge:status", refresh);
    return () => window.removeEventListener("tamforge:status", refresh);
  }, [date, queryClient]);

  if (query.isPending) return <p role="status">Preparing today…</p>;
  if (query.isError || !query.data) return (
    <section className="today-page" aria-labelledby="today-title">
      <header><p className="eyebrow">Your learning day</p><h1 id="today-title">Today</h1></header>
      <p className="workflow-error" role="alert">Today could not be loaded. Your roadmap and saved evidence are unchanged.</p>
    </section>
  );
  const today = query.data;

  return (
    <section className="today-page" aria-labelledby="today-title">
      <header className="today-hero">
        <div>
          <p className="eyebrow">Your learning day</p>
          <h1 id="today-title">Today</h1>
          <p className="roadmap-position">Month {today.roadmap.month} · Week {today.roadmap.week} · Day {today.roadmap.day}</p>
        </div>
        <div className="day-timebox" aria-label="Daily time policy">
          <strong>{today.total_planned_minutes} planned minutes</strong>
          <span>{today.time_policy.focused_minutes} focused · hard stop {today.time_policy.hard_stop_minutes}</span>
        </div>
      </header>

      {today.day_type === "sunday" ? (
        <section className="off-day-card">
          <p className="section-label">Protected rest</p>
          <h2>Sunday is off.</h2>
          <p>No study, catch-up, or study reminders. Background processing may continue.</p>
        </section>
      ) : (
        <>
          {today.day_type === "saturday" ? <p className="assessment-cap">Saturday · 120-minute maximum</p> : null}
          {today.time_policy.hard_stop_recommended ? <p className="hard-stop-notice">The day hard stop has been reached. Save safely and stop; TAM Forge will not add work.</p> : null}
          {today.primary_continue ? <ContinueAction action={today.primary_continue} /> : null}
          {today.primary_continue?.kind === "close_day" && searchParams.get("close") === String(today.primary_continue.target_id) ? (
            <DailyCloseForm today={today} onClosed={() => void queryClient.invalidateQueries({ queryKey: todayKey(date) })} />
          ) : null}

          <section className="today-support-grid" aria-label="Items needing attention">
            <article>
              <p className="section-label">Two corrections maximum</p>
              <h2>Carryovers</h2>
              {today.corrections.length ? <ol>{today.corrections.map((item) => <li key={item.id}><span>{item.priority}</span>{item.instruction}</li>)}</ol> : <p>None due today.</p>}
            </article>
            <article>
              <p className="section-label">Real interviews</p>
              <h2>Scheduled</h2>
              {today.interviews.length ? <ul>{today.interviews.map((item) => <li key={item.id}><strong>{item.company} · {item.role} · {item.stage}</strong><span>{formatTime(item.starts_at)} · {item.expected_duration_minutes} minutes</span></li>)}</ul> : <p>No interview scheduled today.</p>}
            </article>
            <article>
              <p className="section-label">Independent reflection</p>
              <h2>Self-review due</h2>
              {today.awaiting_self_reviews.length ? <ul>{today.awaiting_self_reviews.map((item) => <li key={item.activity_id}><Link to={`/activities/${item.activity_id}#self-review`}>{item.objective}</Link></li>)}</ul> : <p>Nothing waiting.</p>}
            </article>
            <article>
              <p className="section-label">Asynchronous analysis</p>
              <h2>Feedback status</h2>
              {today.analyses.length ? <ul>{today.analyses.map((item) => <li key={item.activity_id}><Link to={`/activities/${item.activity_id}`}>{item.state === "ready" ? "Feedback ready" : "Processing needs attention"}</Link></li>)}</ul> : <p>No new analysis.</p>}
            </article>
          </section>

          <section className="today-tasks" aria-labelledby="tasks-title">
            <header><p className="section-label">Stable roadmap spine</p><h2 id="tasks-title">Required work</h2></header>
            {today.tasks.map((task) => <TaskCard key={task.activity_id} task={task} />)}
          </section>
        </>
      )}
    </section>
  );
}
