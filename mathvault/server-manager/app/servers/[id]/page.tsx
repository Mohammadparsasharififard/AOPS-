"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { api, Server, ServerStatus, Deployment } from "@/lib/api";

export default function ServerDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [server, setServer] = useState<(Server & { deployments: Deployment[] }) | null>(null);
  const [status, setStatus] = useState<ServerStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"status" | "deployments" | "services" | "console">("status");
  const [servicesOutput, setServicesOutput] = useState<string>("");
  const [cmd, setCmd] = useState("");
  const [cmdResult, setCmdResult] = useState<{ exit_code: number; stdout: string; stderr: string; duration_seconds: number } | null>(null);

  const load = () => {
    if (!params?.id) return;
    api.servers.get(params.id).then(setServer).catch(e => setError(e.message));
  };
  useEffect(() => { load(); }, [params?.id]);

  const refreshStatus = () => {
    if (!params?.id) return;
    setBusy(true);
    api.servers.status(params.id).then(setStatus).catch(e => setError(e.message)).finally(() => setBusy(false));
  };

  const refreshServices = () => {
    if (!params?.id) return;
    setBusy(true);
    api.servers.services(params.id).then(r => setServicesOutput(r.output)).catch(e => setError(e.message)).finally(() => setBusy(false));
  };

  const runCmd = (e: React.FormEvent) => {
    e.preventDefault();
    if (!params?.id || !cmd) return;
    setBusy(true);
    api.servers.run(params.id, cmd).then(setCmdResult).catch(e => setError(e.message)).finally(() => setBusy(false));
  };

  const runDeployment = (depId: string) => {
    if (!params?.id) return;
    setBusy(true);
    api.servers.runDeployment(params.id, depId).then(r => {
      alert(`Exit: ${r.exit_code}\n\nstdout:\n${r.stdout}\n\nstderr:\n${r.stderr}`);
    }).catch(e => alert(e.message)).finally(() => setBusy(false));
  };

  const deleteServer = async () => {
    if (!params?.id) return;
    if (!confirm("Delete this server? All encrypted credentials will be removed.")) return;
    await api.servers.delete(params.id);
    router.push("/servers");
  };

  if (error) return <div className="p-3 rounded bg-red-900/30 border border-red-800 text-red-300">{error}</div>;
  if (!server) return <div className="text-slate-500">Loading…</div>;

  return (
    <div className="space-y-6">
      <div>
        <div className="text-sm text-slate-500">
          <Link href="/servers" className="hover:underline">Servers</Link> / {server.name}
        </div>
        <h1 className="text-2xl font-bold mt-2">{server.name}</h1>
        <div className="text-sm text-slate-500">{server.username}@{server.host}:{server.port}</div>
        {server.notes && <div className="text-sm text-slate-400 mt-1">{server.notes}</div>}
      </div>

      <div className="flex gap-2 border-b border-slate-800 pb-2">
        {(["status", "deployments", "services", "blocked", "console"] as const).map(t => (
          <button
            key={t}
            onClick={() => {
              if (t === "blocked") {
                window.location.href = `/servers/${params?.id}/blocked`;
                return;
              }
              setTab(t);
              if (t === "services") refreshServices();
            }}
            className={`px-3 py-1.5 rounded text-sm ${tab === t ? "bg-slate-800 font-medium" : "hover:bg-slate-900"}`}
          >
            {t === "blocked" ? "⚠ Blocked" : t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {tab === "status" && (
        <div className="space-y-4">
          <button
            onClick={refreshStatus}
            disabled={busy}
            className="px-4 py-2 rounded bg-emerald-600 hover:bg-emerald-700 text-white text-sm disabled:opacity-50"
          >
            {busy ? "Checking…" : "Refresh status"}
          </button>
          {status && (
            <div className="grid md:grid-cols-2 gap-3">
              <Stat label="Online" value={status.online ? "Yes" : "No"} />
              <Stat label="Hostname" value={status.hostname} />
              <Stat label="Uptime" value={status.uptime} />
              <Stat label="Load average" value={status.load_avg || "—"} />
              <Stat label="CPU cores" value={String(status.cpu_count || "—")} />
              <Stat label="Memory" value={
                status.mem_total_mb
                  ? `${(status.mem_used_mb || 0).toFixed(0)} / ${status.mem_total_mb} MB (${((status.mem_used_mb || 0) / status.mem_total_mb * 100).toFixed(1)}%)`
                  : "—"
              } />
              <Stat label="Disk" value={
                status.disk_total_gb
                  ? `${status.disk_used_gb} / ${status.disk_total_gb} GB (${((status.disk_used_gb! / status.disk_total_gb!) * 100).toFixed(1)}%)`
                  : "—"
              } />
              <Stat label="Kernel" value={status.uname} />
            </div>
          )}
        </div>
      )}

      {tab === "deployments" && (
        <div className="space-y-4">
          {server.deployments.length === 0 ? (
            <div className="p-4 rounded border border-slate-800 text-center text-slate-500">
              No deployments configured for this server.
            </div>
          ) : (
            server.deployments.map(d => (
              <div key={d.id} className="p-4 rounded border border-slate-800 space-y-2">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="font-medium">{d.name}</div>
                    <div className="text-xs text-slate-500 mt-1 font-mono">{d.deploy_path}</div>
                    {d.git_url && <div className="text-xs text-slate-500 font-mono">{d.git_url} ({d.git_branch})</div>}
                    {d.service_name && <div className="text-xs text-slate-500">Service: {d.service_name}</div>}
                    {d.deploy_script && <div className="text-xs text-slate-500">Deploy script: {d.deploy_script}</div>}
                  </div>
                  <button
                    onClick={() => runDeployment(d.id)}
                    disabled={busy}
                    className="px-3 py-1.5 rounded bg-emerald-600 hover:bg-emerald-700 text-white text-sm disabled:opacity-50"
                  >
                    {busy ? "Deploying…" : "Deploy"}
                  </button>
                </div>
                {d.last_deployed_at && (
                  <div className="text-xs text-slate-500">
                    Last deploy: {new Date(d.last_deployed_at).toLocaleString()} ({d.last_deploy_status})
                  </div>
                )}
              </div>
            ))
          )}
          <Link href={`/servers/${params?.id}/deployments/new`} className="inline-block px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700 text-sm">
            + Add deployment
          </Link>
        </div>
      )}

      {tab === "services" && (
        <div className="space-y-4">
          <button onClick={refreshServices} disabled={busy} className="px-4 py-2 rounded bg-slate-800 hover:bg-slate-700 text-sm">
            {busy ? "Loading…" : "Refresh services"}
          </button>
          {servicesOutput && (
            <pre>{servicesOutput}</pre>
          )}
        </div>
      )}

      {tab === "console" && (
        <div className="space-y-4">
          <form onSubmit={runCmd} className="flex gap-2">
            <input
              type="text"
              value={cmd}
              onChange={e => setCmd(e.target.value)}
              placeholder="Command (e.g., ls -la /var/log)"
              className="flex-1 px-3 py-2 rounded bg-slate-900 border border-slate-800 font-mono text-sm"
              autoFocus
            />
            <button type="submit" disabled={busy} className="px-4 py-2 rounded bg-emerald-600 hover:bg-emerald-700 text-white text-sm disabled:opacity-50">
              {busy ? "Running…" : "Run"}
            </button>
          </form>
          {cmdResult && (
            <div className="space-y-2">
              <div className="text-sm text-slate-500">Exit code: {cmdResult.exit_code} · Duration: {cmdResult.duration_seconds.toFixed(2)}s</div>
              <pre>{cmdResult.stdout || cmdResult.stderr}</pre>
            </div>
          )}
        </div>
      )}

      <div className="pt-6 border-t border-slate-800">
        <button onClick={deleteServer} className="text-sm text-red-400 hover:underline">
          Delete server
        </button>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="p-3 rounded border border-slate-800">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="text-sm font-medium mt-1 break-all">{value}</div>
    </div>
  );
}
