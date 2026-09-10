import React from 'react';
import {AbsoluteFill, Sequence, useCurrentFrame, interpolate} from 'remotion';
import {SCENES, sec, c} from './theme';
import {
  TitleScene,
  ProblemScene,
  DiscoveryScene,
  ArtifactScene,
  ReplayScene,
  EscalationScene,
  CloseScene,
} from './scenes';

const ORDER: [keyof typeof SCENES, React.FC][] = [
  ['title', TitleScene],
  ['problem', ProblemScene],
  ['discovery', DiscoveryScene],
  ['artifact', ArtifactScene],
  ['replay', ReplayScene],
  ['escalation', EscalationScene],
  ['close', CloseScene],
];

const CrossFade: React.FC<{durationInFrames: number; children: React.ReactNode}> = ({
  durationInFrames,
  children,
}) => {
  const frame = useCurrentFrame();
  const fade = 12;
  const opacity = interpolate(
    frame,
    [0, fade, durationInFrames - fade, durationInFrames],
    [0, 1, 1, 0],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'},
  );
  return <AbsoluteFill style={{opacity}}>{children}</AbsoluteFill>;
};

export const Walkthrough: React.FC = () => {
  let from = 0;
  return (
    <AbsoluteFill style={{background: c.bg}}>
      {ORDER.map(([key, Comp]) => {
        const dur = sec(SCENES[key]);
        const seq = (
          <Sequence key={key} from={from} durationInFrames={dur}>
            <CrossFade durationInFrames={dur}>
              <Comp />
            </CrossFade>
          </Sequence>
        );
        from += dur;
        return seq;
      })}
    </AbsoluteFill>
  );
};
