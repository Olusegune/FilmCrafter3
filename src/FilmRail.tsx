import type { ReactNode } from "react";
import * as I from "./icons";

export type RailItem = { id: string; label: string; icon: ReactNode; active?: boolean; done?: boolean; next?: boolean; disabled?: boolean; badge?: string; title?: string; onClick?: () => void };

/**
 * The left rail, the same one the timeline Studio has, so every screen of a film has the same way around: Home at the top, the steps of the golden path in order
 * (a tick when a step is done, a dot on the one to do next), and Settings at the bottom.
 */
export function FilmRail({ items, onHome, onSettings }: { items: RailItem[]; onHome: () => void; onSettings?: () => void }) {
  return (
    <nav className="rail film-rail" aria-label="Main">
      <div className="logo"><I.Mark size={26} /></div>
      <button data-k="home" onClick={onHome} title="Home: all your films"><I.Home /><span>Home</span></button>
      <div className="rail-sep" role="separator" />
      {items.map((it) => (
        <button key={it.id} data-k={it.id} className={[it.active ? "active" : "", it.done ? "done" : "", it.next ? "next" : ""].filter(Boolean).join(" ")} disabled={it.disabled} onClick={it.onClick}
                title={it.title ?? it.label} aria-current={it.active ? "page" : undefined}>
          {it.icon}<span>{it.label}</span>
          {it.done ? <i className="rail-tick" aria-label="done"><I.Check size={9} /></i> : it.next ? <i className="rail-next" aria-label="next step" /> : it.badge ? <i className="rail-badge">{it.badge}</i> : null}
        </button>))}
      <div className="spacer" />
      {onSettings && <button data-k="settings" onClick={onSettings} title="Settings"><I.Gear /><span>Settings</span></button>}
    </nav>
  );
}
