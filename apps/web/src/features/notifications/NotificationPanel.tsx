import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getNotifications, isAllowedNotification, markNotificationRead, type NotificationPage } from "./api";

const copy = {
  feedback_ready: { label: "Feedback ready", detail: "Your asynchronous review is ready." },
  correction_due: { label: "Correction due", detail: "One planned correction is ready for its assigned slot." },
  upcoming_real_interview: { label: "Upcoming real interview", detail: "Review the interview plan without adding extra study time." },
  saturday_assessment: { label: "Saturday assessment", detail: "Your no-AI assessment is ready within the 120-minute limit." },
  processing_failure_requires_action: { label: "Processing needs action", detail: "Study can continue independently. Your source evidence remains saved." },
} as const;

export function NotificationPanel() {
  const [open, setOpen] = useState(false);
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ["notifications"], queryFn: getNotifications });
  const mutation = useMutation({
    mutationFn: markNotificationRead,
    onMutate: async (id) => {
      await queryClient.cancelQueries({ queryKey: ["notifications"] });
      const previous = queryClient.getQueryData<NotificationPage>(["notifications"]);
      queryClient.setQueryData<NotificationPage>(["notifications"], (page) => page ? {
        ...page,
        items: page.items.map((item) => item.id === id ? { ...item, read_at: new Date().toISOString() } : item),
      } : page);
      return { previous };
    },
    onError: (_error, _id, context) => queryClient.setQueryData(["notifications"], context?.previous),
    onSuccess: (read) => queryClient.setQueryData<NotificationPage>(["notifications"], (page) => page ? {
      ...page,
      items: page.items.map((item) => item.id === read.id ? read : item),
    } : page),
  });
  const items = (query.data?.items ?? []).filter((item) => isAllowedNotification(String(item.notification_type)));
  const unread = items.filter((item) => !item.read_at).length;

  return (
    <div className="notification-control">
      <button className="notification-toggle" type="button" aria-expanded={open} aria-controls="notification-panel" onClick={() => setOpen((value) => !value)}>
        Notifications{unread ? ` · ${unread}` : ""}
      </button>
      {open ? <section className="notification-panel" id="notification-panel" aria-label="Notifications">
        <header><p className="section-label">Action only</p><h2>Notifications</h2></header>
        {query.isPending ? <p role="status">Loading notifications…</p> : null}
        {query.isError ? <p className="workflow-error" role="alert">Notifications are unavailable. Study can continue independently.</p> : null}
        {items.length ? <ul>{items.map((item) => {
          const message = copy[item.notification_type];
          return <li key={item.id} className={item.read_at ? "is-read" : ""}>
            <div><strong>{message.label}</strong><p>{message.detail}</p></div>
            {!item.read_at ? <button className="text-button" type="button" aria-label={`Mark ${message.label} as read`} onClick={() => mutation.mutate(item.id)}>Mark read</button> : null}
          </li>;
        })}</ul> : !query.isPending && !query.isError ? <p>Nothing needs your attention.</p> : null}
        <p className="notification-policy">Only feedback, corrections, interviews, Saturday assessments, and failures requiring action appear here.</p>
      </section> : null}
    </div>
  );
}
