// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn(() => Promise.resolve(null)), convertFileSrc: (p: string) => p }));

import { KEY_GROUPS, KeyGroups, type KeyProvider } from "../../KeyRows";
import type { KeyStatus } from "../../api";

const providers: KeyProvider[] = [
  { id: "kie", name: "Kie.ai", purpose: "Video, images and upscaling" }, { id: "fal", name: "fal.ai", purpose: "Video, images" }, { id: "google", name: "Google Gemini", purpose: "Veo, Nano Banana" },
  { id: "byteplus", name: "BytePlus (Seedream)", purpose: "Seedream direct" }, { id: "openai", name: "OpenAI", purpose: "OpenAI's own models" }, { id: "openrouter", name: "OpenRouter", purpose: "Hundreds of models" },
  { id: "anthropic", name: "Anthropic Claude", purpose: "Claude models" },
  { id: "elevenlabs", name: "ElevenLabs", purpose: "Voices" },
];
const status: KeyStatus = { openai: false, anthropic: false, fal: true, kie: false, google: false, elevenlabs: false, openrouter: false, byteplus: false };
afterEach(cleanup);

const view = (over: Partial<Parameters<typeof KeyGroups>[0]> = {}) => {
  const onSave = vi.fn().mockResolvedValue(undefined);
  const onRemove = vi.fn().mockResolvedValue(undefined);
  render(<KeyGroups providers={providers} status={status} onSave={onSave} onRemove={onRemove} {...over} />);
  return { onSave, onRemove };
};

describe("the keys, grouped by what they are for", () => {
  it("lists the providers of pictures and video first (BytePlus among them), then the optional helpers, then voices", () => {
    view();
    const groups = screen.getAllByRole("region").map((g) => within(g).getByRole("heading", { level: 3 }).textContent);
    expect(groups).toEqual(["Pictures and video", "Writing helper and picture checks", "Voices"]);
    const first = screen.getByRole("region", { name: "Pictures and video" });
    expect(first.querySelectorAll("input[type=password]")).toHaveLength(4);
    expect([...first.querySelectorAll("label")].map((l) => l.textContent?.split(" ")[0])).toEqual(["Kie.ai", "fal.ai", "Google", "BytePlus"]);
    expect(within(first).getByText(/You need one of these to make anything/)).toBeInTheDocument();
  });
  it("shows every key once, and a key that has no group is not lost from the groups table", () => {
    view();
    expect(document.querySelectorAll("input[type=password]")).toHaveLength(8);
    expect(KEY_GROUPS.flatMap((g) => g.ids).sort()).toEqual(providers.map((p) => p.id).sort());
  });
  it("says Connected with a Remove link for a saved key only, and Not connected for the rest", () => {
    view();
    expect(screen.getAllByText("Connected")).toHaveLength(1);
    expect(screen.getAllByText("Not connected")).toHaveLength(7);
    expect(screen.getAllByRole("button", { name: /^Remove the / })).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Remove the fal.ai key" })).toBeInTheDocument();
  });
  it("keeps Save off until something is typed, and saves the trimmed key for that provider only", async () => {
    const { onSave } = view();
    const box = document.getElementById("k-byteplus") as HTMLInputElement;
    const save = box.parentElement!.querySelector("button")!;
    expect(save).toBeDisabled();
    fireEvent.change(box, { target: { value: "  ark-123  " } });
    expect(save).toBeEnabled();
    fireEvent.click(save);
    await waitFor(() => expect(onSave).toHaveBeenCalledWith("byteplus", "  ark-123  "));       // the shell trims it; nothing is changed here
    expect(onSave).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(box).toHaveValue(""));                                           // the pasted key is not left on the screen
  });
  it("saves with Enter too", async () => {
    const { onSave } = view();
    const box = document.getElementById("k-kie") as HTMLInputElement;
    fireEvent.change(box, { target: { value: "k" } });
    fireEvent.keyDown(box, { key: "Enter" });
    await waitFor(() => expect(onSave).toHaveBeenCalledWith("kie", "k"));
  });
  it("removes only the key asked for", async () => {
    const { onRemove } = view();
    fireEvent.click(screen.getByRole("button", { name: "Remove the fal.ai key" }));
    await waitFor(() => expect(onRemove).toHaveBeenCalledWith("fal"));
    expect(onRemove).toHaveBeenCalledTimes(1);
  });
  it("says why a key was refused, next to that key, and keeps what was typed", async () => {
    const { onSave } = view({ onSave: vi.fn().mockRejectedValue("Key is empty") });
    void onSave;
    const box = document.getElementById("k-google") as HTMLInputElement;
    fireEvent.change(box, { target: { value: "x" } });
    fireEvent.click(box.parentElement!.querySelector("button")!);
    expect(await screen.findByRole("alert")).toHaveTextContent("Key is empty");
    expect(box).toHaveValue("x");
  });
  it("never shows a pasted key in clear text", () => {
    view();
    document.querySelectorAll("input").forEach((i) => expect(i).toHaveAttribute("type", "password"));
  });
});
