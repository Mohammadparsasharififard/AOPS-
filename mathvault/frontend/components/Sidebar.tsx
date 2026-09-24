"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

const NAV_ITEMS = [
  { href: "/", label: "Home" },
  { href: "/contests", label: "Contests", children: [
    { href: "/contests/international", label: "International" },
    { href: "/contests/national-regional", label: "National & Regional" },
  ]},
  { href: "/countries", label: "Countries" },
  { href: "/problems", label: "Problems" },
  { href: "/search", label: "Search" },
  { href: "/saved", label: "Saved" },
  { href: "/recently-viewed", label: "Recently Viewed" },
  { href: "/updates", label: "Updates" },
  { href: "/admin/sync", label: "Server Status" },
];

export function Sidebar() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  return (
    <>
      {/* Mobile toggle */}
      <button
        className="md:hidden fixed top-3 left-3 z-50 p-2 bg-slate-200 dark:bg-slate-800 rounded"
        onClick={() => setOpen((o) => !o)}
        aria-label="Toggle sidebar"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M3 12h18M3 6h18M3 18h18" />
        </svg>
      </button>

      <aside
        className={`sidebar bg-white dark:bg-slate-900 border-r border-slate-200 dark:border-slate-800 w-64 flex-shrink-0 p-4 ${
          open ? "open" : ""
        }`}
      >
        <Link href="/" className="block mb-6 text-xl font-bold text-accent">
          MathVault
        </Link>
        <nav className="space-y-1">
          {NAV_ITEMS.map((item) => (
            <div key={item.href}>
              <Link
                href={item.href}
                className={`block px-3 py-2 rounded text-sm hover:bg-slate-100 dark:hover:bg-slate-800 ${
                  pathname === item.href ? "bg-slate-100 dark:bg-slate-800 font-medium" : ""
                }`}
              >
                {item.label}
              </Link>
              {item.children && (
                <div className="ml-4 mt-1 space-y-1 border-l border-slate-200 dark:border-slate-800 pl-3">
                  {item.children.map((child) => (
                    <Link
                      key={child.href}
                      href={child.href}
                      className="block px-3 py-1.5 rounded text-sm text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 hover:text-slate-900 dark:hover:text-slate-100"
                    >
                      {child.label}
                    </Link>
                  ))}
                </div>
              )}
            </div>
          ))}
        </nav>
        <div className="mt-6 text-xs text-slate-400 border-t border-slate-200 dark:border-slate-800 pt-4">
          <span className="block">Offline-first archive</span>
          <span className="block">v1.0.0</span>
        </div>
      </aside>

      {/* Backdrop on mobile when open */}
      {open && (
        <div
          className="md:hidden fixed inset-0 bg-black/50 z-40"
          onClick={() => setOpen(false)}
        />
      )}
    </>
  );
}
