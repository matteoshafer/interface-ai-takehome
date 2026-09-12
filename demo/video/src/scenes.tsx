import React from 'react';
import {
  AbsoluteFill,
  Sequence,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
  spring,
} from 'remotion';
import {c, font, mono, sec} from './theme';
import {Body, Browser, FadeIn, H1, Kicker, Panel, progress} from './components';

const Center: React.FC<{children: React.ReactNode; gap?: number}> = ({
  children,
  gap = 26,
}) => (
  <AbsoluteFill
    style={{
      background: c.bg,
      justifyContent: 'center',
      alignItems: 'center',
      padding: 120,
    }}
  >
    <div style={{display: 'flex', flexDirection: 'column', gap, maxWidth: 1500}}>
      {children}
    </div>
  </AbsoluteFill>
);

/* ---------------------------------------------------------------- Title */
export const TitleScene: React.FC = () => (
  <Center gap={30}>
    <FadeIn delay={4}>
      <Kicker>interface.ai — build assignment</Kicker>
    </FadeIn>
    <FadeIn delay={12}>
      <H1>Computer-Use Automation System</H1>
    </FadeIn>
    <FadeIn delay={22}>
      <Body size={38}>
        An LLM works out a task inside a legacy UI once. The run becomes a typed,
        replayable capability. After that, no model is in the loop.
      </Body>
    </FadeIn>
    <FadeIn delay={34}>
      <div style={{display: 'flex', gap: 14, fontFamily: mono, fontSize: 22, color: c.dim}}>
        {['discover', 'artifact', 'replay', 'escalate', 'guardrails'].map((t, i) => (
          <React.Fragment key={t}>
            {i > 0 && <span style={{color: c.border}}>→</span>}
            <span>{t}</span>
          </React.Fragment>
        ))}
      </div>
    </FadeIn>
  </Center>
);

/* -------------------------------------------------------------- Problem */
export const ProblemScene: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <Center>
      <FadeIn delay={2}>
        <Kicker>the problem</Kicker>
      </FadeIn>
      <FadeIn delay={10}>
        <H1 size={58}>
          The back-office apps banks run have no API.
        </H1>
      </FadeIn>
      <FadeIn delay={22}>
        <Body>
          Core banking screens, servicing tools, admin consoles — server-rendered,
          table layouts, no stable selectors, no test IDs. The only way in is to
          drive the UI the way a human operator would.
        </Body>
      </FadeIn>
      <div style={{display: 'flex', gap: 20, marginTop: 20}}>
        {[
          ['Perceive', 'accessibility tree: role + accessible name', 40],
          ['Act', 'click / type / read, resolved by ordered locator strategies', 58],
          ['Record', 'every step, decoupled from the model transcript', 76],
        ].map(([h, d, delay]) => (
          <FadeIn key={h as string} delay={delay as number} style={{flex: 1}}>
            <Panel title={h as string} accent={c.accent} style={{height: '100%'}}>
              <span style={{fontSize: 22, color: c.dim}}>{d}</span>
            </Panel>
          </FadeIn>
        ))}
      </div>
      <div style={{opacity: interpolate(frame, [95, 110], [0, 1], {extrapolateRight: 'clamp'})}}>
        <Body size={26}>
          Proxy target for this build: a mock credit-union admin app with
          injectable runtime faults.
        </Body>
      </div>
    </Center>
  );
};

/* ------------------------------------------------------------ Discovery */
const STEPS = [
  {shot: 'disc-1-login.png', url: 'localhost:5050/login', call: 'type_text  "Username" ← operator', t: 0},
  {shot: 'disc-2-search.png', url: 'localhost:5050/', call: 'type_text  "Member ID or name" ← {{ member_id }}', t: 1},
  {shot: 'disc-3-results.png', url: 'localhost:5050/members?q=100042', call: 'click  link "Open"', t: 2},
  {shot: 'disc-4-member.png', url: 'localhost:5050/member/100042', call: 'read_value  savings_balance ← "$4,215.67"', t: 3},
];

