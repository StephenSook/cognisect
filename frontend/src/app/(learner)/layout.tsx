export default function LearnerLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <div className="learner-shell">
      <header className="learner-header">
        <span className="learner-brand" aria-label="COGNISECT">
          <span className="brand-mark" aria-hidden="true">
            C
          </span>
          <span>COGNISECT</span>
        </span>
        <p className="learner-boundary">One response · no diagnosis</p>
      </header>
      <main className="learner-main">{children}</main>
    </div>
  );
}
