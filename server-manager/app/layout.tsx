import "@/app/globals.css";
import type { Metadata } from "next";
import { Sidebar } from "@/components/Sidebar";

export const metadata: Metadata = {
  title: "Personal Server Manager",
  description: "Laptop-side control panel for SSH-reachable personal servers.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="bg-slate-950 text-slate-100 min-h-screen">
        <div className="flex min-h-screen">
          <Sidebar />
          <main className="flex-1 p-6 max-w-6xl mx-auto w-full">{children}</main>
        </div>
      </body>
    </html>
  );
}
