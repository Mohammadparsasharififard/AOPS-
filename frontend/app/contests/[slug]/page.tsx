"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";

export default function ContestDetailPage() {
  const params = useParams<{ slug: string }>();
  const [contest, setContest] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!params?.slug) return;
    api.contest(params.slug)
      .then(setContest)
      .finally(() => setLoading(false));
  }, [params?.slug]);

  if (loading) return <div className="text-slate-500">Loading…</div>;
  if (!contest) return <div className="text-slate-500">Contest not found.</div>;

  return (
    <div className="space-y-6">
      <div>
        <div className="text-sm text-slate-500">
          <Link href="/contests" className="hover:underline">Contests</Link> / {contest.name}
        </div>
        <h1 className="text-2xl font-bold mt-2">{contest.name}</h1>
        {contest.category && (
          <div className="text-sm text-slate-500 mt-1">Category: {contest.category}</div>
        )}
        {contest.country && (
          <div className="text-sm text-slate-500">Country/Region: {contest.country}</div>
        )}
        {contest.source_url && (
          <a
            href={contest.source_url}
            className="text-sm text-accent hover:underline inline-block mt-2"
            rel="noopener noreferrer"
          >
            View source page (external)
          </a>
        )}
      </div>

      <div>
        <h2 className="text-xl font-semibold mb-3">Years</h2>
        {contest.years.length === 0 ? (
          <div className="text-slate-500">No years archived yet.</div>
        ) : (
          <div className="grid gap-2 md:grid-cols-3">
            {contest.years.map((y: any) => (
              <Link
                key={y.id}
                href={`/contests/${contest.slug}/${y.year}`}
                className="block p-3 rounded border border-slate-200 dark:border-slate-800 hover:border-accent hover:bg-slate-50 dark:hover:bg-slate-900"
              >
                <div className="font-medium">
                  {y.year}
                  {y.round && <span className="text-slate-500 ml-2 text-sm">({y.round})</span>}
                </div>
                <div className="text-xs text-slate-500 mt-1">
                  {y.problem_count || 0} problem(s) • {y.problem_set_count} pack(s)
                </div>
                {y.date && (
                  <div className="text-xs text-slate-500">Date: {y.date}</div>
                )}
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
