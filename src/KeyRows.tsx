import { useState } from "react";
import { errorText, type KeyStatus } from "./api";
import { Check } from "./icons";

export type KeyProvider = { id: keyof KeyStatus; name: string; purpose: string };

/** The keys by what they are for, in the order a newcomer needs them: one provider of pictures and video first, the rest optional. */
export const KEY_GROUPS: { title: string; hint: string; ids: (keyof KeyStatus)[] }[] = [
  { title: "Pictures and video", hint: "You need one of these to make anything. Kie.ai is the easiest start: the most models at the lowest prices.", ids: ["kie", "fal", "google", "byteplus"] },
  { title: "Writing helper and picture checks", hint: "Optional. Plans story steps, suggests shots and checks finished pictures for hands and faces.", ids: ["openai", "anthropic", "openrouter"] },
  { title: "Voices", hint: "Optional. A custom voice for each character.", ids: ["elevenlabs"] },
];

/**
 * The keys, grouped. A key is saved in the computer's credential store (never in a project); this only asks `onSave` / `onRemove` to do it and says what happened. A row always has the same
 * shape (name, state, one box and Save), so nothing moves when a key is added or removed.
 */
export function KeyGroups({ providers, status, onSave, onRemove, groups = KEY_GROUPS }: {
  providers: KeyProvider[]; status: KeyStatus; onSave: (id: string, key: string) => Promise<void>; onRemove: (id: string) => Promise<void>; groups?: typeof KEY_GROUPS;
}) {
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState<Record<string, string>>({});
  const save = async (id: string) => {
    try {
      await onSave(id, draft[id] ?? "");
      setDraft((d) => ({ ...d, [id]: "" }));
      setMsg((m) => ({ ...m, [id]: "" }));
    } catch (e) { setMsg((m) => ({ ...m, [id]: errorText(e) })); }
  };
  const remove = async (id: string) => {
    try { await onRemove(id); setMsg((m) => ({ ...m, [id]: "" })); } catch (e) { setMsg((m) => ({ ...m, [id]: errorText(e) })); }
  };
  const byId = new Map(providers.map((p) => [p.id, p]));
  return (
    <>
      {groups.map((g, gi) => (
        <section key={g.title} className="key-group" aria-labelledby={`kg-${gi}`}>
          <h3 id={`kg-${gi}`}>{g.title}</h3>
          <p className="dim key-hint">{g.hint}</p>
          {g.ids.map((id) => byId.get(id)).filter((p): p is KeyProvider => !!p).map((p) => (
            <div className="field key-field" key={p.id}>
              <div className="key-head">
                <label htmlFor={`k-${p.id}`}>{p.name} <span className="opt">{p.purpose}</span></label>
                <span className="key-state">
                  {status[p.id] ? <>
                    <span className="status-ok"><Check size={14} /> Connected</span>
                    <button type="button" className="link key-remove" onClick={() => remove(p.id)} aria-label={`Remove the ${p.name} key`}>Remove</button>
                  </> : <span className="status-missing">Not connected</span>}
                </span>
              </div>
              <div className="key-row">
                <input id={`k-${p.id}`} type="password" autoComplete="off" spellCheck={false} className="text-input"
                       placeholder={status[p.id] ? "Replace key…" : "Paste your API key"}
                       value={draft[p.id] ?? ""} onChange={(e) => setDraft((d) => ({ ...d, [p.id]: e.target.value }))}
                       onKeyDown={(e) => e.key === "Enter" && save(p.id)} />
                <button type="button" className="btn sel" onClick={() => save(p.id)} disabled={!(draft[p.id] ?? "").trim()}>Save</button>
              </div>
              {msg[p.id] && <div className="error-text" role="alert">{msg[p.id]}</div>}
            </div>
          ))}
        </section>
      ))}
    </>
  );
}
