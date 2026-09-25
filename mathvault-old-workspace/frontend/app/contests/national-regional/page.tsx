"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, Contest } from "@/lib/api";

export default function NationalRegionalContestsPage() {
  const [contests, setContests] = useState<Contest[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.contests({ international: false })
      .then(setContests)
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <div className="text-sm text-slate-500">
          <Link href="/contests" className="hover:underline">Contests</Link> / National & Regional
        </div>
        <h1 className="text-2xl font-bold mt-2">National & Regional Contests</h1>
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
              <div className="font-medium">{c.name}</div>
              {c.country && (
                <div className="text-xs text-slate-500 mt-1">{c.country}</div>
              )}
              {c.category && (
                <div className="text-xs text-slate-500">{c.category}</div>
              )}
              <div className="mt-2 text-xs text-slate-500">
                {c.year_count} year(s) • {c.last_synced ? `synced ${new Date(c.last_synced).toLocaleDateString()}` : "never synced"}
              </div>
            </Link>
          ))}
        </div>
      )}

      <div className="mt-8">
        <Link href="/countries" className="text-accent hover:underline">
          Browse by country / region →
        </Link>
      </div>
    </div>
  );
}
