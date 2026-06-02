"use client";

import { useEffect, useState } from "react";

interface Draft {
  id: string;
  trend_id: string | null;
  persona_id: string | null;
  platform: string;
  content_text: string;
  status: string;
  generated_at: string;
  llm_metadata: any;
  feedback_notes: string | null;
  approved_at: string | null;
  final_content: string | null;
  
  image_url?: string | null;

  // Custom resolved properties
  topic?: string;
  final_score?: number;
}

export default function ApprovalsPage() {
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://personal-branding-engine.onrender.com/api/v1";

  const fetchTrend = async (trendId: string) => {
    try {
      const res = await fetch(`${API_BASE}/trends/${trendId}`);
      if (res.ok) {
        return await res.json();
      }
    } catch (err) {
      console.error(`Error fetching trend ${trendId}:`, err);
    }
    return null;
  };

  useEffect(() => {
    const loadDrafts = async () => {
      try {
        setLoading(true);
        setError(null);
        
        const res = await fetch(`${API_BASE}/approvals/pending`);
        if (!res.ok) {
          throw new Error(`Failed to fetch pending drafts (Status: ${res.status})`);
        }
        const data: Draft[] = await res.json();
        
        // Fetch trend details in parallel to resolve topic & final_score
        const uniqueTrendIds = Array.from(
          new Set(data.map((d) => d.trend_id).filter(Boolean) as string[])
        );
        
        const trendMap: Record<string, { topic: string; final_score: number }> = {};
        
        await Promise.all(
          uniqueTrendIds.map(async (trendId) => {
            const trend = await fetchTrend(trendId);
            if (trend) {
              trendMap[trendId] = {
                topic: trend.topic,
                final_score: trend.final_score,
              };
            }
          })
        );
        
        // Merge trend attributes
        const enrichedDrafts = data.map((draft) => {
          if (draft.trend_id && trendMap[draft.trend_id]) {
            return {
              ...draft,
              topic: trendMap[draft.trend_id].topic,
              final_score: trendMap[draft.trend_id].final_score,
            };
          }
          return {
            ...draft,
            topic: "General Technology",
            final_score: 50.0,
          };
        });
        
        setDrafts(enrichedDrafts);
      } catch (err: any) {
        console.error("Error loading approvals board:", err);
        setError(err.message || "An unexpected error occurred while loading content drafts.");
      } finally {
        setLoading(false);
      }
    };

    loadDrafts();
  }, [API_BASE]);

  const handleApprove = async (draftId: string) => {
    try {
      const res = await fetch(`${API_BASE}/approvals/${draftId}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ edited_content: null }),
      });
      
      if (res.ok) {
        setDrafts((prev) => prev.filter((d) => d.id !== draftId));
      } else {
        const errorData = await res.json().catch(() => ({}));
        alert(`Failed to approve draft: ${errorData.detail || "Server rejected transaction."}`);
      }
    } catch (err) {
      console.error("Approve request error:", err);
      alert("Network error: Failed to dispatch approval request.");
    }
  };

  const handleReject = async (draftId: string) => {
    try {
      const res = await fetch(`${API_BASE}/approvals/${draftId}/reject`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: "Rejected by curator from Command Center dashboard UI" }),
      });
      
      if (res.ok) {
        setDrafts((prev) => prev.filter((d) => d.id !== draftId));
      } else {
        const errorData = await res.json().catch(() => ({}));
        alert(`Failed to reject draft: ${errorData.detail || "Server rejected transaction."}`);
      }
    } catch (err) {
      console.error("Reject request error:", err);
      alert("Network error: Failed to dispatch rejection request.");
    }
  };

  return (
    <div className="space-y-6">
      {/* Page Title Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">
            Content Approvals Pipeline
          </h1>
          <p className="text-sm text-gray-400 mt-1">
            Review, approve, or reject auto-generated content drafts awaiting network distribution.
          </p>
        </div>
        <div className="bg-gray-900 border border-gray-800 px-4 py-2 rounded-lg text-sm text-gray-300 font-medium">
          Pending Review: <span className="text-indigo-400 font-semibold">{drafts.length}</span>
        </div>
      </div>

      {/* Loading State */}
      {loading && (
        <div className="flex flex-col items-center justify-center py-20 gap-4">
          <div className="w-10 h-10 border-4 border-indigo-500 border-t-transparent rounded-full animate-spin"></div>
          <span className="text-gray-400 text-sm font-medium">Loading content pipeline...</span>
        </div>
      )}

      {/* Error State */}
      {error && !loading && (
        <div className="border border-red-500/20 bg-red-500/5 rounded-xl p-6 text-center max-w-xl mx-auto my-12">
          <h3 className="text-red-400 font-semibold mb-2">Connection Failure</h3>
          <p className="text-sm text-gray-400 mb-4">{error}</p>
          <button
            onClick={() => window.location.reload()}
            className="px-4 py-2 rounded-lg text-xs font-semibold bg-red-950 text-red-300 border border-red-800 hover:bg-red-900 transition-colors"
          >
            Retry Connection
          </button>
        </div>
      )}

      {/* Empty State */}
      {!loading && !error && drafts.length === 0 && (
        <div className="border border-gray-800 bg-gray-900/10 rounded-2xl p-16 text-center max-w-xl mx-auto my-12">
          <div className="w-12 h-12 bg-indigo-500/10 text-indigo-400 rounded-full flex items-center justify-center mx-auto mb-4">
            ✓
          </div>
          <h3 className="text-white font-semibold mb-1">Queue Cleared</h3>
          <p className="text-sm text-gray-400">
            All generated content has been processed. Run the backend batch generation cron job to queue more drafts.
          </p>
        </div>
      )}

      {/* Approvals Grid */}
      {!loading && !error && drafts.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 animate-fade-in">
          {drafts.map((draft) => (
            <div
              key={draft.id}
              className="border border-gray-800 bg-gray-900/30 backdrop-blur-md rounded-xl flex flex-col justify-between overflow-hidden shadow-lg transition-all duration-300 ease-in-out transform hover:-translate-y-1 hover:border-indigo-500/50"
            >
              {/* Card Header Info */}
              <div className="p-6 border-b border-gray-900 flex items-center justify-between bg-gray-950/20">
                <div className="flex items-center gap-2">
                  <span className="px-2.5 py-1 rounded bg-indigo-500/10 border border-indigo-500/20 text-[10px] uppercase font-bold tracking-wider text-indigo-300">
                    {draft.platform}
                  </span>
                  <span className="text-xs text-gray-400 font-medium truncate max-w-[150px]">
                    {draft.topic}
                  </span>
                </div>
                <div className="text-right">
                  <span className="text-[10px] block text-gray-500 uppercase tracking-widest font-bold">
                    Score
                  </span>
                  <span className="text-sm font-semibold text-emerald-400">
                    {draft.final_score !== undefined ? draft.final_score.toFixed(1) : "N/A"}
                  </span>
                </div>
              </div>

              {/* Card Body - Content Draft */}
              <div className="p-6 flex-1 flex flex-col justify-between">
                {/* If the draft has an image generated by the backend, display it elegantly */}
                {draft.image_url && (
                  <div className="my-4 overflow-hidden rounded-xl border border-white/10 bg-black/40 aspect-video relative">
                    <img 
                      src={draft.image_url} 
                      alt="AI Generated Contextual Graphic" 
                      className="w-full h-full object-cover opacity-90 hover:opacity-100 transition-opacity duration-300"
                      loading="lazy"
                    />
                  </div>
                )}

                <div className="text-gray-300 text-sm leading-relaxed whitespace-pre-wrap font-medium">
                  {draft.content_text}
                </div>
                
                {draft.feedback_notes && (
                  <div className="mt-4 p-3 bg-amber-500/5 border border-amber-500/10 rounded-lg text-xs text-amber-300">
                    <strong>Feedback History:</strong> {draft.feedback_notes}
                  </div>
                )}
              </div>

              {/* Card Actions Footer */}
              <div className="px-6 py-4 border-t border-gray-900 bg-gray-950/40 grid grid-cols-2 gap-3">
                <button
                  onClick={() => handleReject(draft.id)}
                  className="w-full py-2.5 rounded-lg text-xs font-semibold border border-red-500/30 bg-red-500/10 hover:bg-red-500/20 text-red-200 transition-all duration-200 active:scale-[0.98]"
                >
                  Reject
                </button>
                <button
                  onClick={() => handleApprove(draft.id)}
                  className="w-full py-2.5 rounded-lg text-xs font-semibold border border-emerald-500/30 bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-200 transition-all duration-200 active:scale-[0.98]"
                >
                  Approve
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
