"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api } from "@/lib/api";

export default function NewDeploymentPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [form, setForm] = useState({
    name: "",
    deploy_path: "/opt/myapp",
    git_url: "",
    git_branch: "main",
    service_name: "",
    deploy_script: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!params?.id) return;
    setBusy(true);
    setError(null);
    try {
      await api.servers.createDeployment(params.id, {
        name: form.name,
        deploy_path: form.deploy_path,
        git_url: form.git_url || undefined,
        git_branch: form.git_branch,
        service_name: form.service_name || undefined,
        deploy_script: form.deploy_script || undefined,
      });
      router.push(`/servers/${params.id}`);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="max-w-2xl space-y-6">
      <h1 className="text-2xl font-bold">Add deployment</h1>
      <p className="text-slate-400 text-sm">
        Configure how to deploy code to this server. The Server Manager will:
        clone or pull the git repo, run an optional deploy script, and restart
        an optional systemd service.
      </p>

      <form onSubmit={submit} className="space-y-3">
        <Field label="Name" required>
          <input type="text" value={form.name} onChange={e => setForm({...form, name: e.target.value})} className="w-full px-3 py-2 rounded bg-slate-900 border border-slate-800" placeholder="e.g., MathVault API" required />
        </Field>
        <Field label="Deploy path (absolute)" required>
          <input type="text" value={form.deploy_path} onChange={e => setForm({...form, deploy_path: e.target.value})} className="w-full px-3 py-2 rounded bg-slate-900 border border-slate-800 font-mono text-sm" required />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Git URL (optional)">
            <input type="text" value={form.git_url} onChange={e => setForm({...form, git_url: e.target.value})} className="w-full px-3 py-2 rounded bg-slate-900 border border-slate-800 font-mono text-sm" placeholder="https://github.com/owner/repo.git" />
          </Field>
          <Field label="Git branch">
            <input type="text" value={form.git_branch} onChange={e => setForm({...form, git_branch: e.target.value})} className="w-full px-3 py-2 rounded bg-slate-900 border border-slate-800" />
          </Field>
        </div>
        <Field label="Systemd service to restart (optional)">
          <input type="text" value={form.service_name} onChange={e => setForm({...form, service_name: e.target.value})} className="w-full px-3 py-2 rounded bg-slate-900 border border-slate-800 font-mono text-sm" placeholder="e.g., mathvault-api.service" />
        </Field>
        <Field label="Deploy script (path relative to deploy_path)">
          <input type="text" value={form.deploy_script} onChange={e => setForm({...form, deploy_script: e.target.value})} className="w-full px-3 py-2 rounded bg-slate-900 border border-slate-800 font-mono text-sm" placeholder="e.g., scripts/deploy.sh" />
        </Field>
        {error && <div className="p-2 rounded bg-red-900/30 border border-red-800 text-red-300 text-sm">{error}</div>}
        <div className="flex gap-2">
          <button type="submit" disabled={busy} className="px-4 py-2 rounded bg-emerald-600 hover:bg-emerald-700 text-white disabled:opacity-50">
            {busy ? "Saving…" : "Save deployment"}
          </button>
          <button type="button" onClick={() => router.back()} className="px-4 py-2 rounded border border-slate-800">
            Cancel
          </button>
        </div>
      </form>
    </div>
  );
}

function Field({ label, required, children }: { label: string; required?: boolean; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-sm text-slate-400 mb-1">{label}{required && <span className="text-red-400 ml-1">*</span>}</label>
      {children}
    </div>
  );
}
