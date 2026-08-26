export function App() {
  return (
    <main className="app-shell">
      <header className="app-header">
        <p className="eyebrow">Private study workspace</p>
        <h1>TAM Forge</h1>
      </header>
      <section aria-live="polite" className="loading-state">
        <p>Loading your study workspace…</p>
      </section>
    </main>
  );
}
