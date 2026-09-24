"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, StatsResponse } from "@/lib/api";

export default function HomePage() {
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [online, setOnline] = useState<boolean>(true);

  useEffect(() => {
    api.stats()
      .then(setStats)
      .catch(() => setOnline(false));
  }, []);

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold mb-2">MathVault</h1>
        <p className="text-slate-600 dark:text-slate-400">
          Personal Offline Mathematics Competition Archive — browse and search
          archived competition content, fully usable when the internet is off.
        </p>
      </div>

      {!online && (
        <div className="p-4 rounded bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 text-amber-800 dark:text-amber-200">
          <strong>Offline mode.</strong> Showing last-synced snapshot. New
          syncs will resume automatically when the API is reachable again.
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {stats ? (
          <>
            <StatCard label="Contests" value={stats.contests} href="/contests" />
            <StatCard label="Problems" value={stats.problems} href="/problems" />
            <StatCard label="Countries / Regions" value={stats.countries} href="/countries" />
            <StatCard label="Pages archived" value={stats.pages} href="#" />
            <StatCard label="Assets" value={stats.assets} href="#" />
            <StatCard label="Discussions" value={stats.discussions} href="#" />
            <StatCard label="Posts" value={stats.posts} href="#" />
          </>
        ) : (
          <div className="col-span-full text-slate-500">Loading…</div>
        )}
      </div>

      {stats && (
        <div className="p-4 rounded bg-slate-100 dark:bg-slate-900 border border-slate-200 dark:border-slate-800">
          <div className="text-sm text-slate-600 dark:text-slate-400">Last sync</div>
          <div className="text-lg font-medium">
            {stats.last_sync_at ? new Date(stats.last_sync_at).toLocaleString() : "never"}
          </div>
          {stats.next_sync_at && (
            <>
              <div className="text-sm text-slate-600 dark:text-slate-400 mt-2">Next sync</div>
              <div className="text-lg font-medium">
                {new Date(stats.next_sync_at).toLocaleString()}
              </div>
            </>
          )}
        </div>
      )}

      <div>
        <h2 className="text-xl font-semibold mb-3">Browse</h2>
        <div className="grid md:grid-cols-2 gap-4">
          <Link
            href="/contests/international"
            className="block p-6 rounded border border-slate-200 dark:border-slate-800 hover:border-accent hover:bg-slate-50 dark:hover:bg-slate-900"
          >
            <div className="text-lg font-medium">International Contests</div>
            <div className="text-sm text-slate-600 dark:text-slate-400 mt-1">
              Browse IMO, BMO, Putnam and other international competitions.
            </div>
          </Link>
          <Link
            href="/contests/national-regional"
            className="block p-6 rounded border border-slate-200 dark:border-slate-800 hover:border-accent hover:bg-slate-50 dark:hover:bg-slate-900"
          >
            <div className="text-lg font-medium">National & Regional Contests</div>
            <div className="text-sm text-slate-600 dark:text-slate-400 mt-1">
              Browse by country or region — discovered automatically from the archive.
            </div>
          </Link>
        </div>
      </div>
    </div>
  );
}

function StatCard({ label, value, href }: { label: string; value: number; href: string }) {
  return (
    <Link
      href={href}
      className="block p-4 rounded border border-slate-200 dark:border-slate-800 hover:border-accent"
    >
      <div className="text-2xl font-bold text-accent">{value.toLocaleString()}</div>
      <div className="text-xs text-slate-600 dark:text-slate-400">{label}</div>
    </Link>
  );
}
