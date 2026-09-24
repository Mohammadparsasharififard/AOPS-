"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, Server } from "@/lib/api";

export default function ServersListPage() {
  const [servers, setServers] = useState<Server[]>([]);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  const load = () => {
    api.servers.list().then(setServers).catch(e => setError(e.message));
  };

  useEffect(() => { load(); }, []);

  if (error) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold">Servers</h1>
        <div className="p-3 rounded bg-red-900/30 border border-red-800 text-red-300">
          {error} — <Link href="/settings" className="underline">sign in</Link>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Servers</h1>
        <Link href="/servers/new" className="px-3 py-1.5 rounded bg-emerald-600 hover:bg-emerald-700 text-white text-sm">
          + Add server
        </Link>
      </div>
      {servers.length === 0 ? (
        <div className="p-6 rounded border border-slate-800 text-center text-slate-500">
          No servers yet. <Link href="/servers/new" className="text-emerald-400 underline">Add one →</Link>
        </div>
      ) : (
        <ul className="divide-y divide-slate-800">
          {servers.map(s => (
            <li key={s.id} className="py-3">
              <Link href={`/servers/${s.id}`} className="block hover:bg-slate-900 p-2 rounded">
                <div className="flex items-center justify-between">
                  <div>
                    <span className="font-medium">{s.name}</span>
                    <span className="text-sm text-slate-500 ml-2">{s.username}@{s.host}:{s.port}</span>
                  </div>
                  <span className="text-xs text-slate-500">{s.last_status || "unknown"}</span>
                </div>
                {s.notes && <div className="text-xs text-slate-500 mt-1">{s.notes}</div>}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
