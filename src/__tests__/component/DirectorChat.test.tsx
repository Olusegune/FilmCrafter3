// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
const invoke = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({ invoke: (cmd: string, args: unknown) => invoke(cmd, args) }));
import { DirectorChat } from "../../DirectorChat";

afterEach(() => { cleanup(); invoke.mockReset(); });

describe("Ask the director", () => {
  it("sends through the selected AI brain and keeps paid work behind review", async () => {
    invoke.mockImplementation((cmd: string, args: { action?: string }) => {
      if (cmd === "ai_brain") return Promise.resolve({ provider: "gemini", base_url: "", model: "gemini-2.5-flash", vision_model: "" });
      if (args.action === "proposals") return Promise.resolve([]);
      if (args.action === "turn") return Promise.resolve({ reply: "I prepared a request.", model: "gemini-2.5-flash", steps: [], proposals: [{ id: "p1", tool: "request_render", args: { kind: "video", shots: ["S01"] }, risk: "spend", state: "pending", created: 1 }] });
      if (args.action === "apply") return Promise.resolve({ requires_spend_confirmation: true });
      return Promise.resolve({});
    });
    render(<DirectorChat dir="p" onClose={() => {}} onChanged={() => {}} />);
    fireEvent.change(screen.getByLabelText("Message the director"), { target: { value: "Render S01" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("I prepared a request.")).toBeInTheDocument();
    expect(screen.getByText(/Paid request · never starts from chat/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Review cost" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Paid work was not started");
    await waitFor(() => expect(invoke).toHaveBeenCalledWith("director_chat", { dir: "p", action: "apply", data: { id: "p1" } }));
  });
});
