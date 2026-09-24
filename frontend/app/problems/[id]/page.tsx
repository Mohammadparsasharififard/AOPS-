"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { api, ProblemDetail } from "@/lib/api";
import { ProblemView } from "@/components/ProblemView";

export default function ProblemDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [problem, setProblem] = useState<ProblemDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [discussion, setDiscussion] = useState<any>(null);

  useEffect(() => {
    if (!params?.id) return;
    setLoading(true);
    api.problem(params.id).then((p) => {
      setProblem(p);
      if (p.discussion_available) {
        api.problemDiscussion(params.id).then(setDiscussion).catch(() => {});
      }
    }).finally(() => setLoading(false));
  }, [params?.id]);

  if (loading) return <div className="text-slate-500">Loading…</div>;
  if (!problem) return <div className="text-slate-500">Problem not found.</div>;

  return (
    <div className="space-y-6">
      <div>
        <div className="text-sm text-slate-500">
          <Link href="/problems" className="hover:underline">Problems</Link>
          {problem.contest_slug && (
            <>
              {" / "}
              <Link href={`/contests/${problem.contest_slug}`} className="hover:underline">
                {problem.contest_name}
              </Link>
            </>
          )}
          {problem.year && <> / {problem.year}</>}
        </div>
      </div>

      <ProblemView problem={problem} />

      {/* Navigation */}
      <div className="flex items-center justify-between border-t border-slate-200 dark:border-slate-800 pt-4">
        {problem.prev_id ? (
          <Link
            href={`/problems/${problem.prev_id}`}
            className="px-4 py-2 rounded border border-slate-200 dark:border-slate-800 hover:border-accent"
          >
            ← Previous Problem
          </Link>
        ) : (
          <span className="px-4 py-2 text-slate-400">← Previous</span>
        )}

        <span className="text-slate-500 text-sm">
          Problem {problem.position} / {problem.total_in_contest}
        </span>

        {problem.next_id ? (
          <Link
            href={`/problems/${problem.next_id}`}
            className="px-4 py-2 rounded border border-slate-200 dark:border-slate-800 hover:border-accent"
          >
            Next Problem →
          </Link>
        ) : (
          <span className="px-4 py-2 text-slate-400">Next →</span>
        )}
      </div>

      {/* Resources */}
      <div>
        <h2 className="text-lg font-semibold mb-2">Available archived resources</h2>
        <ul className="space-y-1 text-sm">
          {problem.solution_available && (
            <li>✓ Solution (archived)</li>
          )}
          {problem.discussion_available && (
            <li>✓ Discussion (archived)</li>
          )}
          {problem.archive_url && (
            <li>
              <a href={problem.archive_url} className="text-accent hover:underline">
                View archived page
              </a>
            </li>
          )}
          {!problem.solution_available && !problem.discussion_available && !problem.archive_url && (
            <li className="text-slate-500">No additional resources archived.</li>
          )}
        </ul>
      </div>

      {/* Discussion */}
      {discussion && discussion.threads?.length > 0 && (
        <div>
          <h2 className="text-lg font-semibold mb-3">Discussion</h2>
          <div className="space-y-4">
            {discussion.threads.map((t: any) => (
              <div key={t.id} className="rounded border border-slate-200 dark:border-slate-800 p-4">
                {t.title && <div className="font-medium mb-2">{t.title}</div>}
                <PostTree posts={t.posts} />
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function PostTree({ posts }: { posts: any[] }) {
  if (!posts || posts.length === 0) return null;
  return (
    <ul className="space-y-3">
      {posts.map((p) => (
        <li key={p.id} className="text-sm">
          <div className="flex items-center gap-2 mb-1">
            <span className="font-medium">{p.author || "Anonymous"}</span>
            {p.posted_at && (
              <span className="text-xs text-slate-500">
                {new Date(p.posted_at).toLocaleString()}
              </span>
            )}
          </div>
          <div
            className="prose-math text-slate-700 dark:text-slate-300"
            dangerouslySetInnerHTML={{ __html: p.content_html || "" }}
          />
          {p.replies && p.replies.length > 0 && (
            <div className="ml-6 mt-3 border-l border-slate-200 dark:border-slate-800 pl-4">
              <PostTree posts={p.replies} />
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}
