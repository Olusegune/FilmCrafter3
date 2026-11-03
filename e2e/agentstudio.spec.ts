import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const open = async (page: import("@playwright/test").Page, width = 1440) => {
  await page.setViewportSize({ width, height: 900 });
  await page.goto("/docshots.html?scene=agentstudio");
  await page.addStyleTag({ content: "*, *::before, *::after { animation: none !important; transition: none !important; }" });
  await page.evaluate(() => document.body.classList.remove("docshot"));
  await expect(page.getByRole("heading", { name: "Review before FilmCrafter continues" })).toBeVisible();
};

test("the guided workspace keeps approvals, budget and manual editing together", async ({ page }) => {
  await open(page);
  await expect(page.getByText("$3.33 spent")).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve & continue" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Manual Studio" })).toBeVisible();
  await expect(page.getByText("Story and shot plan approved.")).toBeVisible();
});

test("Agent Studio reflows at a compact desktop width and has no serious accessibility violations", async ({ page }) => {
  await open(page, 900);
  await expect(page.locator(".agent-plan")).toBeVisible();
  const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  expect(r.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`)).toEqual([]);
});