export const DiscoveryScene: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const per = sec(4);
  const idx = Math.min(STEPS.length - 1, Math.floor(frame / per));
  const step = STEPS[idx];
  const local = frame - idx * per;
  const enter = spring({frame: local, fps, config: {damping: 200}});

  return (
    <AbsoluteFill style={{background: c.bg, padding: 90}}>
      <FadeIn delay={2}>
        <Kicker>1 · discovery — the model in the loop</Kicker>
      </FadeIn>
      <div style={{display: 'flex', gap: 60, marginTop: 40, alignItems: 'center'}}>
        <div
          style={{
            transform: `translateY(${interpolate(enter, [0, 1], [30, 0])}px)`,
            opacity: enter,
          }}
        >
          <Browser src={step.shot} url={step.url} width={1080} />
        </div>
        <div style={{display: 'flex', flexDirection: 'column', gap: 18, flex: 1}}>
          <Body size={24}>observe → decide → act, {STEPS.length} of 9 steps shown</Body>
          {STEPS.map((s, i) => (
            <div
              key={s.shot}
              style={{
                fontFamily: mono,
                fontSize: 23,
                padding: '14px 18px',
                borderRadius: 8,
                border: `1px solid ${i === idx ? c.accent : c.border}`,
                background: i === idx ? 'rgba(77,163,255,0.10)' : 'transparent',
                color: i <= idx ? c.code : c.dim,
                opacity: i <= idx ? 1 : 0.4,
              }}
            >
              <span style={{color: c.dim}}>step {i + 1}  </span>
              {s.call}
            </div>
          ))}
          <div style={{marginTop: 14, opacity: interpolate(frame, [per * 3.4, per * 3.8], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'})}}>
            <Panel accent={c.good} title="finish">
              <span style={{fontSize: 22}}>
                outputs = &#123; savings_balance: 4215.67 &#125;
              </span>
            </Panel>
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};

/* ------------------------------------------------------------- Artifact */
export const ArtifactScene: React.FC = () => {
  const frame = useCurrentFrame();
  const rows = [
    ['parameters', 'member_id  string  /^\\d{4,9}$/  pii', 'username / password  secret', 10],
    ['outputs', 'savings_balance  number', 'typed, with a declared read strategy', 26],
    ['steps[].target', 'cell_at → role_name → anchor → text → bbox_ratio', 'ordered, strongest first; replay logs which matched', 42],
    ['checkpoint', 'url ~ /member/\\d+  AND  heading ~ "Member \\d+"', 'asserted after the last step', 58],
    ['known_outcomes', 'member_not_found → { found: false }', 'permission_denied → { permitted: false }', 74],
    ['recovery', 'session_timeout → reauth · dialog → dismiss · slow → retry', 'bounded, declared, not guessed', 90],
  ];
  return (
    <AbsoluteFill style={{background: c.bg, padding: 90}}>
      <FadeIn delay={2}>
        <Kicker>2 · the capability artifact</Kicker>
      </FadeIn>
      <FadeIn delay={8}>
        <H1 size={44}>A contract an agent can call — typed, versioned, reviewable.</H1>
      </FadeIn>
      <div style={{display: 'flex', flexDirection: 'column', gap: 12, marginTop: 34}}>
        {rows.map(([k, a, b, delay]) => (
          <div
            key={k as string}
            style={{
              display: 'flex',
              gap: 24,
              alignItems: 'baseline',
              opacity: interpolate(frame, [delay as number, (delay as number) + 12], [0, 1], {
                extrapolateLeft: 'clamp',
                extrapolateRight: 'clamp',
              }),
              transform: `translateX(${interpolate(
                frame,
                [delay as number, (delay as number) + 12],
                [-20, 0],
                {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'},
              )}px)`,
            }}
          >
            <div style={{fontFamily: mono, fontSize: 24, color: c.accent, width: 340}}>
              {k}
            </div>
            <div style={{fontFamily: mono, fontSize: 23, color: c.code, flex: 1}}>
              {a}
              <div style={{color: c.dim, fontSize: 19, marginTop: 2}}>{b}</div>
            </div>
          </div>
        ))}
      </div>
      <FadeIn delay={108} style={{marginTop: 30}}>
        <Body size={24}>
          Redaction strips SSNs and account numbers from the artifact and every
          log. The model transcript is stored only as a hash.
        </Body>
      </FadeIn>
    </AbsoluteFill>
  );
};

/* --------------------------------------------------------------- Replay */
const RESULTS = [
  {
    label: 'member 100042',
    accent: c.good,
    tag: 'success',
    body: 'outputs = { savings_balance: 4215.67 }',
    delay: 12,
  },
  {
    label: 'member 999999',
    accent: c.accent,
    tag: 'business_outcome',
    body: 'member_not_found → { found: false }   — a legitimate answer, not a crash',
    delay: 40,
  },
  {
    label: 'member 100999',
    accent: c.accent,
    tag: 'business_outcome',
    body: 'permission_denied → { permitted: false }',
    delay: 66,
  },
  {
    label: '--inject dialog / timeout',
    accent: c.warn,
    tag: 'recovered → success',
    body: 'dismissed a maintenance interstitial · re-authenticated after a timeout',
    delay: 92,
  },
  {
    label: '--inject error',
    accent: c.bad,
    tag: 'failure: app_error',
    body: 'stopped at step s06 · screenshot + AX snapshot written to evidence/',
    delay: 118,
  },
];

export const ReplayScene: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{background: c.bg, padding: 90}}>
      <FadeIn delay={2}>
        <Kicker>3 · deterministic replay — no model</Kicker>
      </FadeIn>
      <FadeIn delay={8}>
        <H1 size={44}>Same inputs → same steps → one of three structured results.</H1>
      </FadeIn>
      <div style={{display: 'flex', flexDirection: 'column', gap: 14, marginTop: 34}}>
        {RESULTS.map((r) => (
          <div
            key={r.label}
            style={{
              display: 'flex',
              gap: 22,
              alignItems: 'center',
              opacity: interpolate(frame, [r.delay, r.delay + 12], [0, 1], {
                extrapolateLeft: 'clamp',
                extrapolateRight: 'clamp',
              }),
              transform: `translateY(${interpolate(
                frame,
                [r.delay, r.delay + 12],
                [16, 0],
                {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'},
              )}px)`,
            }}
          >
            <div
              style={{
                fontFamily: mono,
                fontSize: 22,
                color: c.dim,
                width: 360,
                textAlign: 'right',
              }}
            >
              {r.label}
            </div>
            <div style={{width: 3, alignSelf: 'stretch', background: r.accent}} />
            <div style={{flex: 1}}>
              <span
                style={{
                  fontFamily: mono,
                  fontSize: 23,
                  color: r.accent,
                  fontWeight: 700,
                }}
              >
                {r.tag}
              </span>
              <div style={{fontFamily: mono, fontSize: 20, color: c.code, marginTop: 3}}>
                {r.body}
              </div>
            </div>
          </div>
        ))}
      </div>
      <FadeIn delay={140} style={{marginTop: 34}}>
        <Body size={24}>
          Risky, irreversible steps (opening an account) are refused unless the
          capability is approved — and the account number comes back redacted.
        </Body>
      </FadeIn>
    </AbsoluteFill>
  );
};

