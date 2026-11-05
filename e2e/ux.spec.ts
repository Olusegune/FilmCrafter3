import { expect, test, type Page } from "@playwright/test";

// The first-run experience, checked in a real browser on the screenshot harness (made-up data, nothing is sent anywhere): the Studio's header never covers a title, the rail shows the path and
// keeps the other tools behind one button, and Connections groups the keys by what they are for.
const open = async (page: Page, scene: string, w = 1440, h = 800) => {
  await page.setViewportSize({ width: w, height: h });
  await page.goto(`/docshots.html?scene=${scene}`);
  await page.addStyleTag({ content: "*, *::before, *::after { animation: none !important; transition: none !important; }" });
  await page.evaluate(() => { document.body.classList.remove("docshot"); try { localStorage.removeItem("pf-rail-more"); } catch { /* none */ } });
  await expect(page.locator(".rail")).toBeVisible();
};
const box = async (page: Page, sel: string) => { const b = await page.locator(sel).first().boundingBox(); if (!b) throw new Error(`${sel} has no box`); return b; };
const overlaps = (a: { x: number; width: number }, b: { x: number; width: number }) => a.x < b.x + b.width && b.x < a.x + a.width;

test.describe("the Studio's header", () => {
  for (const width of [1100, 1280, 1440, 1920]) {
    test(`no icon of the top bar covers the inspector's title at ${width} px wide`, async ({ page }) => {
      await open(page, "studio", width);
      await page.waitForTimeout(800);
      const title = await box(page, ".inspector-head .t");
      for (const btn of await page.locator(".topbar .icon-btn").all()) {
        const b = await btn.boundingBox();
        if (b) expect(overlaps(title, b), `${await btn.getAttribute("aria-label")} covers "${await page.locator(".inspector-head .t").innerText()}"`).toBe(false);
      }
    });
  }
  test("Ask the Director is in More when the bar is tight, and still one click away", async ({ page }) => {
    await open(page, "studio", 1280);
    await page.waitForTimeout(800);
    await expect(page.locator(".topbar .cmd-btn")).toHaveCount(0);
    await page.locator(".topbar").getByRole("button", { name: /^More/ }).click();
    await expect(page.getByRole("menuitem", { name: /Ask the Director/ })).toBeVisible();
  });
});

test.describe("the rail", () => {
  const names = (page: Page) => page.locator(".rail button").evaluateAll((bs) => bs.map((b) => (b.textContent ?? "").trim()));
  test("shows the path first (Studio, Review, Export) and keeps the other tools behind More", async ({ page }) => {
    await open(page, "studio");
    expect(await names(page)).toEqual(["Home", "Project", "Library", "Studio", "AI Agent", "Looks", "Review", "Export", "More", "Settings"]);
    const more = page.locator(".rail button.rail-more");
    await expect(more).toHaveAttribute("aria-expanded", "false");
    await more.click();
    await expect(more).toHaveAttribute("aria-expanded", "true");
    expect(await names(page)).toEqual(["Home", "Project", "Library", "Studio", "AI Agent", "Looks", "Review", "Export", "Fewer", "Supervisor", "Acting", "Continuity", "Layers", "Lighting", "Presets", "Color", "Colour match", "Clean up", "Settings"]);
    await page.locator(".rail button.rail-more").click();
    expect(await names(page)).toHaveLength(10);
  });
  test("remembers how it was left", async ({ page }) => {
    await open(page, "studio");
    await page.locator(".rail button.rail-more").click();
    await page.reload();
    await page.addStyleTag({ content: "*, *::before, *::after { animation: none !important; transition: none !important; }" });
    await expect(page.locator(".rail").getByRole("button", { name: "Supervisor" })).toBeVisible();
  });
  test("Director Mode shows every tool and no More button", async ({ page }) => {
    await open(page, "studio");
    await page.locator(".topbar").getByRole("button", { name: /^More/ }).click();
    await page.getByRole("menuitem", { name: /Director Mode/ }).click();
    await expect(page.locator(".rail").getByRole("button", { name: "Clean up" })).toBeVisible();
    await expect(page.locator(".rail button.rail-more")).toHaveCount(0);
  });
  test("every tool the rail hides can still be found with the command palette", async ({ page }) => {
    await open(page, "studio");
    await page.keyboard.press("Control+k");
    await expect(page.getByRole("dialog")).toBeVisible();
  });
});

test.describe("Connections", () => {
  test("groups the keys by what they are for, with BytePlus among the providers of pictures", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto("/docshots.html?scene=settings");
    await page.addStyleTag({ content: "*, *::before, *::after { animation: none !important; transition: none !important; }" });
    await page.evaluate(() => document.body.classList.remove("docshot"));
    const heads = await page.locator(".key-group > h3").allInnerTexts();
    expect(heads.map((h) => h.toLowerCase())).toEqual(["pictures and video", "writing helper and picture checks", "voices"]);
    const first = page.locator(".key-group").first();
    await expect(first.locator("label")).toHaveCount(4);
    await expect(first.locator("label", { hasText: "BytePlus" })).toBeVisible();
    await expect(first).toContainText("You need one of these to make anything");
  });
  test("a row keeps its shape whether a key is saved or not, and 'Not connected' never wraps", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto("/docshots.html?scene=settings");
    await page.addStyleTag({ content: "*, *::before, *::after { animation: none !important; transition: none !important; }" });
    await page.evaluate(() => document.body.classList.remove("docshot"));
    await page.waitForTimeout(600);
    const widths = await page.locator(".key-field .key-row .text-input").evaluateAll((els) => els.map((e) => Math.round(e.getBoundingClientRect().width)));
    expect(new Set(widths).size).toBe(1);
    const heights = await page.locator(".status-missing").evaluateAll((els) => els.map((e) => Math.round(e.getBoundingClientRect().height)));
    expect(Math.max(...heights)).toBeLessThan(24);                                                      // one line
    await expect(page.getByRole("button", { name: /^Remove the .* key$/ }).first()).toBeVisible();
  });
});
