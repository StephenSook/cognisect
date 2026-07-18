import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";

import "./globals.css";

const lexend = localFont({
  src: "../../node_modules/@fontsource-variable/lexend/files/lexend-latin-wght-normal.woff2",
  variable: "--font-lexend-family",
  display: "swap",
  fallback: ["Avenir Next", "sans-serif"],
});

const sourceSans = localFont({
  src: [
    {
      path: "../../node_modules/@fontsource-variable/source-sans-3/files/source-sans-3-latin-wght-normal.woff2",
      style: "normal",
    },
    {
      path: "../../node_modules/@fontsource-variable/source-sans-3/files/source-sans-3-latin-wght-italic.woff2",
      style: "italic",
    },
  ],
  variable: "--font-source-sans-family",
  display: "swap",
  fallback: ["Segoe UI", "sans-serif"],
});

const jetbrainsMono = localFont({
  src: "../../node_modules/@fontsource-variable/jetbrains-mono/files/jetbrains-mono-latin-wght-normal.woff2",
  variable: "--font-jetbrains-mono-family",
  display: "swap",
  fallback: ["SFMono-Regular", "monospace"],
});

const description =
  "Teacher-controlled formative assessment for signed-integer subtraction.";

export const metadata: Metadata = {
  title: { default: "COGNISECT", template: "%s | COGNISECT" },
  description,
  openGraph: {
    type: "website",
    title: "COGNISECT",
    description,
    siteName: "COGNISECT",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  colorScheme: "dark light",
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#101313" },
    { media: "(prefers-color-scheme: light)", color: "#efede5" },
  ],
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      className={`${lexend.variable} ${sourceSans.variable} ${jetbrainsMono.variable}`}
      lang="en"
    >
      <body>{children}</body>
    </html>
  );
}
