"use client";

import { useEffect, useState } from "react";

export default function RecentlyViewedPage() {
  const [history, setHistory] = useState<{ id: string; at: number }[]>([]);

  useEffect(() => {
    try {
      const stored = JSON.parse(localStorage.getItem("mathvault-history") || "[]");
      setHistory(stored);
    } catch {
      setHistory([]);
    }
  }, []);

  if (history.length === 0) {
    return (
      <div>
        <h1 className="text-2xl font-bold mb-2">Recently Viewed</h1>
        <p className="text-slate-600 dark:text-slate-400">
          No recent history. Browse problems to populate this list.
        </p>
      </div>
    );
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Recently Viewed</h1>
      <ul className="space-y-2">
        {history.map((h) => (
          <li key={h.id + h.at}>
            <a href={`/problems/${h.id}`} className="text-accent hover:underline">
              {h.id} — viewed {new Date(h.at).toLocaleString()}
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}
