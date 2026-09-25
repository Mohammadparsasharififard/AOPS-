"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, Problem } from "@/lib/api";

export default function ProblemsPage() {
  const [problems, setProblems] = useState<Problem[]>([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const limit = 50;

  useEffect(() => {
    setLoading(true);
    const t = setTimeout(() => {
      api.problems({ q: q || undefined, limit, offset })
        .then(setProblems)
        .finally(() => setLoading(false));
    }, 300);
    return () => clearTimeout(t);
  }, [q, offset]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold mb-2">Problems</h1>
        <p className="text-slate-600 dark:text-slate-400">
          Search archived problems. Full-text search is also available on the Search page.
        </p>
      </div>

      <input
        type="search"
        value={q}
        onChange={(e) => { setQ(e.target.value); setOffset(0); }}
        placeholder="Filter by title…"
        className="w-full px-3 py-2 rounded border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900"
      />

      {loading ? (
        <div className="text-slate-500">Loading…</div>
      ) : problems.length === 0 ? (
        <div className="p-6 rounded border border-slate-200 dark:border-slate-800 text-center text-slate-500">
          No problems archived yet. Run <code>mathvault crawl</code> to start.
        </div>
      ) : (
        <ul className="divide-y divide-slate-200 dark:divide-slate-800">
          {problems.map((p) => (
            <li key={p.id}>
              <Link
                href={`/problems/${p.id}`}
                className="block py-3 hover:bg-slate-50 dark:hover:bg-slate-900"
              >
                <div className="flex items-center gap-3">
                  <span className="text-sm text-slate-500 w-20">Problem {p.number}</span>
                  <span className="font-medium flex-1">{p.title || "(untitled)"}</span>
                  <span className="text-sm text-slate-500">
                    {p.contest_name} {p.year}
                  </span>
                  <ArchiveBadge status={p.archive_status} />
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}

      <div className="flex gap-2 justify-center">
        <button
          onClick={() => setOffset(Math.max(0, offset - limit))}
          disabled={offset === 0}
          className="px-3 py-1.5 rounded border border-slate-200 dark:border-slate-800 disabled:opacity-50"
        >
          ← Previous
        </button>
        <span className="px-3 py-1.5 text-slate-500 text-sm">
          {offset + 1}–{offset + problems.length}
        </span>
        <button
          onClick={() => setOffset(offset + limit)}
          disabled={problems.length < limit}
          className="px-3 py-1.5 rounded border border-slate-200 dark:border-slate-800 disabled:opacity-50"
        >
          Next →
        </button>
      </div>
    </div>
  );
}

function ArchiveBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    archived: "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300",
    partial: "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300",
    failed: "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300",
    not_archived: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400",
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded ${colors[status] || colors.not_archived}`}>
      {status.replace(/_/g, " ")}
    </span>
  );
}
