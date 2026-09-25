"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";

export default function ContestYearDetailPage() {
  const params = useParams<{ slug: string; year: string }>();
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!params?.slug || !params?.year) return;
    api.contestYear(params.slug, parseInt(params.year, 10))
      .then(setData)
      .finally(() => setLoading(false));
  }, [params?.slug, params?.year]);

  if (loading) return <div className="text-slate-500">Loading…</div>;
  if (!data) return <div className="text-slate-500">Year not found.</div>;

  return (
    <div className="space-y-6">
      <div>
        <div className="text-sm text-slate-500">
          <Link href="/contests" className="hover:underline">Contests</Link> /
          {" "}
          <Link href={`/contests/${data.contest_slug}`} className="hover:underline">{data.contest_name}</Link> /
          {" "}
          {data.year}
        </div>
        <h1 className="text-2xl font-bold mt-2">
          {data.contest_name} {data.year}
        </h1>
        {data.round && <div className="text-slate-500 text-sm mt-1">Round: {data.round}</div>}
        {data.date && <div className="text-slate-500 text-sm">Date: {data.date}</div>}
        {data.duration && <div className="text-slate-500 text-sm">Duration: {data.duration}</div>}
      </div>

      <div className="grid md:grid-cols-2 gap-6">
        <div>
          <h2 className="text-xl font-semibold mb-3">Problems</h2>
          {data.problems.length === 0 ? (
            <div className="text-slate-500 text-sm">No problems archived.</div>
          ) : (
            <ul className="space-y-1">
              {data.problems.map((p: any) => (
                <li key={p.id}>
                  <Link
                    href={`/problems/${p.id}`}
                    className="block p-2 rounded border border-slate-200 dark:border-slate-800 hover:border-accent"
                  >
                    <span className="font-medium">Problem {p.number}</span>
                    {p.title && <span className="text-slate-500 ml-2 text-sm">— {p.title}</span>}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div>
          <h2 className="text-xl font-semibold mb-3">Resource Packs</h2>
          {data.problem_sets.length === 0 ? (
            <div className="text-slate-500 text-sm">No resource packs archived.</div>
          ) : (
            <ul className="space-y-1">
              {data.problem_sets.map((ps: any) => (
                <li key={ps.id}>
                  <a
                    href={ps.archive_path ? `/api/assets/${ps.archive_path}` : ps.url}
                    target={ps.archive_path ? "_self" : "_blank"}
                    rel="noopener noreferrer"
                    className="block p-2 rounded border border-slate-200 dark:border-slate-800 hover:border-accent"
                  >
                    <span className="font-medium capitalize">{ps.type.replace(/_/g, " ")}</span>
                    {ps.name && <span className="text-slate-500 ml-2 text-sm">— {ps.name}</span>}
                  </a>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
