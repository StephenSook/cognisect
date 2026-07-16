import type { Metadata } from "next";
import Link from "next/link";

import "./globals.css";

export const metadata: Metadata = {
  title: { default: "COGNISECT", template: "%s | COGNISECT" },
  description: "Teacher-controlled formative assessment for signed-integer subtraction.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <header>
          <nav aria-label="Primary navigation">
            <Link href="/">COGNISECT</Link>
            <Link href="/lab">Lab</Link>
            <Link href="/runtime">Runtime evidence</Link>
          </nav>
        </header>
        <main>{children}</main>
      </body>
    </html>
  );
}
