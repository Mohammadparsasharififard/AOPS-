"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";

export default function BlockedUrlsPage() {
  const params = useParams<{ id: string }>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [output, setOutput] = useState<string>("");
  const [retrying, setRetrying] = useState(false);
  const [retryUrl, setRetryUrl] = useState<string | null>(null);
  const [retryResult, setRetryResult] = useState<string | null>(null);

  const load = () => {
    if (!params?.id) return;
    setLoading(true);
    setError(null);
    fetch(`/api/servers/${params.id}/blocked-urls`, { credentials: "include" })
      .then(r => r.ok ? r.json() : Promise.reject(r))
      .then(data => {
        setOutput(data.output || "No output");
        setLoading(false);
      })
      .catch(e => {
        setError(e.message || "Failed to load");
        setLoading(false);
      });
  };

  useEffect(() => { load(); }, [params?.id]);

  const retrySingle = async (url: string) => {
    if (!params?.id) return;
    setRetrying(true);
    setRetryUrl(url);
    setRetryResult(null);
    try {
      const res = await fetch(`/api/servers/${params.id}/blocked-urls/${encodeURIComponent(url)}/retry`, {
        method: "POST",
        credentials: "include",
      });
      const data = await res.json();
      // Try to parse JSON from the output
      try {
        const parsed = JSON.parse(data.output);
        if (parsed.success > 0) {
          setRetryResult(`✓ Archived successfully!`);
        } else if (parsed.still_blocked > 0) {
          setRetryResult(`⚠ Still blocked — try with headless: false`);
        } else {
          setRetryResult(`✗ Failed: ${parsed.results?.[0]?.message || "unknown"}`);
        }
      } catch {
        setRetryResult(data.output?.slice(0, 200) || "No output");
      }
      // Reload the list
      setTimeout(load, 1000);
    } catch (e: any) {
      setRetryResult(`Error: ${e.message}`);
    } finally {
      setRetrying(false);
      setRetryUrl(null);
    }
  };

  const retryAll = async () => {
    if (!params?.id) return;
    if (!confirm("Retry ALL blocked URLs? This may take several minutes.")) return;
    setRetrying(true);
    setRetryResult(null);
    try {
      const res = await fetch(`/api/servers/${params.id}/blocked-urls/retry`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
        credentials: "include",
      });
      const data = await res.json();
      try {
        const parsed = JSON.parse(data.output);
        setRetryResult(`Success: ${parsed.success}, Still blocked: ${parsed.still_blocked}, Failed: ${parsed.failed}`);
      } catch {
        setRetryResult(data.output?.slice(0, 300) || "No output");
      }
      setTimeout(load, 2000);
    } catch (e: any) {
      setRetryResult(`Error: ${e.message}`);
    } finally {
      setRetrying(false);
    }
  };

  // Parse the coverage output to extract blocked URLs
  const blockedLines = output.split("\n").filter(l =>
    l.includes("blocked") || l.includes("Blocked") || l.includes("challenge") || l.includes("cloudflare")
  );

  return (
    <div className="space-y-6">
      <div>
        <div className="text-sm text-slate-500">
          <Link href="/servers" className="hover:underline">Servers</Link>
          {" / "}
          <Link href={`/servers/${params?.id}`} className="hover:underline">Server</Link>
          {" / Blocked URLs"}
        </div>
        <h1 className="text-2xl font-bold mt-2">Blocked / Failed URLs</h1>
        <p className="text-slate-400 text-sm mt-1">
          URLs that couldn't be archived (CAPTCHA, login, paywall, Cloudflare challenge).
          Click "Retry" to re-fetch a single URL. The system NEVER bypasses CAPTCHA —
          if a real CAPTCHA appears, set <code>browser.headless: false</code> in source.yaml
          and retry manually.
        </p>
      </div>

      {error && (
        <div className="p-3 rounded bg-red-900/30 border border-red-800 text-red-300 text-sm">
          {error}
        </div>
      )}

      <div className="flex gap-2">
        <button
          onClick={load}
          disabled={loading}
          className="px-4 py-2 rounded bg-slate-800 hover:bg-slate-700 text-sm disabled:opacity-50"
        >
          {loading ? "Loading…" : "Refresh"}
        </button>
        <button
          onClick={retryAll}
          disabled={retrying}
          className="px-4 py-2 rounded bg-emerald-600 hover:bg-emerald-700 text-white text-sm disabled:opacity-50"
        >
          {retrying ? "Retrying…" : "Retry All Blocked"}
        </button>
      </div>

      {retryResult && (
        <div className="p-3 rounded bg-slate-900 border border-slate-800 text-sm">
          <strong>Retry result:</strong> {retryResult}
        </div>
      )}

      <div>
        <h2 className="text-lg font-semibold mb-3">Coverage Output</h2>
        {loading ? (
          <div className="text-slate-500">Loading…</div>
        ) : (
          <pre className="bg-slate-900 border border-slate-800 rounded p-4 overflow-x-auto text-sm whitespace-pre-wrap">
{output}
          </pre>
        )}
      </div>

      {/* Quick actions */}
      <div className="grid md:grid-cols-2 gap-4">
        <Link
          href={`/servers/${params?.id}?tab=validate`}
          className="block p-4 rounded border border-slate-800 hover:border-emerald-600"
        >
          <div className="font-medium">Validate Archive</div>
          <div className="text-sm text-slate-400 mt-1">
            Check for broken links, missing assets, unindexed pages
          </div>
        </Link>
        <Link
          href={`/servers/${params?.id}?tab=offline`}
          className="block p-4 rounded border border-slate-800 hover:border-emerald-600"
        >
          <div className="font-medium">Offline Test</div>
          <div className="text-sm text-slate-400 mt-1">
            Verify archive works without internet
          </div>
        </Link>
      </div>
    </div>
  );
}
