export default function LearnerLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <div className="learner-shell">
      <header className="learner-header">
        <span className="learner-brand" aria-label="COGNISECT">
          <img className="brand-mark brand-logo" src="/branding/cognisect-logo.png" alt="" aria-hidden="true" />
          <span>COGNISECT</span>
        </span>
        <p className="learner-boundary">One response · no diagnosis</p>
      </header>
      <main className="learner-main">{children}</main>
    </div>
  );
}
