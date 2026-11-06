// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

const invoke = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({ invoke: (cmd: string, args: unknown) => invoke(cmd, args), convertFileSrc: (p: string) => p }));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn() }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: vi.fn() }));

import { LayersPanel } from "../../Layers";

let layers: object[] = [];
const backend = (_cmd: string, a: { action?: string; data?: Record<string, unknown> }) => {
  if (a?.action === "list") return Promise.resolve(layers);
  if (a?.action === "history") return Promise.resolve({ can_undo: false, can_redo: false });
  if (a?.action === "add") { layers = [{ id: "ov_1", kind: "text", text: "Your text", enabled: true, placed: true, start: 12, end: 16, source: "manual", x: 0.5, y: 0.5, size: 0.08, width: 0.5, color: "#fff", fade: 0.4, reason: "", explicit: true, explicit_end: true }]; return Promise.resolve(layers); }
  if (a?.action === "styles") return Promise.resolve({ styles: [] });
  if (a?.action === "templates") return Promise.resolve({ templates: [] });
  return Promise.resolve([]);
};
afterEach(() => { cleanup(); invoke.mockReset(); layers = []; });
const show = (time = 12.4) => render(<LayersPanel dir="proj" selected={null} onSelect={() => {}} onClose={() => {}} time={time} docked />);

describe("the Layers panel when nothing has been added", () => {
  it("leads with what can be added, in plain words, and says where the playhead is", async () => {
    invoke.mockImplementation(backend);
    show(12.4);
    const group = await screen.findByRole("group", { name: "What to add" });
    expect(within(group).getAllByRole("button").map((b) => b.querySelector("b")?.textContent)).toEqual(["Title or text", "Picture", "Video clip", "Shape or icon"]);
    expect(screen.getByLabelText("Playhead time")).toHaveTextContent("0:12.4");
    expect(screen.getByText(/A new one starts at the/)).toBeInTheDocument();
    expect(screen.getByText(/Move the playhead to where it should appear, then choose what to add/)).toBeInTheDocument();
    expect(screen.queryByText("Put something over your film")).toBeNull();                                  // the numbered wall of text is gone
    expect(screen.queryByRole("button", { name: "+ Text" })).toBeNull();                                    // and the small buttons are not shown twice
  });

  it("adds a title from the first choice and then switches to the compact buttons", async () => {
    invoke.mockImplementation(backend);
    show();
    fireEvent.click(await screen.findByRole("button", { name: /Title or text/ }));
    await waitFor(() => expect(screen.queryByRole("group", { name: "What to add" })).toBeNull());
    expect(screen.getByRole("button", { name: "+ Text" })).toBeInTheDocument();
    expect(screen.getByText("How layers work")).toBeInTheDocument();
  });
});
