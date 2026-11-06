// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { readFileSync } from "node:fs";

import { DEFAULT_PRODUCTION, modeSentence, ProductionModePicker } from "../../ProductionMode";
import type { ProductionMode } from "../../api";

afterEach(cleanup);

describe("the shot's production mode", () => {
  it("is a full scene by default and shows no plate controls", () => {
    render(<ProductionModePicker onChange={() => {}} />);
    expect(screen.getByLabelText("Production mode")).toHaveValue("full");
    expect(screen.getByRole("status")).toHaveTextContent("with the people and the place together");
    expect(screen.queryByLabelText("Screen colour")).toBeNull();
  });

  it("offers the layered scene only as a greyed option so it is not mistaken for something that works", () => {
    render(<ProductionModePicker onChange={() => {}} />);
    const opt = screen.getByRole("option", { name: "Layered scene (not built yet)" });
    expect(opt).toBeDisabled();
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual(["Full scene", "Green screen", "Transparent", "Layered scene (not built yet)"]);
  });

  it("chooses a mode and sends the whole setting, keeping what was already chosen", () => {
    const onChange = vi.fn();
    render(<ProductionModePicker value={{ ...DEFAULT_PRODUCTION, light: "left" }} onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("Production mode"), { target: { value: "green_screen" } });
    expect(onChange).toHaveBeenCalledWith({ mode: "green_screen", screen: "green", framing: "full", light: "left", angle: "eye", movement: "still" });
  });

  it("shows the plate controls for a green screen shot and sends each change", () => {
    const onChange = vi.fn();
    const v: ProductionMode = { ...DEFAULT_PRODUCTION, mode: "green_screen" };
    render(<ProductionModePicker value={v} onChange={onChange} />);
    expect(screen.getByRole("status")).toHaveTextContent("Green screen: green screen, full body, soft, from the front. The place is not drawn.");
    fireEvent.change(screen.getByLabelText("Screen colour"), { target: { value: "blue" } });
    fireEvent.change(screen.getByLabelText("Framing of the subject"), { target: { value: "half" } });
    fireEvent.change(screen.getByLabelText("What the subject does"), { target: { value: "turn" } });
    expect(onChange.mock.calls.map(([x]) => x)).toEqual([{ ...v, screen: "blue" }, { ...v, framing: "half" }, { ...v, movement: "turn" }]);
    expect(screen.getByText(/check the screen before keying/i)).toBeInTheDocument();
  });

  it("explains that transparent is made from a screen because the models here do not make transparency", () => {
    render(<ProductionModePicker value={{ ...DEFAULT_PRODUCTION, mode: "transparent" }} onChange={() => {}} />);
    expect(screen.getByRole("status")).toHaveTextContent("Transparent:");
    expect(modeSentence({ ...DEFAULT_PRODUCTION, mode: "transparent", screen: "blue", framing: "close" })).toContain("blue screen, head and shoulders");
  });

  it("cannot be changed while the storyboard is locked", () => {
    render(<ProductionModePicker value={{ ...DEFAULT_PRODUCTION, mode: "green_screen" }} onChange={() => {}} locked />);
    expect(screen.getByLabelText("Production mode")).toBeDisabled();
    expect(screen.getByLabelText("Screen colour")).toBeDisabled();
  });

  it("is on the Camera tab of the shot editor and the shot carries the setting", () => {
    const lab = readFileSync("src/ShotLab.tsx", "utf8");
    expect(lab).toContain("<ProductionModePicker");
    expect(lab).toContain("save({ production: p })");
    expect(readFileSync("src/api.ts", "utf8")).toContain("production?: ProductionMode");
  });
});
