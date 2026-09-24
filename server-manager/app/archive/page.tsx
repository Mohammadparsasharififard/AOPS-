"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";

export default function ArchivePage() {
  const [urls, setUrls] = useState<{ frontend_url: string; api_url: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.archive.offlineUrl().then(setUrls).catch(e => setError(e.message));
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold mb-2">Offline Archive</h1>
        <p className="text-slate-400">
          Access the MathVault offline archive running on this laptop (or on your server).
        </p>
      </div>

      {error && (
        <div className="p-3 rounded bg-red-900/30 border border-red-800 text-red-300">
          {error}
        </div>
      )}

      {urls && (
        <div className="grid md:grid-cols-2 gap-4">
          <a
            href={urls.frontend_url}
            target="_blank"
            rel="noopener noreferrer"
            className="block p-6 rounded border border-slate-800 hover:border-emerald-600"
          >
            <div className="text-lg font-medium">Open MathVault UI</div>
            <div className="text-xs text-slate-500 mt-1 font-mono">{urls.frontend_url}</div>
            <div className="text-sm text-slate-400 mt-3">
              Browse archived contests, problems, and discussions. Works fully offline
              once content has been archived.
            </div>
          </a>
          <a
            href={`${urls.api_url}/api/docs`}
            target="_blank"
            rel="noopener noreferrer"
            className="block p-6 rounded border border-slate-800 hover:border-emerald-600"
          >
            <div className="text-lg font-medium">MathVault API docs</div>
            <div className="text-xs text-slate-500 mt-1 font-mono">{urls.api_url}/api/docs</div>
            <div className="text-sm text-slate-400 mt-3">
              OpenAPI / Swagger. Useful for programmatic access to the archive.
            </div>
          </a>
        </div>
      )}

      <div className="p-4 rounded border border-slate-800 bg-slate-900/50">
        <h2 className="font-medium mb-2">How this works</h2>
        <ol className="text-sm text-slate-400 list-decimal list-inside space-y-1">
          <li>MathVault runs as a separate service (locally or on your server).</li>
          <li>This Server Manager just provides a convenient link to it.</li>
          <li>Once content is archived, MathVault is fully usable offline.</li>
          <li>The archive respects <code>robots.txt</code> and your allowlist — it never bypasses access controls.</li>
        </ol>
      </div>
    </div>
  );
}
