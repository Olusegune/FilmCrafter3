// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { FilmRail } from "../../FilmRail";

afterEach(cleanup);
const items = (go = vi.fn()) => [
  { id: "story", label: "Story", icon: <i />, done: true, onClick: () => go("story") },
  { id: "cast", label: "Cast", icon: <i />, next: true, onClick: () => go("cast") },
  { id: "make", label: "Studio", icon: <i />, active: true, onClick: () => go("make") },
  { id: "export", label: "Export", icon: <i />, disabled: true },
];

describe("the left rail on every film screen", () => {
  it("has Home on top, the steps in order, marks done, next and where you are, and Settings below", () => {
    render(<FilmRail items={items()} onHome={() => {}} onSettings={() => {}} />);
    const names = screen.getAllByRole("button").map((b) => b.textContent);
    expect(names).toEqual(["Home", "Story", "Cast", "Studio", "Export", "Settings"]);
    expect(screen.getByRole("button", { name: /Studio/ })).toHaveAttribute("aria-current", "page");
    expect(screen.getByLabelText("done")).toBeInTheDocument();
    expect(screen.getByLabelText("next step")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Export/ })).toBeDisabled();
  });
  it("goes where each button says", () => {
    const go = vi.fn(), home = vi.fn(), settings = vi.fn();
    render(<FilmRail items={items(go)} onHome={home} onSettings={settings} />);
    fireEvent.click(screen.getByRole("button", { name: /Cast/ }));
    fireEvent.click(screen.getByRole("button", { name: /Home/ }));
    fireEvent.click(screen.getByRole("button", { name: /Settings/ }));
    expect(go).toHaveBeenCalledWith("cast");
    expect(home).toHaveBeenCalledOnce();
    expect(settings).toHaveBeenCalledOnce();
  });
  it("leaves Settings out when there is nothing to open", () => {
    render(<FilmRail items={items()} onHome={() => {}} />);
    expect(screen.queryByRole("button", { name: /Settings/ })).toBeNull();
  });
});
