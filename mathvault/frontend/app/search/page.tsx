"use client";

import { useState } from "react";
import Link from "next/link";
import { api, SearchHit } from "@/lib/api";

export default function SearchPage() {
  const [q, setQ] = useState("");
  const [docType, setDocType] = useState<string>("");
  const [results, setResults] = useState<SearchHit[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);

  const runSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (!q.trim()) return;
    setLoading(true);
    setSearched(true);
    api.search(q, docType || undefined, 30)
      .then(setResults)
      .catch(() => setResults([]))
      .finally(() => setLoading(false));
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold mb-2">Search</h1>
        <p className="text-slate-600 dark:text-slate-400">
          Search across problems, contests, discussions, and resources.
        </p>
      </div>

      <form onSubmit={runSearch} className="flex gap-2">
        <select
          value={docType}
          onChange={(e) => setDocType(e.target.value)}
          className="px-3 py-2 rounded border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900"
        >
          <option value="">All types</option>
          <option value="problem">Problems</option>
          <option value="contest">Contests</option>
          <option value="page">Pages</option>
          <option value="discussion">Discussions</option>
          <option value="resource">Resources</option>
        </select>
        <input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="e.g., geometry, IMO 2019, number theory…"
          className="flex-1 px-3 py-2 rounded border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900"
          autoFocus
        />
        <button
          type="submit"
          className="px-4 py-2 rounded bg-accent text-white hover:bg-accent-hover"
        >
          Search
        </button>
      </form>

      {loading && <div className="text-slate-500">Searching…</div>}

      {!loading && searched && results.length === 0 && (
        <div className="p-6 rounded border border-slate-200 dark:border-slate-800 text-center text-slate-500">
          No results found.
        </div>
      )}

      {!loading && results.length > 0 && (
        <div className="space-y-3">
          <div className="text-sm text-slate-500">
            {results.length} result(s) • ranked by relevance
          </div>
          <ul className="space-y-3">
            {results.map((r) => (
              <li key={`${r.doc_type}-${r.ref_id}`} className="p-4 rounded border border-slate-200 dark:border-slate-800 hover:border-accent">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <div className="text-xs text-slate-500 uppercase">{r.doc_type}</div>
                    {renderTitle(r)}
                  </div>
                  {r.year && <div className="text-sm text-slate-500">{r.year}</div>}
                </div>
                {r.contest_name && (
                  <div className="text-xs text-slate-500 mt-1">{r.contest_name}</div>
                )}
                {r.snippet && (
                  <div
                    className="text-sm text-slate-600 dark:text-slate-400 mt-2"
                    dangerouslySetInnerHTML={{
                      __html: r.snippet.replace(/<mark>/g, '<mark class="bg-yellow-200 dark:bg-yellow-900">'),
                    }}
                  />
                )}
                {r.tags && (
                  <div className="mt-2 text-xs text-slate-500">Tags: {r.tags}</div>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function renderTitle(r: SearchHit) {
  if (r.doc_type === "problem") {
    return (
      <Link href={`/problems/${r.ref_id}`} className="font-medium hover:underline">
        {r.title || "Untitled Problem"}
      </Link>
    );
  }
  if (r.doc_type === "contest") {
    return (
      <Link href={`/contests/${r.ref_id}`} className="font-medium hover:underline">
        {r.title || "Untitled Contest"}
      </Link>
    );
  }
  return (
    r.url ? (
      <a href={r.url} className="font-medium hover:underline" target="_blank" rel="noreferrer">
        {r.title || r.url}
      </a>
    ) : (
      <span className="font-medium">{r.title || "Untitled"}</span>
    )
  );
}
