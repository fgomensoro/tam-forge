export function ActiveRoleBadge({ role }: { role: string | null }) {
  return (
    <div className="role-badge" aria-label={`Active AI role: ${role ?? "None"}`}>
      <span className="role-light" aria-hidden="true" />
      <span>AI role · {role ?? "None"}</span>
    </div>
  );
}
