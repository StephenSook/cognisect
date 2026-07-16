import Link from "next/link";

export default function NotFound() {
  return (
    <article>
      <h1>Resource not found</h1>
      <p>The resource is unavailable or is not owned by this browser.</p>
      <Link href="/lab">Return to the teacher lab</Link>
    </article>
  );
}
