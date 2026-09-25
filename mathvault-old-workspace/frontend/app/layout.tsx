import "katex/dist/katex.min.css";
import "@/app/globals.css";

import type { Metadata } from "next";
import { Sidebar } from "@/components/Sidebar";
import { ThemeToggle } from "@/components/ThemeToggle";

export const metadata: Metadata = {
  title: "MathVault — Personal Offline Mathematics Competition Archive",
  description: "Browse and search archived mathematics competition content offline.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="bg-slate-50 dark:bg-slate-950 text-slate-900 dark:text-slate-100 min-h-screen">
        <div className="flex min-h-screen">
          <Sidebar />
          <div className="flex-1 flex flex-col">
            <header className="flex items-center justify-end gap-2 p-3 border-b border-slate-200 dark:border-slate-800">
              <ThemeToggle />
            </header>
            <main className="flex-1 p-6 max-w-6xl mx-auto w-full">{children}</main>
          </div>
        </div>
      </body>
    </html>
  );
}
