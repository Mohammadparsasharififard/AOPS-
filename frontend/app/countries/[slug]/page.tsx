"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";

export default function CountryDetailPage() {
  const params = useParams<{ slug: string }>();
  const [country, setCountry] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!params?.slug) return;
    api.country(params.slug)
      .then(setCountry)
      .finally(() => setLoading(false));
  }, [params?.slug]);

  if (loading) return <div className="text-slate-500">Loading…</div>;
  if (!country) return <div className="text-slate-500">Country/Region not found.</div>;

  return (
    <div className="space-y-6">
      <div>
        <div className="text-sm text-slate-500">
          <Link href="/countries" className="hover:underline">Countries</Link> / {country.name}
        </div>
        <h1 className="text-2xl font-bold mt-2">{country.name}</h1>
        <div className="text-sm text-slate-500 capitalize">{country.type}</div>
      </div>

      <div>
        <h2 className="text-xl font-semibold mb-3">Contests</h2>
        {country.contests.length === 0 ? (
          <div className="text-slate-500">No contests archived.</div>
        ) : (
          <div className="grid gap-2 md:grid-cols-2">
            {country.contests.map((c: any) => (
              <Link
                key={c.id}
                href={`/contests/${c.slug}`}
                className="block p-4 rounded border border-slate-200 dark:border-slate-800 hover:border-accent hover:bg-slate-50 dark:hover:bg-slate-900"
              >
                <div className="font-medium">{c.name}</div>
                {c.category && (
                  <div className="text-xs text-slate-500 mt-1">{c.category}</div>
                )}
                <div className="mt-2 text-xs text-slate-500">
                  {c.last_synced ? `synced ${new Date(c.last_synced).toLocaleDateString()}` : "never synced"}
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
