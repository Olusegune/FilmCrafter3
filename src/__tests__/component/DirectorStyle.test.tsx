// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
const invoke = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({ invoke: (cmd: string, args: unknown) => invoke(cmd, args), convertFileSrc: (p: string) => p }));
import { DirectorStyleSheet } from "../../DirectorStyle";
const styles = [{ id: "coogler", name: "Ryan Coogler", region: "North America", origin: "USA", known_for: "Warm community", palette: [], traits: { camera: "Moving takes", light: "Warm skin" } }, { id: "adetiba", name: "Kemi Adetiba", region: "Africa", origin: "Nigeria", known_for: "Commanding portraits", palette: [], traits: { camera: "Heroic angles", light: "Jewel tones" } }];
afterEach(() => { cleanup(); invoke.mockReset(); });
describe("Director style", () => {
  it("is optional, searchable and applies only through the director-style command", async () => {
    invoke.mockResolvedValue({ current: null, styles }); render(<DirectorStyleSheet dir="p" onClose={() => {}} />);
    expect(await screen.findByText("Ryan Coogler")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Region"), { target: { value: "Africa" } });
    expect(screen.queryByText("Ryan Coogler")).not.toBeInTheDocument(); fireEvent.click(screen.getByText("Kemi Adetiba")); fireEvent.click(screen.getByRole("button", { name: "Use this director style" }));
    await waitFor(() => expect(invoke).toHaveBeenCalledWith("director_style", { dir: "p", action: "set", data: { id: "adetiba" } }));
  });
  it("can be cleared without touching any project setting API", async () => {
    invoke.mockResolvedValue({ current: "coogler", styles }); render(<DirectorStyleSheet dir="p" onClose={() => {}} />);
    fireEvent.click(await screen.findByRole("button", { name: "Clear style" }));
    await waitFor(() => expect(invoke).toHaveBeenCalledWith("director_style", { dir: "p", action: "clear", data: {} }));
    expect(invoke.mock.calls.some(([cmd]) => cmd === "set_project_settings" || cmd === "set_look")).toBe(false);
  });
});
