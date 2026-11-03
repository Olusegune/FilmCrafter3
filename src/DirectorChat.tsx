import { useEffect, useState } from "react";
import { api, errorText, type AgentProposal, type Brain } from "./api";

type Message = { role: "user" | "assistant"; content: string };
const STARTERS = ["Summarize this production", "Which shots still need keyframes?", "Suggest a visual direction", "What should I work on next?"];

export function DirectorChat({ dir, onClose, onChanged }: { dir: string; onClose: () => void; onChanged: () => void }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [immediate, setImmediate] = useState(false);
  const [proposals, setProposals] = useState<AgentProposal[]>([]);
  const [brain, setBrain] = useState<Brain | null>(null);
  const refresh = () => api.directorChat<AgentProposal[]>(dir, "proposals").then(setProposals).catch(() => {});
  useEffect(() => { void refresh(); void api.aiBrain<Brain>("get").then(setBrain); }, [dir]); // eslint-disable-line react-hooks/exhaustive-deps
  const send = async (value = text) => {
    const prompt = value.trim(); if (!prompt || busy) return;
    const next = [...messages, { role: "user" as const, content: prompt }]; setMessages(next); setText(""); setBusy(true); setError("");
    try {
      const r = await api.directorChat(dir, "turn", { message: prompt, history: messages, immediate });
      setMessages([...next, { role: "assistant", content: r.reply }]); setProposals(r.proposals); if (immediate && r.steps.length) onChanged();
    } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  };
  const decide = async (p: AgentProposal, action: "apply" | "reject") => {
    setBusy(true); setError("");
    try {
      const r = await api.directorChat<{ requires_spend_confirmation?: boolean }>(dir, action, { id: p.id });
      if (r.requires_spend_confirmation) setError("Paid work was not started. Open Manual Studio to review the live price and confirm it there.");
      await refresh(); onChanged();
    } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  };
  const pending = proposals.filter((p) => p.state === "pending");
  return <div className="director-chat-backdrop" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
    <section className="director-chat" role="dialog" aria-modal="true" aria-labelledby="director-chat-title">
      <header><div><h2 id="director-chat-title">Ask the director</h2><p>Plan, inspect and propose changes to this project.</p></div><button className="icon-btn" onClick={onClose} aria-label="Close">×</button></header>
      <div className="director-chat-body">
        {!messages.length && <div className="director-chat-welcome"><b>How can I help with your film?</b><p>I can inspect shots and keyframes, suggest a filmmaker craft profile, or prepare a revision for your approval.</p><div>{STARTERS.map((x) => <button key={x} onClick={() => send(x)}>{x}</button>)}</div></div>}
        {messages.map((m, i) => <div key={i} className={`director-message ${m.role}`}>{m.content}</div>)}
        {busy && <div className="director-message assistant" role="status">Thinking…</div>}
        {!!pending.length && <div className="director-suggestions"><h3>Review {pending.length} suggestion{pending.length === 1 ? "" : "s"}</h3>{pending.map((p) => <article key={p.id}><div><b>{label(p.tool)}</b><small>{p.risk === "spend" ? "Paid request · never starts from chat" : "Project change"}</small><code>{summary(p)}</code></div><div><button className="btn primary small" onClick={() => decide(p, "apply")} disabled={busy}>{p.risk === "spend" ? "Review cost" : "Apply"}</button><button className="btn ghost small" onClick={() => decide(p, "reject")} disabled={busy}>Reject</button></div></article>)}</div>}
      </div>
      <footer><label className="director-immediate"><input type="checkbox" checked={immediate} onChange={(e) => setImmediate(e.target.checked)} /> Make non-paid changes straight away</label><div className="director-compose"><textarea aria-label="Message the director" value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(); } }} placeholder="Ask about the film or request a change…" /><button onClick={() => send()} disabled={busy || !text.trim()} aria-label="Send">→</button></div><small>Project details are sent to {brain ? providerName(brain.provider) : "your chosen AI provider"}. Paid generation always requires a separate cost confirmation.</small>{error && <p className="error-text" role="alert">{error}</p>}</footer>
    </section>
  </div>;
}

function label(tool: string) { return ({ set_director_style: "Use filmmaker craft profile", clear_director_style: "Remove filmmaker craft profile", request_revision: "Request focused revision", request_render: "Prepare generation request" } as Record<string,string>)[tool] ?? tool.replace(/_/g, " "); }
function summary(p: AgentProposal) { const a = p.args; return String(a.note ?? a.id ?? (Array.isArray(a.shots) ? `${a.kind}: ${a.shots.length} shot(s)` : "")); }
function providerName(p: Brain["provider"]) { return ({ openai: "OpenAI", openrouter: "OpenRouter", gemini: "Google Gemini", ollama: "your local Ollama server", lmstudio: "your local LM Studio server" })[p]; }
