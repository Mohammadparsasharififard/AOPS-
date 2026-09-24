"use client";

import { useEffect } from "react";
import { ProblemDetail } from "@/lib/api";
import katex from "katex";

/**
 * Renders a problem with LaTeX rendering.
 *
 * LaTeX rendering strategy:
 * - If the statement HTML contains $...$ or $$...$$, we replace those with
 *   rendered KaTeX HTML client-side.
 * - Otherwise, the HTML is rendered as-is.
 *
 * The HTML has already been sanitized server-side (bleach).
 */
export function ProblemView({ problem }: { problem: ProblemDetail }) {
  useEffect(() => {
    if (typeof document === "undefined") return;
    renderMath();
  }, [problem.id, problem.statement_html]);

  if (!problem.statement_html) {
    return (
      <div>
        <h1 className="text-xl font-semibold mb-3">
          Problem {problem.number}
          {problem.title && <span className="text-slate-500 ml-2">— {problem.title}</span>}
        </h1>
        <div className="p-6 rounded border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/20 text-amber-800 dark:text-amber-200">
          This problem statement is not available offline.
        </div>
      </div>
    );
  }

  return (
    <div>
      <h1 className="text-xl font-semibold mb-3">
        Problem {problem.number}
        {problem.title && <span className="text-slate-500 ml-2">— {problem.title}</span>}
      </h1>
      <div
        className="prose-math"
        dangerouslySetInnerHTML={{ __html: problem.statement_html }}
      />
      {problem.tags.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-2">
          {problem.tags.map((t) => (
            <span key={t} className="text-xs px-2 py-1 rounded bg-slate-100 dark:bg-slate-800">
              {t}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function renderMath() {
  // Render inline + display LaTeX
  const blocks = document.querySelectorAll(".prose-math");
  blocks.forEach((block) => {
    const html = block.innerHTML;
    const rendered = renderInlineMath(html);
    if (rendered !== html) {
      block.innerHTML = rendered;
    }
  });
}

function renderInlineMath(html: string): string {
  // Display math: $$...$$
  html = html.replace(/\$\$([\s\S]+?)\$\$/g, (_m, expr) => {
    try {
      return katex.renderToString(expr, { displayMode: true, throwOnError: false });
    } catch {
      return `<code>${expr}</code>`;
    }
  });
  // Inline math: $...$
  html = html.replace(/(^|[^\\])\$([^\n$]+?)\$/g, (match, pre, expr) => {
    try {
      return pre + katex.renderToString(expr, { displayMode: false, throwOnError: false });
    } catch {
      return match;
    }
  });
  // Also handle \( ... \) and \[ ... \]
  html = html.replace(/\\\(([\s\S]+?)\\\)/g, (_m, expr) => {
    try {
      return katex.renderToString(expr, { displayMode: false, throwOnError: false });
    } catch {
      return `<code>${expr}</code>`;
    }
  });
  html = html.replace(/\\\[([\s\S]+?)\\\]/g, (_m, expr) => {
    try {
      return katex.renderToString(expr, { displayMode: true, throwOnError: false });
    } catch {
      return `<code>${expr}</code>`;
    }
  });
  return html;
}