/* --------------------------------------------------------- Cross-tenant */
export const TenantScene: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const rows = [
    {label: 'core tenant (control)', accent: c.good, rank: 'role_name — rank 0',
     detail: 'the field is "Member ID or name"', at: 40},
    {label: 'west tenant, NO overlay', accent: c.warn, rank: 'bbox_ratio — rank 3',
     detail: '"Account Holder # or name" — role_name misses, falls through to a screen coordinate', at: 70},
    {label: 'west tenant + overlay', accent: c.good, rank: 'role_name — rank 0',
     detail: 'a 4-line step_overrides entry — no re-recording', at: 100},
  ];
  return (
    <AbsoluteFill style={{background: c.bg, padding: 90}}>
      <FadeIn delay={2}>
        <Kicker>5 · cross-tenant reuse — no re-recording</Kicker>
      </FadeIn>
      <FadeIn delay={8}>
        <H1 size={42}>
          One capability, recorded once, reused across institutions.
        </H1>
      </FadeIn>
      <div style={{display: 'flex', gap: 60, marginTop: 36, alignItems: 'flex-start'}}>
        <div
          style={{
            opacity: interpolate(frame, [16, 34], [0, 1], {extrapolateRight: 'clamp'}),
          }}
        >
          <Browser src="tenant-west-home.png"
                   url="localhost:5050/?tenant=west  (Westland FCU)" width={860} />
        </div>
        <div style={{flex: 1, display: 'flex', flexDirection: 'column', gap: 16}}>
          <Body size={24}>
            Westland FCU relabels the search field. Same replay, same capability:
          </Body>
          {rows.map((r) => {
            const s = spring({frame: frame - r.at, fps, config: {damping: 200}});
            return (
              <div
                key={r.label}
                style={{
                  opacity: s,
                  transform: `translateX(${interpolate(s, [0, 1], [-24, 0])}px)`,
                  border: `1px solid ${c.border}`,
                  borderLeft: `4px solid ${r.accent}`,
                  borderRadius: 8,
                  padding: '14px 20px',
                  fontFamily: mono,
                }}
              >
                <div style={{fontSize: 22, color: c.dim}}>{r.label}</div>
                <div style={{fontSize: 23, color: r.accent, fontWeight: 700, marginTop: 2}}>
                  {r.rank}
                </div>
                <div style={{fontSize: 18, color: c.code, marginTop: 3}}>{r.detail}</div>
              </div>
            );
          })}
        </div>
      </div>
      <FadeIn delay={130} style={{marginTop: 30}}>
        <Body size={24}>
          The fall-through rank <i>is</i> the drift signal — sustained rank &gt; 0
          for a tenant flags "specialize"; the overlay is the fix, not a re-record.
        </Body>
      </FadeIn>
    </AbsoluteFill>
  );
};

