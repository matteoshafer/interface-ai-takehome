# Demo video (Remotion)

A ~75-second programmatic walkthrough of the system: the problem, the discovery
loop, the capability artifact, deterministic replay and its three result shapes,
and the escalation/handoff.

```bash
cd demo/video
npm install
npm run build          # renders to out/demo.mp4
npm run preview        # opens the Remotion studio to scrub/edit
```

The rendered video is committed at `../../evidence/demo.mp4`.

Screenshots in `public/` are pulled straight from `evidence/` — the discovery
run, the injected-failure replay, and the operator console at the moment of
escalation. Scene copy and timings live in `src/scenes.tsx` / `src/theme.ts`.
