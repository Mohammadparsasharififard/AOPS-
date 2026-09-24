"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, Server } from "@/lib/api";

export default function DeployPage() {
  const [servers, setServers] = useState<Server[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.servers.list().then(setServers).catch(e => setError(e.message));
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold mb-2">Quick deploy</h1>
        <p className="text-slate-400">
          Pick a server to manage its deployments. For new deployments, use the
          server detail page.
        </p>
      </div>
      {error && (
        <div className="p-2 rounded bg-red-900/30 border border-red-800 text-red-300 text-sm">
          {error} — sign in first.
        </div>
      )}
      {servers.length === 0 ? (
        <div className="p-6 rounded border border-slate-800 text-center text-slate-500">
          No servers registered yet. <Link href="/servers/new" className="text-emerald-400 underline">Add one →</Link>
        </div>
      ) : (
        <ul className="space-y-3">
          {servers.map(s => (
            <li key={s.id} className="p-4 rounded border border-slate-800">
              <div className="flex items-center justify-between">
                <Link href={`/servers/${s.id}`} className="font-medium hover:underline">
                  {s.name}
                </Link>
                <Link href={`/servers/${s.id}`} className="text-sm text-emerald-400 hover:underline">
                  Manage deployments →
                </Link>
              </div>
              <div className="text-xs text-slate-500 mt-1">
                {s.username}@{s.host}:{s.port}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
