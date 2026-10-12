"use client";
import Link from "next/link";
export default function NotFound() {
  return (
    <div className="empty">
      <h1>Page not found</h1>
      <p>This page doesn&apos;t exist or you don&apos;t have access to it.</p>
      <Link className="button button-primary" href="/">
        Go to overview
      </Link>
    </div>
  );
}
