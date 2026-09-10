export const FPS = 30;
export const WIDTH = 1920;
export const HEIGHT = 1080;

export const c = {
  bg: '#0d1117',
  bgPanel: '#161b22',
  border: '#2b3440',
  text: '#e6edf3',
  dim: '#8b949e',
  accent: '#4da3ff',
  good: '#3fb950',
  warn: '#d29922',
  bad: '#f85149',
  code: '#c9d1d9',
};

export const font =
  '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif';
export const mono =
  'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace';

// scene lengths in seconds
export const SCENES = {
  title: 3.5,
  problem: 7,
  discovery: 19,
  artifact: 13,
  replay: 16,
  escalation: 11,
  close: 5,
};

export const sec = (s: number) => Math.round(s * FPS);
export const TOTAL = sec(Object.values(SCENES).reduce((a, b) => a + b, 0));
