"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

export default function SettingsPage() {
  const router = useRouter();
  const [setupRequired, setSetupRequired] = useState<boolean | null>(null);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Check status on mount
  useState(() => {
    api.auth.status().then(s => setSetupRequired(s.setup_required)).catch(() => setSetupRequired(true));
  });

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (setupRequired) {
      // Setup mode
      if (password !== confirm) {
        setError("Passwords do not match");
        return;
      }
      if (password.length < 12) {
        setError("Master password must be at least 12 characters");
        return;
      }
      setBusy(true);
      try {
        await api.auth.setup(password);
        router.push("/");
        router.refresh();
      } catch (e: any) {
        setError(e.message);
      } finally {
        setBusy(false);
      }
    } else {
      // Login mode
      setBusy(true);
      try {
        await api.auth.login(password);
        router.push("/");
        router.refresh();
      } catch (e: any) {
        setError(e.message);
      } finally {
        setBusy(false);
      }
    }
  };

  return (
    <div className="max-w-md mx-auto mt-12 space-y-6">
      <div>
        <h1 className="text-2xl font-bold mb-2">
          {setupRequired ? "First-time setup" : "Sign in"}
        </h1>
        <p className="text-slate-400 text-sm">
          {setupRequired
            ? "Choose a master password to encrypt all SSH credentials. This password is NOT recoverable if lost."
            : "Enter your master password to unlock the SSH credential vault."}
        </p>
      </div>

      <form onSubmit={submit} className="space-y-3">
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Master password"
          autoFocus
          className="w-full px-3 py-2 rounded bg-slate-900 border border-slate-800"
        />
        {setupRequired && (
          <input
            type="password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            placeholder="Confirm master password"
            className="w-full px-3 py-2 rounded bg-slate-900 border border-slate-800"
          />
        )}
        <button
          type="submit"
          disabled={busy}
          className="w-full px-4 py-2 rounded bg-emerald-600 hover:bg-emerald-700 text-white disabled:opacity-50"
        >
          {busy ? "Working…" : setupRequired ? "Set master password" : "Unlock"}
        </button>
        {error && <div className="text-red-400 text-sm">{error}</div>}
      </form>
    </div>
  );
}
