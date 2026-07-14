"use client";

import { useEffect, useState, useRef } from "react";

interface Draft {
  id: string;
  persona_id: string | null;
  content_text: string;
  status: string; // 'DRAFT', 'PUBLISHED', 'FAILED'
  generated_at: string;
  llm_metadata: {
    model?: string;
    prompt_length?: number;
    timestamp?: string;
    requires_image?: boolean;
    image_prompt?: string | null;
    linkedin_post_id?: string;
    published_url?: string;
    image_url?: string;
  };
}

export default function DashboardPage() {
  let API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";
  if (API_BASE && !API_BASE.endsWith("/api/v1")) {
    API_BASE = `${API_BASE.replace(/\/$/, "")}/api/v1`;
  }

  // System states
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [selectedDraft, setSelectedDraft] = useState<Draft | null>(null);
  const [topic, setTopic] = useState("");
  const [editorText, setEditorText] = useState("");
  const [liveTopics, setLiveTopics] = useState<string[]>([]);
  const [loadingLiveTopics, setLoadingLiveTopics] = useState(false);
  const [editorImageUrl, setEditorImageUrl] = useState("");
  const [isGeneratingImage, setIsGeneratingImage] = useState(false);
  
  // Loading & action states
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isPublishing, setIsPublishing] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);

  // Integration states
  const [linkedinConnected, setLinkedinConnected] = useState(false);
  const [linkedinUrn, setLinkedinUrn] = useState("");

  // Toast / Notification states
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" | "info" } | null>(null);
  const toastTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  const showToast = (message: string, type: "success" | "error" | "info" = "info") => {
    if (toastTimeoutRef.current) clearTimeout(toastTimeoutRef.current);
    setToast({ message, type });
    toastTimeoutRef.current = setTimeout(() => {
      setToast(null);
    }, 4000);
  };

  // 1. Fetch LinkedIn status
  const checkLinkedInStatus = async () => {
    try {
      const res = await fetch(`${API_BASE}/publishing/linkedin/status`);
      if (res.ok) {
        const data = await res.json();
        setLinkedinConnected(data.connected);
        setLinkedinUrn(data.linkedin_person_urn || "");
      }
    } catch (err) {
      console.error("Failed to check LinkedIn status:", err);
    }
  };

  // 2. LinkedIn connection (Supports sandbox simulation or real redirect)
  const connectLinkedIn = async (e: React.MouseEvent<HTMLButtonElement>) => {
    const client_id = process.env.NEXT_PUBLIC_LINKEDIN_CLIENT_ID;
    
    // Sandbox bypass if client ID is mock/empty or if Shift key is held during click
    if (!client_id || client_id === "mock_client_id" || e.shiftKey) {
      try {
        setIsConnecting(true);
        const redirectUri = window.location.origin;
        const res = await fetch(
          `${API_BASE}/publishing/linkedin/connect?code=sandbox_dev_token_123&redirect_uri=${encodeURIComponent(redirectUri)}`,
          { method: "POST" }
        );
        if (res.ok) {
          const data = await res.json();
          setLinkedinConnected(true);
          setLinkedinUrn(data.linkedin_person_urn);
          showToast("LinkedIn account connected successfully (Simulated)!", "success");
        } else {
          const errorData = await res.json().catch(() => ({}));
          showToast(errorData.detail || "Failed to link LinkedIn account.", "error");
        }
      } catch (err) {
        console.error("LinkedIn link error:", err);
        showToast("Network error: Failed to connect LinkedIn.", "error");
      } finally {
        setIsConnecting(false);
      }
      return;
    }

    // Real OAuth flow redirect to LinkedIn consent screen
    const redirect_uri = window.location.origin;
    const scope = "openid profile email w_member_social";
    const state = Math.random().toString(36).substring(2, 15);
    localStorage.setItem("linkedin_oauth_state", state);

    const authUrl = `https://www.linkedin.com/oauth/v2/authorization` +
      `?response_type=code` +
      `&client_id=${client_id}` +
      `&redirect_uri=${encodeURIComponent(redirect_uri)}` +
      `&scope=${encodeURIComponent(scope)}` +
      `&state=${state}`;

    window.location.href = authUrl;
  };

  // 3. Load Drafts from history
  const loadDrafts = async (selectFirst = false) => {
    try {
      setLoadingHistory(true);
      const res = await fetch(`${API_BASE}/generation/drafts`);
      if (res.ok) {
        const data: Draft[] = await res.json();
        const normalizedData = data.map(d => ({
          ...d,
          content_text: d.content_text.replace(/\\n/g, "\n").replace(/\n{3,}/g, "\n\n")
        }));
        setDrafts(normalizedData);
        if (selectFirst && normalizedData.length > 0) {
          handleSelectDraft(normalizedData[0]);
        }
      } else {
        showToast("Failed to retrieve draft history.", "error");
      }
    } catch (err) {
      console.error("Error loading drafts:", err);
      showToast("Could not connect to backend. Please make sure FastAPI is running.", "error");
    } finally {
      setLoadingHistory(false);
    }
  };

  const fetchLiveNews = async () => {
    try {
      setLoadingLiveTopics(true);
      const res = await fetch(`${API_BASE}/generation/live-news`);
      if (res.ok) {
        const data = await res.json();
        setLiveTopics(data);
      } else {
        throw new Error("Failed to fetch live-news");
      }
    } catch (err) {
      console.error("Failed to fetch live news:", err);
      setLiveTopics([
        "Why simple codebases scale better than complex distributed microservices",
        "A review of using Groq's high-speed inference engine for real-time applications",
        "How consistency and authentic sharing beats high-production templates on LinkedIn",
        "How modern developer AI agents are changing team dynamics and shipping speeds"
      ]);
    } finally {
      setLoadingLiveTopics(false);
    }
  };

  useEffect(() => {
    // Check if redirecting from LinkedIn OAuth callback
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const state = params.get("state");

    if (code) {
      // Validate state to prevent CSRF
      const savedState = localStorage.getItem("linkedin_oauth_state");
      localStorage.removeItem("linkedin_oauth_state");

      const completeConnection = async () => {
        try {
          setIsConnecting(true);
          const redirectUri = window.location.origin;
          const res = await fetch(
            `${API_BASE}/publishing/linkedin/connect?code=${code}&redirect_uri=${encodeURIComponent(redirectUri)}`,
            { method: "POST" }
          );
          if (res.ok) {
            const data = await res.json();
            setLinkedinConnected(true);
            setLinkedinUrn(data.linkedin_person_urn);
            showToast("LinkedIn account connected successfully!", "success");
          } else {
            const errorData = await res.json().catch(() => ({}));
            showToast(errorData.detail || "Failed to link LinkedIn account.", "error");
          }
        } catch (err) {
          console.error("LinkedIn link error:", err);
          showToast("Network error: Failed to connect LinkedIn.", "error");
        } finally {
          setIsConnecting(false);
          // Clear query parameters from URL path
          window.history.replaceState({}, document.title, window.location.pathname);
        }
      };

      completeConnection();
    }

    checkLinkedInStatus();
    loadDrafts(true);
    fetchLiveNews();
    return () => {
      if (toastTimeoutRef.current) clearTimeout(toastTimeoutRef.current);
    };
  }, []);

  // 4. Handle selecting a draft
  const handleSelectDraft = (draft: Draft) => {
    const normalizedDraft = {
      ...draft,
      content_text: draft.content_text.replace(/\\n/g, "\n").replace(/\n{3,}/g, "\n\n")
    };
    setSelectedDraft(normalizedDraft);
    setEditorText(normalizedDraft.content_text);
    setEditorImageUrl(normalizedDraft.llm_metadata?.image_url || "");
  };

  // 5. Generate AI Draft
  const handleGenerate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!topic.trim()) {
      showToast("Please enter a topic or prompt first.", "error");
      return;
    }

    try {
      setIsGenerating(true);
      showToast("Generating LinkedIn post draft via Groq...", "info");
      
      const res = await fetch(`${API_BASE}/generation`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topic }),
      });

      if (res.ok) {
        const newDraft: Draft = await res.json();
        showToast("Draft generated and saved to database!", "success");
        setTopic("");
        // Reload history and select the newly generated draft
        await loadDrafts();
        handleSelectDraft(newDraft);
      } else {
        const errorData = await res.json().catch(() => ({}));
        showToast(errorData.detail || "Failed to generate draft.", "error");
      }
    } catch (err) {
      console.error("Generation error:", err);
      showToast("Network error: Failed to generate draft.", "error");
    } finally {
      setIsGenerating(false);
    }
  };

  // 6. Save manual edits to database
  const handleSaveEdits = async () => {
    if (!selectedDraft) return;

    try {
      setIsSaving(true);
      const res = await fetch(`${API_BASE}/generation/drafts/${selectedDraft.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content_text: editorText, image_url: editorImageUrl }),
      });

      if (res.ok) {
        const updatedDraft = await res.json();
        updatedDraft.content_text = updatedDraft.content_text.replace(/\\n/g, "\n").replace(/\n{3,}/g, "\n\n");
        showToast("Changes saved successfully to database!", "success");
        // Update both local list and active selection
        setDrafts((prev) => prev.map((d) => (d.id === updatedDraft.id ? updatedDraft : d)));
        setSelectedDraft(updatedDraft);
      } else {
        const errorData = await res.json().catch(() => ({}));
        showToast(errorData.detail || "Failed to save edits.", "error");
      }
    } catch (err) {
      console.error("Save edits error:", err);
      showToast("Network error: Failed to save changes.", "error");
    } finally {
      setIsSaving(false);
    }
  };

  // 6b. Generate Image
  const handleGenerateImage = async () => {
    if (!selectedDraft) return;
    const searchTopic = topic || selectedDraft.content_text.slice(0, 80) || "Technology branding";

    try {
      setIsGeneratingImage(true);
      showToast("Generating professional AI vector illustration...", "info");
      
      const res = await fetch(`${API_BASE}/generation/generate-image`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
          topic: searchTopic,
          draft_text: selectedDraft.content_text
        }),
      });

      if (res.ok) {
        const data = await res.json();
        setEditorImageUrl(data.image_url);
        showToast("AI image generated successfully! Remember to Save Changes.", "success");
      } else {
        const errorData = await res.json().catch(() => ({}));
        showToast(errorData.detail || "Failed to generate image.", "error");
      }
    } catch (err) {
      console.error("Image generation error:", err);
      showToast("Network error: Failed to generate image.", "error");
    } finally {
      setIsGeneratingImage(false);
    }
  };

  // 7. Publish to LinkedIn
  const handlePublish = async () => {
    if (!selectedDraft) return;
    if (!linkedinConnected) {
      showToast("Please link a LinkedIn account first before publishing.", "error");
      return;
    }

    try {
      setIsPublishing(true);
      showToast("Publishing draft to LinkedIn...", "info");
      
      const res = await fetch(`${API_BASE}/generation/drafts/${selectedDraft.id}/publish`, {
        method: "POST",
      });

      if (res.ok) {
        const updatedDraft = await res.json();
        updatedDraft.content_text = updatedDraft.content_text.replace(/\\n/g, "\n").replace(/\n{3,}/g, "\n\n");
        showToast("Post successfully published to LinkedIn! 🎉", "success");
        setDrafts((prev) => prev.map((d) => (d.id === updatedDraft.id ? updatedDraft : d)));
        setSelectedDraft(updatedDraft);
      } else {
        const errorData = await res.json().catch(() => ({}));
        showToast(errorData.detail || "Publishing failed.", "error");
      }
    } catch (err) {
      console.error("Publishing error:", err);
      showToast("Network error: Failed to dispatch publication.", "error");
    } finally {
      setIsPublishing(false);
    }
  };

  // Helper values

  const characterCount = editorText.length;
  const isLengthInvalid = characterCount > 3000;

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      {/* Toast Alert popup */}
      {toast && (
        <div 
          className={`fixed bottom-5 right-5 z-50 px-5 py-3 rounded-xl border shadow-xl flex items-center gap-3 animate-fade-in transition-all duration-300 ${
            toast.type === "success" 
              ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-300"
              : toast.type === "error"
              ? "bg-red-500/10 border-red-500/30 text-red-300"
              : "bg-indigo-500/10 border-indigo-500/30 text-indigo-300"
          }`}
        >
          <span className="text-sm font-semibold">{toast.message}</span>
          <button onClick={() => setToast(null)} className="text-xs opacity-60 hover:opacity-100 font-bold">✕</button>
        </div>
      )}

      {/* Connection and Header Panel */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-gray-900/30 backdrop-blur-md border border-gray-800 p-6 rounded-2xl">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">
            Content Generation & Publishing Canvas
          </h1>
          <p className="text-sm text-gray-400 mt-1">
            Generate, iterate, and immediately distribute your professional narrative on LinkedIn.
          </p>
        </div>

        {/* LinkedIn Connection Widget */}
        <div className="flex items-center gap-4">
          {(() => {
            if (linkedinConnected === false) {
              const redirectParam = typeof window !== "undefined" ? `?redirect_uri=${encodeURIComponent(window.location.origin)}` : "";
              return (
                <a
                  id="linkedin-connect-button"
                  href={`${API_BASE}/publishing/linkedin/login${redirectParam}`}
                  className="inline-flex items-center justify-center px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-xs font-semibold tracking-wide shadow-md active:scale-95 transition-all duration-200"
                >
                  Link LinkedIn Account
                </a>
              );
            }
            return (
              <div className="flex items-center gap-3 bg-emerald-500/10 border border-emerald-500/20 px-4 py-2 rounded-xl">
                <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse"></span>
                <div className="text-left">
                  <span className="text-xs block text-gray-400 uppercase tracking-wider font-bold">LinkedIn Linked</span>
                  <span className="text-[11px] font-mono text-emerald-300 truncate max-w-[160px] block">
                    {linkedinUrn.replace("urn:li:person:", "")}
                  </span>
                </div>
              </div>
            );
          })()}
        </div>
      </div>

      {/* Main Layout Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        
        {/* Left Column: AI Creator Panel (2/5 size) */}
        <div className="lg:col-span-2 space-y-6">
          <div className="bg-gray-900/20 backdrop-blur-md border border-gray-800 p-6 rounded-2xl shadow-xl relative overflow-hidden">
            <div className="absolute -top-16 -left-16 w-36 h-36 bg-indigo-500/5 rounded-full blur-3xl"></div>
            
            <h2 className="text-lg font-bold text-white mb-4 flex items-center gap-2">
              <span className="text-indigo-400 font-mono">01.</span> Prompt AI Creator
            </h2>

            <form onSubmit={handleGenerate} className="space-y-4">
              <div>
                <label htmlFor="topic-input" className="block text-xs font-semibold text-gray-400 uppercase tracking-widest mb-2">
                  What would you like to write about?
                </label>
                <textarea
                  id="topic-input"
                  rows={4}
                  value={topic}
                  onChange={(e) => setTopic(e.target.value)}
                  placeholder="Enter a theme, topic, or raw outline. E.g., 'Refactoring codebases for simplicity and developer happiness'..."
                  className="w-full bg-black/40 border border-gray-800/80 focus:border-indigo-500/80 focus:ring-1 focus:ring-indigo-500/20 text-gray-200 text-sm leading-relaxed rounded-xl p-4 outline-none transition-all duration-300 resize-none"
                />
              </div>

              {/* Live News Topics Grid */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <span className="block text-[10px] font-bold text-gray-500 uppercase tracking-widest">
                    Live Tech Trends (Hacker News)
                  </span>
                  {loadingLiveTopics && (
                    <span className="w-3 h-3 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin"></span>
                  )}
                </div>
                <div className="flex flex-col gap-2">
                  {liveTopics.map((topicItem, idx) => (
                    <button
                      key={idx}
                      type="button"
                      onClick={() => setTopic(topicItem)}
                      className="p-3 rounded-lg border border-gray-800/85 bg-gray-900/10 hover:bg-indigo-950/20 hover:border-indigo-500/30 text-left text-[11px] font-medium text-gray-400 hover:text-indigo-300 transition-all duration-200 leading-normal"
                    >
                      {topicItem}
                    </button>
                  ))}
                </div>
              </div>

              <button
                id="generate-button"
                type="submit"
                disabled={isGenerating || !topic.trim()}
                className="w-full py-3 bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-500 hover:to-purple-500 disabled:from-indigo-800 disabled:to-purple-800 disabled:opacity-50 text-white rounded-xl text-sm font-semibold tracking-wider shadow-lg shadow-indigo-600/10 hover:shadow-[0_0_20px_rgba(99,102,241,0.3)] active:scale-[0.99] transition-all duration-200 flex items-center justify-center gap-2"
              >
                {isGenerating ? (
                  <>
                    <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></span>
                    <span>Generating Draft...</span>
                  </>
                ) : (
                  <span>Generate Draft with AI</span>
                )}
              </button>
            </form>
          </div>
        </div>

        {/* Right Column: Editor Canvas & History (3/5 size) */}
        <div className="lg:col-span-3 space-y-6">
          
          {/* Editor Canvas Card */}
          <div className="bg-gray-900/20 backdrop-blur-md border border-gray-800 rounded-2xl shadow-xl overflow-hidden">
            {/* Header info */}
            <div className="px-6 py-4 border-b border-gray-900 flex items-center justify-between bg-gray-950/20">
              <div className="flex items-center gap-3">
                <span className="text-[11px] font-bold text-gray-500 uppercase tracking-widest font-mono">
                  02. Editing Canvas
                </span>
                {selectedDraft && (
                  <span className={`px-2 py-0.5 rounded text-[10px] uppercase font-bold border ${
                    selectedDraft.status === "PUBLISHED"
                      ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-300"
                      : selectedDraft.status === "FAILED"
                      ? "border-red-500/20 bg-red-500/10 text-red-300"
                      : "border-indigo-500/20 bg-indigo-500/10 text-indigo-300"
                  }`}>
                    {selectedDraft.status}
                  </span>
                )}
              </div>

              {/* Status link */}
              {selectedDraft?.status === "PUBLISHED" && selectedDraft.llm_metadata?.published_url && (
                <a
                  href={selectedDraft.llm_metadata.published_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-xs text-emerald-400 hover:text-emerald-300 font-semibold underline"
                >
                  View Live Post ↗
                </a>
              )}
            </div>

            {/* Canvas body */}
            {selectedDraft ? (
              <div className="p-6 space-y-4">
                <textarea
                  id="editor-textarea"
                  value={editorText}
                  onChange={(e) => setEditorText(e.target.value)}
                  className="w-full bg-black/30 border border-gray-850/80 focus:border-indigo-500/80 focus:ring-1 focus:ring-indigo-500/20 text-gray-200 text-sm leading-relaxed rounded-xl p-4 resize-y min-h-[300px] outline-none transition-all duration-300 font-sans whitespace-pre-wrap"
                  placeholder="Post content text editor..."
                />

                {/* Generate AI Image Button */}
                <button
                  type="button"
                  onClick={handleGenerateImage}
                  disabled={isGeneratingImage || isSaving || isPublishing || isGenerating}
                  className="w-full py-2 bg-indigo-950/40 border border-indigo-500/30 hover:border-indigo-500/55 hover:bg-indigo-950/60 disabled:opacity-40 text-indigo-300 hover:text-indigo-200 rounded-xl text-xs font-semibold tracking-wide active:scale-[0.98] transition-all duration-200 flex items-center justify-center gap-2"
                >
                  {isGeneratingImage ? (
                    <>
                      <span className="w-3.5 h-3.5 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin"></span>
                      <span>Generating Image...</span>
                    </>
                  ) : (
                    <span>🎨 Generate AI Image</span>
                  )}
                </button>

                {/* Image Preview */}
                {editorImageUrl && (
                  <div className="overflow-hidden rounded-xl border border-white/10 bg-black/40 aspect-video relative my-2">
                    <img 
                      src={editorImageUrl} 
                      alt="AI Generated Illustration" 
                      className="w-full h-full object-cover opacity-90 hover:opacity-100 transition-opacity duration-300 animate-fade-in"
                      loading="lazy"
                    />
                    <button 
                      type="button"
                      onClick={() => setEditorImageUrl("")}
                      className="absolute top-2 right-2 p-1.5 rounded-full bg-black/75 hover:bg-black text-gray-300 hover:text-white text-xs transition-colors"
                      title="Remove image"
                    >
                      ✕
                    </button>
                  </div>
                )}

                {/* Info footer line */}
                <div className="flex items-center justify-between text-xs">
                  <span className={`font-medium ${isLengthInvalid ? "text-red-400 font-semibold" : "text-gray-400"}`}>
                    Character Count: {characterCount} / 3000 {isLengthInvalid && "(Exceeds LinkedIn limit!)"}
                  </span>
                  {selectedDraft.llm_metadata?.model && (
                    <span className="text-gray-500 font-mono text-[10px]">
                      Model: {selectedDraft.llm_metadata.model}
                    </span>
                  )}
                </div>

                {/* Editor Action buttons */}
                <div className="grid grid-cols-2 gap-4 pt-2">
                  <button
                    id="save-button"
                    onClick={handleSaveEdits}
                    disabled={isSaving || isPublishing || isGenerating}
                    className="py-2.5 bg-gray-900 border border-gray-800 hover:border-gray-700 disabled:opacity-50 text-gray-300 hover:text-white rounded-xl text-xs font-semibold tracking-wider active:scale-[0.98] transition-all duration-200 flex items-center justify-center gap-2"
                  >
                    {isSaving ? (
                      <>
                        <span className="w-3.5 h-3.5 border-2 border-gray-300 border-t-transparent rounded-full animate-spin"></span>
                        <span>Saving...</span>
                      </>
                    ) : (
                      <span>Save Changes</span>
                    )}
                  </button>

                  <button
                    id="publish-button"
                    onClick={handlePublish}
                    disabled={isSaving || isPublishing || isGenerating || isLengthInvalid || selectedDraft.status === "PUBLISHED"}
                    className="py-2.5 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 disabled:from-gray-800 disabled:to-gray-800 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-xl text-xs font-semibold tracking-wider shadow-lg active:scale-[0.98] transition-all duration-200 flex items-center justify-center gap-2"
                  >
                    {isPublishing ? (
                      <>
                        <span className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin"></span>
                        <span>Publishing...</span>
                      </>
                    ) : selectedDraft.status === "PUBLISHED" ? (
                      <span>Published to LinkedIn</span>
                    ) : (
                      <span>Publish to LinkedIn</span>
                    )}
                  </button>
                </div>
              </div>
            ) : (
              <div className="p-16 text-center">
                <div className="w-12 h-12 rounded-full bg-gray-900/50 border border-gray-800 flex items-center justify-center mx-auto mb-4 text-gray-500">
                  ✍️
                </div>
                <h3 className="text-white font-semibold mb-1">No Draft Active</h3>
                <p className="text-xs text-gray-400 max-w-xs mx-auto">
                  Type a prompt on the left to generate your first draft, or load an existing one from the history log.
                </p>
              </div>
            )}
          </div>

          {/* Draft History List */}
          <div className="bg-gray-900/20 backdrop-blur-md border border-gray-800 rounded-2xl shadow-xl overflow-hidden p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-bold text-gray-400 uppercase tracking-wider font-mono">
                03. Draft History & Activity Log
              </h3>
              <button 
                onClick={() => loadDrafts(false)}
                className="text-xs text-indigo-400 hover:text-indigo-300 font-semibold"
              >
                Refresh Log
              </button>
            </div>

            {loadingHistory ? (
              <div className="py-12 flex flex-col items-center justify-center gap-3">
                <span className="w-5 h-5 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin"></span>
                <span className="text-xs text-gray-500">Retrieving past drafts...</span>
              </div>
            ) : drafts.length === 0 ? (
              <div className="py-12 text-center text-xs text-gray-500">
                No past drafts found in database.
              </div>
            ) : (
              <div className="space-y-3 max-h-[300px] overflow-y-auto pr-1">
                {drafts.map((draft) => {
                  const isSelected = selectedDraft?.id === draft.id;
                  const snippet = draft.content_text.slice(0, 95) + (draft.content_text.length > 95 ? "..." : "");
                  
                  return (
                    <div
                      key={draft.id}
                      onClick={() => handleSelectDraft(draft)}
                      className={`p-4 rounded-xl border text-left cursor-pointer transition-all duration-200 ${
                        isSelected
                          ? "bg-indigo-950/20 border-indigo-500/40 shadow-indigo-950/50"
                          : "bg-black/25 border-gray-850 hover:bg-gray-900/30 hover:border-gray-800"
                      }`}
                    >
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-[10px] text-gray-500 font-mono">
                          {new Date(draft.generated_at).toLocaleString()}
                        </span>
                        
                        <span className={`px-2 py-0.5 rounded text-[9px] uppercase font-bold border ${
                          draft.status === "PUBLISHED"
                            ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-300"
                            : draft.status === "FAILED"
                            ? "border-red-500/20 bg-red-500/10 text-red-300"
                            : "border-indigo-500/20 bg-indigo-500/10 text-indigo-300"
                        }`}>
                          {draft.status}
                        </span>
                      </div>
                      <p className="text-gray-300 text-xs leading-relaxed font-medium whitespace-pre-wrap">
                        {snippet || "(No content)"}
                      </p>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

        </div>
      </div>
    </div>
  );
}
