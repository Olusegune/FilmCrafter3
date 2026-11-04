# FilmCrafter 0.35.0 handover

Agent Studio now creates a complete, approved production manifest from a script: character design, wardrobe, voice direction, sets, locations, lighting, continuity props, scene breakdown, score prompt, sound direction, SFX/ambience plan, and motion-graphics moments. Users choose image/keyframe, video, voice, music and SFX providers independently or leave each on Automatic.

Accepted image/video selections pin FilmCrafter's existing project router. The creative package and all department choices persist in `agent-production.json`; the original story is never rewritten. The workflow includes story, design, direction, storyboard, preview, remaining scenes, voices/score/sound, motion graphics, edit preview, continuity/quality review and export.

Paid generation is intentionally not pre-authorized by selecting Autopilot. FilmCrafter prepares each paid department batch and keeps the existing price, rights and one-use confirmation gates. Local ComfyUI work may run unattended. This is required to preserve the user's budget control.

Validation: TypeScript production build, 81 component tests, 15 Rust tests and 5 Agent Studio engine tests passed. Windows packages are unsigned unless an Authenticode certificate is configured.
