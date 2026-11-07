import { useCallback, useEffect, useState } from "react";
import { open as openDialog } from "@tauri-apps/plugin-dialog";
import { api, errorText, type ScCompare, type ScFinding, type ScReport } from "./api";

const SEV: Record<ScFinding["severity"], string> = { warning: "Likely problem", advice: "Worth a look", note: "For your information" };

/**
 * The continuity inspector for one set: what is where in every shot, and what a viewer might see go wrong from one shot to the next. Everything here is worked out from the set's own data (positions, events,
 * cameras), so the answers are the same every time. A finding that is meant can be marked deliberate, with a note; that is kept beside the set and changes nothing in it. The picture viewer is advisory only.
 */
export function SetContinuity({ dir, set }: { dir: string; set: string }) {
  const [r, setR] = useState<ScReport | null>(null);
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [shot, setShot] = useState("");
  const [cmp, setCmp] = useState<ScCompare | null>(null);
  const [showAll, setShowAll] = useState(false);
  const run = useCallback(async (label: string, f: () => Promise<void>) => { setErr(""); setBusy(label); try { await f(); } catch (e) { setErr(errorText(e)); } finally { setBusy(""); } }, []);
  const inspect = useCallback(() => run("inspect", async () => setR(await api.setContinuity("inspect", dir, { set }))), [run, dir, set]);
  useEffect(() => { setR(null); setCmp(null); void inspect(); }, [inspect]);
  const mark = (f: ScFinding, on: boolean) => run("mark", async () => setR(await api.setContinuity("override", dir, { set, key: f.key, note: notes[f.key] ?? f.note, on })));
  const withCam = (r?.timeline ?? []).filter((t) => t.camera);
  const compare = () => run("compare", async () => {
    const f = await openDialog({ multiple: false, filters: [{ name: "Pictures", extensions: ["png", "jpg", "jpeg", "webp"] }] });
    if (typeof f === "string") setCmp(await api.setContinuity<ScCompare>("compare", dir, { set, shot: shot || withCam[0]?.shot, picture: f }));
  });
  const live = (r?.findings ?? []).filter((f) => !f.overridden), kept = (r?.findings ?? []).filter((f) => f.overridden);
  return (
    <section aria-label="Continuity">
      <p className="dim">Checks what is where in every shot and what a viewer might see go wrong from one shot to the next. It is worked out from this set's own positions, events and cameras, so it says the same thing every time; it reads no pictures. Mark a finding deliberate if you meant it (that works on a locked set too: it changes nothing in the set).</p>
      <div className="sm-row"><button className="btn sm" disabled={!!busy} onClick={() => void inspect()}>{busy === "inspect" ? "Inspecting…" : "Inspect again"}</button>
        {r && <span role="status" aria-label="Continuity summary">{r.counts.warning} likely problem{r.counts.warning === 1 ? "" : "s"} · {r.counts.advice} worth a look · {r.counts.note} for information{r.counts.deliberate ? ` · ${r.counts.deliberate} marked deliberate` : ""}</span>}</div>
      {err && <p className="ss-warn" role="alert">{err}</p>}
      {r && r.shots_without_camera.length > 0 && <p className="dim">{r.shots_without_camera.length} of {r.timeline.length} shots have no camera chosen in this set, so what they show cannot be checked. Choose them in the Over the shots tab.</p>}
      {r && live.length === 0 && <p className="dim" role="status">Nothing to flag{r.shots_without_camera.length ? " among the shots that have a camera" : ""}.</p>}
      {live.length > 0 && <ul className="ss-cues" aria-label="Findings">{live.map((f) => <li key={f.key} aria-label={`Finding ${f.kind}`}>
        <div className="sm-row"><b className={f.severity === "warning" ? "ss-warn" : ""}>{SEV[f.severity]}</b><span>{f.text}</span></div>
        <div className="sm-row"><span className="dim">{f.shots.length ? `Shot${f.shots.length === 1 ? "" : "s"} ${f.shots.join(" → ")}` : "The whole set"}</span>
          <input className="text-input" aria-label={`Why it is deliberate (${f.kind})`} placeholder="Why it is meant (optional)" maxLength={300} value={notes[f.key] ?? ""} onChange={(e) => setNotes({ ...notes, [f.key]: e.target.value })} style={{ flex: 1, minWidth: 160 }} />
          <button className="btn sm ghost" disabled={!!busy} onClick={() => void mark(f, true)}>It is deliberate</button></div></li>)}</ul>}
      {kept.length > 0 && <details><summary>Marked deliberate ({kept.length})</summary><ul className="ss-cues" aria-label="Deliberate">{kept.map((f) => <li key={f.key} className="sm-row"><span>{f.text}</span><span className="dim">{f.note || "no note"}</span>
        <button className="link" disabled={!!busy} onClick={() => void mark(f, false)}>Check it again</button></li>)}</ul></details>}

      <h4>Shot by shot</h4>
      {r && <><table className="ss-table" aria-label="Shot by shot"><thead><tr><th>Shot</th><th>Camera</th><th>In view</th><th>Changes during the shot</th></tr></thead>
        <tbody>{r.timeline.slice(0, showAll ? undefined : 12).map((t) => <tr key={t.shot}><td>{t.shot}</td><td>{t.camera?.name ?? <span className="dim">none</span>}</td>
          <td>{t.camera ? t.things.filter((x) => x.in_frame).map((x) => x.name).join(", ") || <span className="dim">nothing</span> : <span className="dim">not checked</span>}</td><td>{t.events.join("; ") || <span className="dim">none</span>}</td></tr>)}</tbody></table>
        {r.timeline.length > 12 && <button className="link" onClick={() => setShowAll((v) => !v)}>{showAll ? "Show fewer shots" : `Show all ${r.timeline.length} shots`}</button>}</>}

      <h4>Compare a picture with the set <span className="dim">advice, not proof</span></h4>
      <p className="dim">Put a generated picture of a shot beside the set's own view of it. Look at the layout: where things stand and which way they face. Colour and detail will differ.</p>
      <div className="sm-row"><select className="text-input" aria-label="Shot to compare" value={shot} onChange={(e) => setShot(e.target.value)}><option value="">{withCam.length ? "Choose a shot…" : "No shot has a camera yet"}</option>{withCam.map((t) => <option key={t.shot} value={t.shot}>{t.shot} ({t.camera!.name})</option>)}</select>
        <button className="btn sm" disabled={!!busy || withCam.length === 0} onClick={() => void compare()}>{busy === "compare" ? "Comparing…" : "Choose a picture to compare…"}</button></div>
      {cmp && <figure aria-label="Picture comparison" style={{ margin: 0 }}><img alt="The set's view, the picture, and where they differ" src={`${api.mediaUrl(`${dir}/${cmp.file}`)}?v=${cmp.file}`} style={{ maxWidth: "100%", borderRadius: 6 }} />
        <figcaption><span className="dim">Left: the set. Middle: your picture. Right: where they differ (red is more).</span><br />{cmp.words}<br /><span className="dim">{cmp.note}</span></figcaption></figure>}
    </section>
  );
}
