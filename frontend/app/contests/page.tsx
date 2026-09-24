"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, Contest } from "@/lib/api";

export default function ContestsPage() {
  const [contests, setContests] = useState<Contest[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<"all" | "international" | "national">("all");

  useEffect(() => {
    setLoading(true);
    const params = filter === "international" ? { international: true }
      : filter === "national" ? { international: false }
      : {};
    api.contests(params)
      .then(setContests)
      .finally(() => setLoading(false));
  }, [filter]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold mb-2">Contests</h1>
        <p className="text-slate-600 dark:text-slate-400">
          All archived competitions — international and national/regional.
        </p>
      </div>

      <div className="flex gap-2">
        {(["all", "international", "national"] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-3 py-1.5 rounded text-sm border ${
              filter === f
                ? "bg-accent text-white border-accent"
                : "border-slate-200 dark:border-slate-800 hover:bg-slate-100 dark:hover:bg-slate-800"
            }`}
          >
            {f === "all" ? "All" : f === "international" ? "International" : "National & Regional"}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="text-slate-500">Loading…</div>
      ) : contests.length === 0 ? (
        <div className="p-6 rounded border border-slate-200 dark:border-slate-800 text-center text-slate-500">
          No contests archived yet. Run <code>mathvault crawl</code> to start archiving.
        </div>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {contests.map((c) => (
            <Link
              key={c.id}
              href={`/contests/${c.slug}`}
              className="block p-4 rounded border border-slate-200 dark:border-slate-800 hover:border-accent hover:bg-slate-50 dark:hover:bg-slate-900"
            >
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="font-medium">{c.name}</div>
                  {c.category && (
                    <div className="text-xs text-slate-500 mt-1">{c.category}</div>
                  )}
                  {c.country && (
                    <div className="text-xs text-slate-500">{c.country}</div>
                  )}
                </div>
                <span className="text-xs px-2 py-1 rounded bg-slate-100 dark:bg-slate-800">
                  {c.is_international ? "Intl." : "Nat."}
                </span>
              </div>
              <div className="mt-3 text-xs text-slate-500">
                {c.year_count} year(s) • {c.last_synced ? `synced ${new Date(c.last_synced).toLocaleDateString()}` : "never synced"}
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