/* ----------------------------------------------------------- Escalation */
export const EscalationScene: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const holders = [
    {who: 'automation', reason: 'run started', at: 6},
    {who: 'operator', reason: 'replay hit HTTP 500 — intervention filed with context', at: 46},
    {who: 'automation', reason: 'operator fixed the live session · resume', at: 92},
  ];
  return (
    <AbsoluteFill style={{background: c.bg, padding: 90}}>
      <FadeIn delay={2}>
        <Kicker>6 · escalation & handoff</Kicker>
      </FadeIn>
      <FadeIn delay={8}>
        <H1 size={44}>
          When it can't safely finish, a human takes the same live session.
        </H1>
      </FadeIn>
      <div style={{display: 'flex', gap: 50, marginTop: 40, alignItems: 'flex-start'}}>
        <div
          style={{
            opacity: interpolate(frame, [16, 34], [0, 1], {extrapolateRight: 'clamp'}),
          }}
        >
          <Browser src="escalation.png" url="operator console — intervention #4606487db7" width={820} />
        </div>
        <div style={{flex: 1, display: 'flex', flexDirection: 'column', gap: 16}}>
          <Body size={24}>control ledger — append-only, one source of truth</Body>
          {holders.map((h, i) => {
            const s = spring({frame: frame - h.at, fps, config: {damping: 200}});
            return (
              <div
                key={i}
                style={{
                  opacity: s,
                  transform: `translateX(${interpolate(s, [0, 1], [-24, 0])}px)`,
                  border: `1px solid ${c.border}`,
                  borderLeft: `4px solid ${h.who === 'operator' ? c.warn : c.good}`,
                  borderRadius: 8,
                  padding: '16px 20px',
                  fontFamily: mono,
                }}
              >
                <div style={{fontSize: 24, color: h.who === 'operator' ? c.warn : c.good}}>
                  {h.who}
                </div>
                <div style={{fontSize: 20, color: c.dim, marginTop: 3}}>{h.reason}</div>
              </div>
            );
          })}
          <FadeIn delay={112}>
            <Panel accent={c.good} title="result">
              <span style={{fontSize: 22}}>
                SUCCESS — position restored, run completed
              </span>
            </Panel>
          </FadeIn>
        </div>
      </div>
    </AbsoluteFill>
  );
};

/* -------------------------------------------------------------- Close */
export const CloseScene: React.FC = () => (
  <Center gap={30}>
    <FadeIn delay={2}>
      <Kicker>one vertical slice, all the way through</Kicker>
    </FadeIn>
    <FadeIn delay={10}>
      <H1 size={48}>
        goal → LLM run → capability → deterministic replay → cross-tenant reuse → human handoff
      </H1>
    </FadeIn>
    <FadeIn delay={22}>
      <div style={{display: 'flex', flexDirection: 'column', gap: 12, fontFamily: mono, fontSize: 27, color: c.dim}}>
        <span><b style={{color: c.text}}>58</b> tests &nbsp;·&nbsp; unit + integration</span>
        <span><b style={{color: c.text}}>8</b> replay scenarios + a cross-tenant demo + an escalation handoff, all in <span style={{color: c.code}}>/evidence</span></span>
        <span>provider-agnostic discovery &nbsp;·&nbsp; Claude &nbsp;·&nbsp; NVIDIA NIM &nbsp;·&nbsp; OpenAI</span>
      </div>
    </FadeIn>
    <FadeIn delay={34}>
      <div style={{fontFamily: mono, fontSize: 28, color: c.accent}}>
        github.com/matteoshafer/interface-ai-takehome
      </div>
    </FadeIn>
  </Center>
);
