"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, AuditEntry } from "@/lib/api";

export default function LogsPage() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.audit.list(100).then(setEntries).catch(e => setError(e.message));
  }, []);

  if (error) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold">Audit Log</h1>
        <div className="p-3 rounded bg-red-900/30 border border-red-800 text-red-300">
          {error} — <Link href="/settings" className="underline">sign in</Link>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Audit Log</h1>
      <p className="text-slate-400 text-sm">Last 100 sensitive actions.</p>

      {entries.length === 0 ? (
        <div className="p-4 rounded border border-slate-800 text-center text-slate-500">
          No actions recorded yet.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table>
            <thead>
              <tr className="text-slate-500">
                <th>Time</th>
                <th>Action</th>
                <th>Command</th>
                <th>Exit</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {entries.map(e => (
                <tr key={e.id}>
                  <td className="text-xs text-slate-500">
                    {e.started_at ? new Date(e.started_at).toLocaleString() : "—"}
                  </td>
                  <td className="text-sm">{e.action}</td>
                  <td className="text-xs font-mono text-slate-400 truncate max-w-md">
                    {e.command || ""}
                  </td>
                  <td className="text-xs">{e.exit_code ?? "—"}</td>
                  <td className={e.success ? "text-emerald-400 text-xs" : "text-red-400 text-xs"}>
                    {e.success ? "OK" : "FAIL"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
