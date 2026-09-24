"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

export default function NewServerPage() {
  const router = useRouter();
  const [form, setForm] = useState({
    name: "",
    host: "",
    port: 22,
    username: "root",
    auth_method: "password",
    password: "",
    private_key: "",
    notes: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api.servers.create({
        name: form.name,
        host: form.host,
        port: form.port,
        username: form.username,
        auth_method: form.auth_method,
        password: form.password || undefined,
        private_key: form.private_key || undefined,
        notes: form.notes || undefined,
      });
      router.push("/servers");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="max-w-2xl space-y-6">
      <h1 className="text-2xl font-bold">Register a new server</h1>
      <p className="text-slate-400 text-sm">
        Credentials are encrypted with your master password and stored locally.
        They never leave this laptop.
      </p>

      <form onSubmit={submit} className="space-y-3">
        <Field label="Name (display)" required>
          <input type="text" value={form.name} onChange={e => setForm({...form, name: e.target.value})} className="w-full px-3 py-2 rounded bg-slate-900 border border-slate-800" required />
        </Field>
        <div className="grid grid-cols-3 gap-3">
          <Field label="Host" required>
            <input type="text" value={form.host} onChange={e => setForm({...form, host: e.target.value})} className="w-full px-3 py-2 rounded bg-slate-900 border border-slate-800" placeholder="1.2.3.4 or host.com" required />
          </Field>
          <Field label="Port">
            <input type="number" value={form.port} onChange={e => setForm({...form, port: parseInt(e.target.value, 10)})} className="w-full px-3 py-2 rounded bg-slate-900 border border-slate-800" />
          </Field>
          <Field label="Username">
            <input type="text" value={form.username} onChange={e => setForm({...form, username: e.target.value})} className="w-full px-3 py-2 rounded bg-slate-900 border border-slate-800" />
          </Field>
        </div>

        <Field label="Authentication method">
          <select value={form.auth_method} onChange={e => setForm({...form, auth_method: e.target.value})} className="w-full px-3 py-2 rounded bg-slate-900 border border-slate-800">
            <option value="password">Password</option>
            <option value="key">Private key (PEM)</option>
          </select>
        </Field>

        {form.auth_method === "password" ? (
          <Field label="SSH password" required>
            <input type="password" value={form.password} onChange={e => setForm({...form, password: e.target.value})} className="w-full px-3 py-2 rounded bg-slate-900 border border-slate-800 font-mono" />
          </Field>
        ) : (
          <Field label="Private key (PEM format)" required>
            <textarea value={form.private_key} onChange={e => setForm({...form, private_key: e.target.value})} rows={10} className="w-full px-3 py-2 rounded bg-slate-900 border border-slate-800 font-mono text-xs" placeholder={"-----BEGIN OPENSSH PRIVATE KEY-----\n..."} />
          </Field>
        )}

        <Field label="Notes (optional)">
          <textarea value={form.notes} onChange={e => setForm({...form, notes: e.target.value})} rows={2} className="w-full px-3 py-2 rounded bg-slate-900 border border-slate-800" placeholder="Location, OS, purpose..." />
        </Field>

        {error && <div className="p-2 rounded bg-red-900/30 border border-red-800 text-red-300 text-sm">{error}</div>}

        <div className="flex gap-2">
          <button type="submit" disabled={busy} className="px-4 py-2 rounded bg-emerald-600 hover:bg-emerald-700 text-white disabled:opacity-50">
            {busy ? "Saving…" : "Save server"}
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
      <label className="block text-sm text-slate-400 mb-1">
        {label}{required && <span className="text-red-400 ml-1">*</span>}
      </label>
      {children}
    </div>
  );
}
