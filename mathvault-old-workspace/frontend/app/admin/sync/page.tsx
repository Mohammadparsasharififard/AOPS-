"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

interface SyncStatus {
  last_sync_started_at: string | null;
  last_sync_finished_at: string | null;
  last_status: string | null;
  next_sync_at: string | null;
  sync_interval_hours: number;
  pages_discovered: number;
  pages_new: number;
  pages_changed: number;
  pages_unchanged: number;
  pages_failed: number;
  bytes_downloaded: number;
  trigger: string | null;
  error_message: string | null;
  errors: { url: string; type: string; message: string; http_status: number | null; occurred_at: string | null }[];
}

export default function AdminSyncPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [authed, setAuthed] = useState(false);
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [triggering, setTriggering] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadStatus = async () => {
    try {
      const s = await api.admin.syncStatus(username, password);
      setStatus(s);
      setAuthed(true);
      setError(null);
    } catch (e: any) {
      setError(e?.status === 401 ? "Invalid credentials" : "Failed to load status");
    }
  };

  const triggerSync = async () => {
    setTriggering(true);
    try {
      await api.admin.runSync(username, password);
      setError(null);
      setTimeout(loadStatus, 1000);
    } catch (e: any) {
      setError(e?.status === 401 ? "Invalid credentials" : "Failed to trigger sync");
    } finally {
      setTriggering(false);
    }
  };

  if (!authed) {
    return (
      <div className="max-w-md mx-auto mt-12">
        <h1 className="text-2xl font-bold mb-4">Admin — Sync Dashboard</h1>
        <p className="text-slate-500 text-sm mb-4">
          Enter admin credentials (configured via <code>ADMIN_USERNAME</code> and <code>ADMIN_PASSWORD_HASH</code>).
        </p>
        <div className="space-y-3">
          <input
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="Username"
            className="w-full px-3 py-2 rounded border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900"
          />
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Password"
            className="w-full px-3 py-2 rounded border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900"
            onKeyDown={(e) => { if (e.key === "Enter") loadStatus(); }}
          />
          <button
            onClick={loadStatus}
            className="w-full px-4 py-2 rounded bg-accent text-white hover:bg-accent-hover"
          >
            Sign In
          </button>
          {error && <div className="text-red-500 text-sm">{error}</div>}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Admin — Sync Dashboard</h1>
        <button
          onClick={triggerSync}
          disabled={triggering}
          className="px-4 py-2 rounded bg-accent text-white hover:bg-accent-hover disabled:opacity-50"
        >
          {triggering ? "Triggering…" : "Run Sync Now"}
        </button>
      </div>

      {status && (
        <>
          <div className="grid md:grid-cols-3 gap-4">
            <Stat label="Last sync" value={status.last_sync_finished_at ? new Date(status.last_sync_finished_at).toLocaleString() : "never"} />
            <Stat label="Next sync" value={status.next_sync_at ? new Date(status.next_sync_at).toLocaleString() : "—"} />
            <Stat label="Status" value={status.last_status || "—"} />
            <Stat label="Pages discovered" value={String(status.pages_discovered)} />
            <Stat label="New pages" value={String(status.pages_new)} />
            <Stat label="Changed pages" value={String(status.pages_changed)} />
            <Stat label="Unchanged pages" value={String(status.pages_unchanged)} />
            <Stat label="Failed pages" value={String(status.pages_failed)} />
            <Stat label="Bytes downloaded" value={status.bytes_downloaded.toLocaleString()} />
          </div>

          {status.error_message && (
            <div className="p-4 rounded bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-300">
              <strong>Last run error:</strong> {status.error_message}
            </div>
          )}

          {status.errors.length > 0 && (
            <div>
              <h2 className="text-lg font-semibold mb-3">Recent errors</h2>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-slate-500 border-b border-slate-200 dark:border-slate-800">
                      <th className="py-2 px-2">Time</th>
                      <th className="py-2 px-2">Type</th>
                      <th className="py-2 px-2">URL</th>
                      <th className="py-2 px-2">Message</th>
                      <th className="py-2 px-2">HTTP</th>
                    </tr>
                  </thead>
                  <tbody>
                    {status.errors.map((e, i) => (
                      <tr key={i} className="border-b border-slate-100 dark:border-slate-900">
                        <td className="py-2 px-2">{e.occurred_at ? new Date(e.occurred_at).toLocaleString() : "—"}</td>
                        <td className="py-2 px-2">{e.type}</td>
                        <td className="py-2 px-2 truncate max-w-xs">{e.url}</td>
                        <td className="py-2 px-2">{e.message}</td>
                        <td className="py-2 px-2">{e.http_status || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="p-4 rounded border border-slate-200 dark:border-slate-800">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="text-lg font-medium mt-1">{value}</div>
    </div>
  );
}
