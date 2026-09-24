"use client";

import { useEffect, useState } from "react";

export default function SavedPage() {
  const [saved, setSaved] = useState<string[]>([]);

  useEffect(() => {
    try {
      const stored = JSON.parse(localStorage.getItem("mathvault-saved") || "[]");
      setSaved(stored);
    } catch {
      setSaved([]);
    }
  }, []);

  if (saved.length === 0) {
    return (
      <div>
        <h1 className="text-2xl font-bold mb-2">Saved</h1>
        <p className="text-slate-600 dark:text-slate-400">
          No saved problems yet. Click the bookmark icon on a problem page to save it for offline reference.
        </p>
      </div>
    );
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Saved</h1>
      <ul className="space-y-2">
        {saved.map((id) => (
          <li key={id}>
            <a href={`/problems/${id}`} className="text-accent hover:underline">
              Saved problem {id}
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}
