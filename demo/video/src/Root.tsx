import React from 'react';
import {Composition} from 'remotion';
import {Walkthrough} from './Walkthrough';
import {FPS, WIDTH, HEIGHT, TOTAL} from './theme';

export const RemotionRoot: React.FC = () => (
  <Composition
    id="Walkthrough"
    component={Walkthrough}
    durationInFrames={TOTAL}
    fps={FPS}
    width={WIDTH}
    height={HEIGHT}
  />
);
