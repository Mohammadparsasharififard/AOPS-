"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, Server } from "@/lib/api";

export default function HomePage() {
  const [servers, setServers] = useState<Server[]>([]);
  const [setupRequired, setSetupRequired] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.auth.status()
      .then(s => {
        setSetupRequired(s.setup_required);
        if (!s.setup_required) {
          return api.servers.list();
        }
        return [];
      })
      .then(setServers)
      .catch(e => setError(e.message));
  }, []);

  if (setupRequired) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold">Welcome</h1>
        <p className="text-slate-400">
          This is your first run. Set a master password to encrypt SSH credentials.
        </p>
        <Link href="/settings" className="inline-block px-4 py-2 rounded bg-emerald-600 hover:bg-emerald-700 text-white">
          Go to setup →
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold mb-2">Dashboard</h1>
        <p className="text-slate-400">
          Manage your registered personal servers. All credentials are encrypted locally
          with your master password.
        </p>
      </div>

      {error && (
        <div className="p-3 rounded bg-red-900/30 border border-red-800 text-red-300 text-sm">
          {error}
          <div className="mt-2">
            <Link href="/settings" className="underline">Sign in →</Link>
          </div>
        </div>
      )}

      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-xl font-semibold">Servers ({servers.length})</h2>
          <Link
            href="/servers/new"
            className="px-3 py-1.5 rounded bg-emerald-600 hover:bg-emerald-700 text-white text-sm"
          >
            + Add server
          </Link>
        </div>
        {servers.length === 0 ? (
          <div className="p-6 rounded border border-slate-800 text-center text-slate-500">
            No servers registered yet.
          </div>
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            {servers.map(s => (
              <Link
                key={s.id}
                href={`/servers/${s.id}`}
                className="block p-4 rounded border border-slate-800 hover:border-emerald-600 hover:bg-slate-900"
              >
                <div className="flex items-start justify-between">
                  <div>
                    <div className="font-medium">{s.name}</div>
                    <div className="text-xs text-slate-500 mt-1">
                      {s.username}@{s.host}:{s.port}
                    </div>
                  </div>
                  <StatusBadge status={s.last_status} />
                </div>
                {s.notes && (
                  <div className="text-xs text-slate-500 mt-2">{s.notes}</div>
                )}
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status?: string | null }) {
  if (!status) return <span className="text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-400">unknown</span>;
  const colors: Record<string, string> = {
    online: "bg-emerald-900/40 text-emerald-300",
    offline: "bg-red-900/40 text-red-300",
    error: "bg-amber-900/40 text-amber-300",
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded ${colors[status] || "bg-slate-800 text-slate-400"}`}>
      {status}
    </span>
  );
}
