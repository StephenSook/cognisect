"use client";

export default function ErrorPage({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <article>
      <h1>Current state is unavailable</h1>
      <p role="alert">The service could not load this page. No workflow claim is being made.</p>
      <button type="button" onClick={reset}>
        Try again
      </button>
    </article>
  );
}
