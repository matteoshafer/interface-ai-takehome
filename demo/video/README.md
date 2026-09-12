# Demo video (Remotion)

A ~88-second programmatic walkthrough of the system: the problem, the discovery
loop, the capability artifact, deterministic replay and its three result shapes,
cross-tenant reuse (the west-tenant overlay), and the escalation/handoff.

```bash
cd demo/video
npm install
npm run build          # renders to out/demo.mp4
npm run preview        # opens the Remotion studio to scrub/edit
```

The rendered video is committed at `../../evidence/demo.mp4`.

Screenshots in `public/` are pulled straight from `evidence/` (the discovery
run, the injected-failure replay, the operator console at the moment of
escalation) or captured directly from the mock app (the west-tenant home
screen for the cross-tenant scene). Scene copy and timings live in
`src/scenes.tsx` / `src/theme.ts`.
