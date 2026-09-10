import React from 'react';
import {interpolate, spring, useCurrentFrame, useVideoConfig, Img, staticFile} from 'remotion';
import {c, font, mono} from './theme';

export const FadeIn: React.FC<{
  children: React.ReactNode;
  delay?: number;
  y?: number;
  style?: React.CSSProperties;
}> = ({children, delay = 0, y = 24, style}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const s = spring({frame: frame - delay, fps, config: {damping: 200}});
  return (
    <div
      style={{
        opacity: s,
        transform: `translateY(${interpolate(s, [0, 1], [y, 0])}px)`,
        ...style,
      }}
    >
      {children}
    </div>
  );
};

export const Kicker: React.FC<{children: React.ReactNode}> = ({children}) => (
  <div
    style={{
      fontFamily: mono,
      fontSize: 26,
      letterSpacing: 2,
      textTransform: 'uppercase',
      color: c.accent,
    }}
  >
    {children}
  </div>
);

export const H1: React.FC<{children: React.ReactNode; size?: number}> = ({
  children,
  size = 76,
}) => (
  <div
    style={{
      fontFamily: font,
      fontSize: size,
      fontWeight: 700,
      color: c.text,
      lineHeight: 1.1,
      letterSpacing: -1,
    }}
  >
    {children}
  </div>
);

export const Body: React.FC<{children: React.ReactNode; size?: number}> = ({
  children,
  size = 34,
}) => (
  <div style={{fontFamily: font, fontSize: size, color: c.dim, lineHeight: 1.45}}>
    {children}
  </div>
);

export const Browser: React.FC<{
  src: string;
  url: string;
  width?: number;
  style?: React.CSSProperties;
}> = ({src, url, width = 1180, style}) => (
  <div
    style={{
      width,
      borderRadius: 12,
      overflow: 'hidden',
      border: `1px solid ${c.border}`,
      boxShadow: '0 40px 120px rgba(0,0,0,0.55)',
      background: c.bgPanel,
      ...style,
    }}
  >
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '12px 16px',
        borderBottom: `1px solid ${c.border}`,
      }}
    >
      {['#f85149', '#d29922', '#3fb950'].map((d) => (
        <div key={d} style={{width: 12, height: 12, borderRadius: 6, background: d}} />
      ))}
      <div
        style={{
          marginLeft: 12,
          flex: 1,
          fontFamily: mono,
          fontSize: 18,
          color: c.dim,
          background: c.bg,
          borderRadius: 6,
          padding: '6px 12px',
        }}
      >
        {url}
      </div>
    </div>
    <Img src={staticFile(src)} style={{width: '100%', display: 'block'}} />
  </div>
);

export const Panel: React.FC<{
  children: React.ReactNode;
  title?: string;
  accent?: string;
  style?: React.CSSProperties;
}> = ({children, title, accent = c.border, style}) => (
  <div
    style={{
      background: c.bgPanel,
      border: `1px solid ${c.border}`,
      borderLeft: `4px solid ${accent}`,
      borderRadius: 10,
      padding: '22px 26px',
      fontFamily: mono,
      fontSize: 24,
      color: c.code,
      lineHeight: 1.5,
      ...style,
    }}
  >
    {title ? (
      <div style={{color: c.dim, fontSize: 18, marginBottom: 10, letterSpacing: 1}}>
        {title}
      </div>
    ) : null}
    {children}
  </div>
);

export const progress = (frame: number, start: number, end: number) =>
  interpolate(frame, [start, end], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
