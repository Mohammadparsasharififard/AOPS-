"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

const NAV = [
  { href: "/", label: "Dashboard" },
  { href: "/servers", label: "Servers" },
  { href: "/deploy", label: "Deploy" },
  { href: "/logs", label: "Audit Log" },
  { href: "/archive", label: "Offline Archive" },
  { href: "/settings", label: "Settings" },
];

export function Sidebar() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        className="md:hidden fixed top-3 left-3 z-50 p-2 bg-slate-800 rounded"
        onClick={() => setOpen(o => !o)}
        aria-label="Toggle sidebar"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M3 12h18M3 6h18M3 18h18" />
        </svg>
      </button>
      <aside className={`sidebar bg-slate-900 border-r border-slate-800 w-60 flex-shrink-0 p-4 ${open ? "open" : ""}`}>
        <Link href="/" className="block mb-6 text-lg font-bold text-emerald-400">
          Server Manager
        </Link>
        <nav className="space-y-1">
          {NAV.map(item => (
            <Link
              key={item.href}
              href={item.href}
              className={`block px-3 py-2 rounded text-sm hover:bg-slate-800 ${
                pathname === item.href ? "bg-slate-800 font-medium" : ""
              }`}
            >
              {item.label}
            </Link>
          ))}
        </nav>
        <div className="mt-6 text-xs text-slate-500 border-t border-slate-800 pt-4">
          <span className="block">v1.0.0</span>
          <span className="block">Local-only · encrypted</span>
        </div>
      </aside>
      {open && <div className="md:hidden fixed inset-0 bg-black/50 z-40" onClick={() => setOpen(false)} />}
    </>
  );
}
