import type { ProductionMode } from "./api";

export const DEFAULT_PRODUCTION: ProductionMode = { mode: "full", screen: "green", framing: "full", light: "front", angle: "eye", movement: "still" };

export const MODE_WORDS: Record<ProductionMode["mode"], { label: string; blurb: string }> = {
  full: { label: "Full scene", blurb: "The picture is made with the people and the place together, as always." },
  green_screen: { label: "Green screen", blurb: "The subject is asked for against a flat, evenly lit screen, and the place is left out. Check the plate, key it in the Cutout studio, and put it on a background." },
  transparent: { label: "Transparent", blurb: "The picture models here do not make transparency themselves, so this asks for a flat screen too and the Cutout studio turns it into a transparent cutout." },
};

const FRAMING: [string, string][] = [["full", "Full body"], ["half", "Waist up"], ["close", "Head and shoulders"], ["prop", "An object alone"]];
const LIGHT: [string, string][] = [["front", "Soft, from the front"], ["left", "From the left"], ["right", "From the right"], ["back", "Rim light from behind"], ["top", "Soft, from above"]];
const ANGLE: [string, string][] = [["eye", "Eye level"], ["low", "Low angle"], ["high", "High angle"]];
const MOVE: [string, string][] = [["still", "Stands still"], ["walk", "Walks on the spot"], ["turn", "Turns slowly"], ["gesture", "Gestures"]];

/** One line saying what the shot's mode means for the picture that will be asked for. */
export const modeSentence = (p: ProductionMode): string => (p.mode === "full" ? MODE_WORDS.full.blurb : `${MODE_WORDS[p.mode].label}: ${p.screen} screen, ${(FRAMING.find(([k]) => k === p.framing) ?? FRAMING[0])[1].toLowerCase()}, ${(LIGHT.find(([k]) => k === p.light) ?? LIGHT[0])[1].toLowerCase()}. The place is not drawn.`);

/**
 * How this shot's picture is made. A full scene is as before. A green screen or transparent shot is asked for as a plate: the subject on a flat, evenly lit screen, with the lighting, framing and movement chosen here,
 * to be keyed in the Cutout studio. A layered scene (separating a shot into background, characters and effects) is not built yet and is shown greyed so it is not mistaken for something that works.
 */
export function ProductionModePicker({ value, onChange, locked }: { value?: ProductionMode; onChange: (p: ProductionMode) => void; locked?: boolean }) {
  const p = { ...DEFAULT_PRODUCTION, ...(value ?? {}) };
  const set = (patch: Partial<ProductionMode>) => onChange({ ...p, ...patch });
  const sel = (label: string, key: "framing" | "light" | "angle" | "movement", list: [string, string][]) => (
    <label className="field"><span>{label}</span><select className="text-input" aria-label={label} value={p[key]} disabled={locked} onChange={(e) => set({ [key]: e.target.value })}>{list.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>);
  return (
    <section className="sl-production" aria-label="How this shot is made">
      <label className="field"><span>How this shot is made <span className="dim">production mode</span></span>
        <select className="text-input" aria-label="Production mode" value={p.mode} disabled={locked} onChange={(e) => set({ mode: e.target.value as ProductionMode["mode"] })}>
          {(Object.keys(MODE_WORDS) as ProductionMode["mode"][]).map((k) => <option key={k} value={k}>{MODE_WORDS[k].label}</option>)}
          <option value="layered" disabled>Layered scene (not built yet)</option></select></label>
      <p className="dim" role="status">{modeSentence(p)}</p>
      {p.mode !== "full" && <>
        <div className="cw-grid2">
          <label className="field"><span>Screen colour</span><select className="text-input" aria-label="Screen colour" value={p.screen} disabled={locked} onChange={(e) => set({ screen: e.target.value as "green" | "blue" })}><option value="green">Green</option><option value="blue">Blue</option></select></label>
          {sel("Framing of the subject", "framing", FRAMING)}{sel("Light on the subject", "light", LIGHT)}{sel("Camera angle", "angle", ANGLE)}{sel("What the subject does", "movement", MOVE)}</div>
        <p className="dim sm-note">A generated screen is rarely perfectly even. When the picture is made, bring it into the Cutout studio (rail, More, Cutouts) and check the screen before keying.</p></>}
    </section>
  );
}
