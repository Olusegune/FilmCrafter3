# FilmCrafter 0.46.0 handover

Read `HANDOVER-0.37.0.md`, then `HANDOVER-0.38.0.md` to `HANDOVER-0.45.0.md`. The code is `Olusegune/FilmCrafter3`.

## Implemented: one left rail on every film screen

- `src/FilmRail.tsx`: the rail (`FilmRail`), the tool list (`TOOLS`) and `railSteps` (the golden-path steps with ticks and the next dot). Used by `FilmView.tsx` (all steps) and `Studio.tsx`; `AgentStudio.tsx` is handed the Studio's rail as `rail`. The old per-screen rails and `RailBtn` are gone.
- A tool pressed on a film screen goes to the timeline Studio with that tool open (`StudioSheet` now also holds every `ToolId`; `Studio.tsx` `openTool` handles each). In the Studio it opens in place.
- Owner's rule: the menu is on every screen of a film, not on Home. A tool that cannot act is greyed with the reason, never hidden.
- Also: `.ls`, `.ff`, `.spend`, `.bm`, `.ac`, `.pc`, `.sp-plan`, `.rd` dialogs keep their sections at full height (`flex-shrink: 0`) so a short window scrolls instead of cutting text; Line Studio's header is sticky.

## Not done / next

- Never looked at on screen: open the installed app and check the rail on Story, Cast, Studio, Agent Studio and the Timeline, at a small window size, and the Line Studio dialog. Fix what looks wrong.
- The Home screen's own layout is unchanged. Narrow windows (under 700 px) hide the rail.
- The Virtual Production / WorldLock / DirectorCam brief has not been started.
