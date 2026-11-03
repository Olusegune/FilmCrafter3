import { useEffect, useMemo, useState } from "react";
import { api, errorText, type DirectorStyle } from "./api";
import { Sheet } from "./Sheet";

export function DirectorStyleSheet({ dir, onClose, onChanged }: { dir: string; onClose: () => void; onChanged?: () => void }) {
  const [styles, setStyles] = useState<DirectorStyle[]>([]), [current, setCurrent] = useState<string | null>(null);
  const [region, setRegion] = useState("All"), [query, setQuery] = useState(""), [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState(""), [busy, setBusy] = useState(false);
  useEffect(() => { api.directorStyle(dir, "list").then((r) => { setStyles(r.styles); setCurrent(r.current); setSelected(r.current); }).catch((e) => setError(errorText(e))); }, [dir]);
  const regions = useMemo(() => ["All", ...new Set(styles.map((x) => x.region))], [styles]);
  const shown = styles.filter((x) => (region === "All" || x.region === region) && (!query || `${x.name} ${x.origin} ${x.known_for}`.toLowerCase().includes(query.toLowerCase())));
  const picked = styles.find((x) => x.id === selected);
  const choose = async () => { if (!picked) return; setBusy(true); setError(""); try { await api.directorStyle(dir, "set", { id: picked.id }); setCurrent(picked.id); onChanged?.(); } catch (e) { setError(errorText(e)); } finally { setBusy(false); } };
  const clear = async () => { setBusy(true); try { await api.directorStyle(dir, "clear"); setCurrent(null); setSelected(null); onChanged?.(); } catch (e) { setError(errorText(e)); } finally { setBusy(false); } };
  return <Sheet label="Director style" className="director-style-sheet" onDismiss={onClose}>
    <div className="vs-head"><div><h2>Director style</h2><p className="sub">Optional craft guidance for camera, lens, light, colour, pace and performance. It never changes your story, look, cast, timing or approved work.</p></div><button className="icon-btn" onClick={onClose} aria-label="Close">×</button></div>
    <div className="ds-filters"><select aria-label="Region" value={region} onChange={(e) => setRegion(e.target.value)}>{regions.map((r) => <option key={r}>{r}</option>)}</select><input className="text-input" type="search" aria-label="Search filmmakers" placeholder="Search filmmakers or regions…" value={query} onChange={(e) => setQuery(e.target.value)} /></div>
    {error && <div className="error-text" role="alert">{error}</div>}
    <div className="ds-layout"><div className="ds-list" role="list" aria-label="Filmmaker styles">{shown.map((x) => <button role="listitem" key={x.id} className={selected === x.id ? "on" : ""} onClick={() => setSelected(x.id)}><b>{x.name}</b><span>{x.origin}</span>{current === x.id && <em>In use</em>}</button>)}</div>
      <div className="ds-detail">{picked ? <><p className="eyebrow">{picked.region}</p><h3>{picked.name}</h3><p className="sub">{picked.known_for}</p><dl>{Object.entries(picked.traits).map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl><p className="dim">Only these craft traits reach the AI provider. The filmmaker's name is kept out of generation prompts.</p></> : <div className="empty">Choose a filmmaker to read the craft traits.</div>}</div></div>
    <div className="sheet-actions"><button className="btn ghost" disabled={!current || busy} onClick={clear}>Clear style</button><button className="btn hero" disabled={!picked || busy} onClick={choose}>Use this director style</button></div>
  </Sheet>;
}
