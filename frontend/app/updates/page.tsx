"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

interface CrawlRun {
  id: string;
  started_at: string | null;
  finished_at: string | null;
  status: string;
  trigger: string;
  dry_run: boolean;
  pages_discovered: number;
  pages_new: number;
  pages_changed: number;
  pages_unchanged: number;
  pages_failed: number;
  bytes_downloaded: number;
  error_message: string | null;
}

export default function UpdatesPage() {
  const [runs, setRuns] = useState<CrawlRun[]>([]);

  useEffect(() => {
    // This is an admin endpoint — try without auth first (returns 401 if needed)
    fetch("/api/admin/crawl-runs")
      .then((r) => r.ok ? r.json() : [])
      .then(setRuns)
      .catch(() => setRuns([]));
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold mb-2">Updates</h1>
        <p className="text-slate-600 dark:text-slate-400">
          Recent crawl runs and what changed. Admin credentials required for full history.
        </p>
      </div>

      {runs.length === 0 ? (
        <div className="p-6 rounded border border-slate-200 dark:border-slate-800 text-center text-slate-500">
          {runs.length === 0 ? "No crawl runs recorded yet." : "Authentication required."}
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-slate-500 border-b border-slate-200 dark:border-slate-800">
                <th className="py-2 px-2">Started</th>
                <th className="py-2 px-2">Finished</th>
                <th className="py-2 px-2">Status</th>
                <th className="py-2 px-2 text-right">Discovered</th>
                <th className="py-2 px-2 text-right">New</th>
                <th className="py-2 px-2 text-right">Changed</th>
                <th className="py-2 px-2 text-right">Unchanged</th>
                <th className="py-2 px-2 text-right">Failed</th>
                <th className="py-2 px-2 text-right">Bytes</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id} className="border-b border-slate-100 dark:border-slate-900">
                  <td className="py-2 px-2">{r.started_at ? new Date(r.started_at).toLocaleString() : "—"}</td>
                  <td className="py-2 px-2">{r.finished_at ? new Date(r.finished_at).toLocaleString() : "—"}</td>
                  <td className="py-2 px-2">
                    <StatusBadge status={r.status} />
                  </td>
                  <td className="py-2 px-2 text-right">{r.pages_discovered}</td>
                  <td className="py-2 px-2 text-right text-green-600">{r.pages_new}</td>
                  <td className="py-2 px-2 text-right text-blue-600">{r.pages_changed}</td>
                  <td className="py-2 px-2 text-right text-slate-400">{r.pages_unchanged}</td>
                  <td className="py-2 px-2 text-right text-red-600">{r.pages_failed}</td>
                  <td className="py-2 px-2 text-right">{r.bytes_downloaded.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    completed: "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300",
    running: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300",
    failed: "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300",
    aborted: "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300",
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded ${colors[status] || ""}`}>
      {status}
    </span>
  );
}
