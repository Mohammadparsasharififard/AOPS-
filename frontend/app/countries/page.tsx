"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";

export default function CountriesPage() {
  const [countries, setCountries] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.countries()
      .then(setCountries)
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold mb-2">Countries & Regions</h1>
        <p className="text-slate-600 dark:text-slate-400">
          Discovered automatically from the source's navigation. Countries are
          never hardcoded.
        </p>
      </div>

      {loading ? (
        <div className="text-slate-500">Loading…</div>
      ) : countries.length === 0 ? (
        <div className="p-6 rounded border border-slate-200 dark:border-slate-800 text-center text-slate-500">
          No countries/regions archived yet. Run <code>mathvault crawl</code> to start.
        </div>
      ) : (
        <div className="grid gap-2 md:grid-cols-3">
          {countries.map((c) => (
            <Link
              key={c.id}
              href={`/countries/${c.slug}`}
              className="block p-3 rounded border border-slate-200 dark:border-slate-800 hover:border-accent"
            >
              <div className="font-medium">{c.name}</div>
              <div className="text-xs text-slate-500 mt-1 capitalize">
                {c.type} • {c.contest_count} contest(s)
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
