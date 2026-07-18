import Link from "next/link";

export default function TeacherLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <>
      <header className="site-header">
        <nav className="site-nav" aria-label="Primary navigation">
          <Link className="brand" href="/">
            <img className="brand-mark brand-logo" src="/branding/cognisect-logo.png" alt="" aria-hidden="true" />
            <span>COGNISECT</span>
          </Link>
          <div className="nav-links">
            <Link href="/lab">Lab</Link>
            <Link href="/runtime">Runtime evidence</Link>
          </div>
          <span className="nav-status">
            <span aria-hidden="true" /> Signed integers · registry v1
          </span>
        </nav>
      </header>
      <main className="site-main">{children}</main>
      <footer className="site-footer">
        <p>Teacher-controlled evidence · no cognitive-state claims</p>
        <p className="mono">COGNISECT / EDUCATION / 2026</p>
      </footer>
    </>
  );
}
