import React from 'react';
import {
  AbsoluteFill,
  Html5Audio,
  Img,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {loadFont} from '@remotion/google-fonts/Poppins';
import {getPalette} from './palette';
import {SceneData, VideoProps, Word} from './types';

const {fontFamily} = loadFont('normal', {
  weights: ['700', '800'],
  subsets: ['latin', 'latin-ext'],
});

const FADE_FRAMES = 9; // Überblendung zwischen Szenen

// Deterministischer Pseudo-Zufall (gleiches Ergebnis bei jedem Render)
const rand = (seed: number) => {
  const x = Math.sin(seed * 12.9898) * 43758.5453;
  return x - Math.floor(x);
};

// ---------------------------------------------------------------- Hintergrund

const Background: React.FC<{mood: string; seed: number}> = ({mood, seed}) => {
  const frame = useCurrentFrame();
  const p = getPalette(mood);
  const angle = 160 + Math.sin(frame / 90 + seed) * 25;

  const blobs = Array.from({length: 5}, (_, i) => {
    const s = seed * 10 + i;
    const size = 500 + rand(s) * 600;
    const baseX = rand(s + 1) * 1080;
    const baseY = rand(s + 2) * 1920;
    const x = baseX + Math.sin(frame / (70 + i * 15) + s) * 90;
    const y = baseY + Math.cos(frame / (80 + i * 12) + s) * 110;
    return (
      <div
        key={i}
        style={{
          position: 'absolute',
          left: x - size / 2,
          top: y - size / 2,
          width: size,
          height: size,
          borderRadius: '50%',
          background: `radial-gradient(circle, ${p.blob}55 0%, ${p.blob}00 70%)`,
        }}
      />
    );
  });

  return (
    <AbsoluteFill style={{background: `linear-gradient(${angle}deg, ${p.bgA}, ${p.bgB})`}}>
      {blobs}
      <AbsoluteFill
        style={{
          background: 'radial-gradient(ellipse at center, rgba(0,0,0,0) 45%, rgba(0,0,0,0.55) 100%)',
        }}
      />
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------- Icons

const entrance = (variant: number, progress: number) => {
  // 0: von unten springen, 1: von links hineindrehen, 2: aufpoppen
  if (variant === 0) return {x: 0, y: (1 - progress) * 380, rot: 0, s: 0.6 + 0.4 * progress};
  if (variant === 1) return {x: (1 - progress) * -520, y: 0, rot: (1 - progress) * -35, s: 0.7 + 0.3 * progress};
  return {x: 0, y: 0, rot: (1 - progress) * 14, s: 0.2 + 0.8 * progress};
};

const Hero: React.FC<{file: string; index: number; centerY: number; size: number; mood: string}> = ({
  file,
  index,
  centerY,
  size,
  mood,
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const p = getPalette(mood);
  const progress = spring({frame, fps, config: {damping: 11, stiffness: 90, mass: 0.9}});
  const e = entrance(index % 3, progress);
  const floatY = Math.sin(frame / 18) * 22;
  const wobble = Math.sin(frame / 26) * 3;
  const breathe = 1 + Math.sin(frame / 30) * 0.025;
  const glowPulse = 0.75 + Math.sin(frame / 22) * 0.15;

  return (
    <>
      {/* Lichtschein hinter dem Objekt */}
      <div
        style={{
          position: 'absolute',
          left: 540 - size,
          top: centerY - size,
          width: size * 2,
          height: size * 2,
          borderRadius: '50%',
          opacity: glowPulse * progress,
          background: `radial-gradient(circle, ${p.glow}66 0%, ${p.glow}00 65%)`,
        }}
      />
      {/* Bodenschatten */}
      <div
        style={{
          position: 'absolute',
          left: 540 - size * 0.45,
          top: centerY + size * 0.52 - floatY * 0.15,
          width: size * 0.9,
          height: size * 0.14,
          borderRadius: '50%',
          opacity: 0.35 * progress,
          transform: `scale(${1 - floatY / 400})`,
          background: 'radial-gradient(ellipse, rgba(0,0,0,0.8) 0%, rgba(0,0,0,0) 70%)',
        }}
      />
      <Img
        src={staticFile(file)}
        style={{
          position: 'absolute',
          left: 540 - size / 2,
          top: centerY - size / 2,
          width: size,
          height: size,
          transform: `translate(${e.x}px, ${e.y + floatY}px) rotate(${e.rot + wobble}deg) scale(${e.s * breathe})`,
          filter: 'drop-shadow(0 22px 28px rgba(0,0,0,0.45))',
        }}
      />
    </>
  );
};

const ExtraIcon: React.FC<{file: string; slot: number; heroY: number; heroSize: number}> = ({
  file,
  slot,
  heroY,
  heroSize,
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const delay = 10 + slot * 7;
  const progress = spring({frame: frame - delay, fps, config: {damping: 10, stiffness: 110}});
  const size = heroSize * 0.42;
  const side = slot % 2 === 0 ? -1 : 1;
  const cx = 540 + side * (heroSize * 0.62);
  const cy = heroY + heroSize * (slot < 2 ? 0.34 : -0.34) + Math.sin(frame / 20 + slot * 2) * 16;
  return (
    <Img
      src={staticFile(file)}
      style={{
        position: 'absolute',
        left: cx - size / 2,
        top: cy - size / 2,
        width: size,
        height: size,
        opacity: progress,
        transform: `scale(${progress}) rotate(${side * 10 + Math.sin(frame / 30 + slot) * 5}deg)`,
        filter: 'drop-shadow(0 14px 18px rgba(0,0,0,0.4))',
      }}
    />
  );
};

const Label: React.FC<{text: string; y: number}> = ({text, y}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const progress = spring({frame: frame - 14, fps, config: {damping: 14, stiffness: 100}});
  if (!text) return null;
  return (
    <div
      style={{
        position: 'absolute',
        left: 0,
        width: 1080,
        top: y,
        display: 'flex',
        justifyContent: 'center',
        opacity: progress,
        transform: `translateY(${(1 - progress) * 30}px)`,
      }}
    >
      <div
        style={{
          fontFamily,
          fontWeight: 700,
          fontSize: 44,
          letterSpacing: 6,
          textTransform: 'uppercase',
          color: 'rgba(255,255,255,0.92)',
          padding: '14px 38px',
          borderRadius: 999,
          background: 'rgba(255,255,255,0.12)',
          border: '2px solid rgba(255,255,255,0.28)',
        }}
      >
        {text}
      </div>
    </div>
  );
};

// ---------------------------------------------------------------- Untertitel

type Chunk = {words: Word[]; start: number};

const makeChunks = (words: Word[]): Chunk[] => {
  const chunks: Chunk[] = [];
  let cur: Word[] = [];
  let chars = 0;
  for (const w of words) {
    const len = w.text.length + 1;
    if (cur.length > 0 && (chars + len > 22 || cur.length >= 4)) {
      chunks.push({words: cur, start: cur[0].start});
      cur = [];
      chars = 0;
    }
    cur.push(w);
    chars += len;
  }
  if (cur.length) chunks.push({words: cur, start: cur[0].start});
  return chunks;
};

const Subtitles: React.FC<{
  words: Word[];
  color: string;
  accent: string;
  centerY: number;
}> = ({words, color, accent, centerY}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const t = frame / fps;
  const chunks = React.useMemo(() => makeChunks(words), [words]);
  if (!chunks.length) return null;

  let idx = 0;
  for (let i = 0; i < chunks.length; i++) {
    if (t >= chunks[i].start - 0.05) idx = i;
  }
  const chunk = chunks[idx];
  const chunkFrame = Math.max(0, frame - Math.floor(chunk.start * fps));
  const pop = spring({frame: chunkFrame, fps, config: {damping: 14, stiffness: 160}, durationInFrames: 12});

  return (
    <div
      style={{
        position: 'absolute',
        left: 60,
        width: 960,
        top: centerY - 130,
        height: 260,
        display: 'flex',
        flexWrap: 'wrap',
        alignContent: 'center',
        justifyContent: 'center',
        gap: '6px 22px',
        transform: `scale(${0.92 + 0.08 * pop})`,
        opacity: Math.min(1, pop * 1.4),
      }}
    >
      {chunk.words.map((w, i) => {
        const spoken = t >= w.start;
        const active = t >= w.start && t < w.end + 0.08;
        return (
          <span
            key={i}
            style={{
              fontFamily,
              fontWeight: 800,
              fontSize: 86,
              lineHeight: 1.12,
              color: active ? accent : color,
              opacity: spoken ? 1 : 0.5,
              transform: `scale(${active ? 1.12 : 1})`,
              WebkitTextStroke: '12px rgba(0,0,0,0.85)',
              paintOrder: 'stroke fill',
              textShadow: '0 6px 18px rgba(0,0,0,0.5)',
              display: 'inline-block',
            }}
          >
            {w.text}
          </span>
        );
      })}
    </div>
  );
};

// ---------------------------------------------------------------- Szene

const Scene: React.FC<{
  scene: SceneData;
  index: number;
  style: VideoProps['style'];
  isFirst: boolean;
}> = ({scene, index, style, isFirst}) => {
  const frame = useCurrentFrame();
  const fadeIn = isFirst ? 1 : interpolate(frame, [0, FADE_FRAMES], [0, 1], {extrapolateRight: 'clamp'});
  const bottom = style.subtitlePosition !== 'middle';
  const heroSize = bottom ? 620 : 520;
  const heroY = bottom ? 640 : 520;
  const labelY = heroY + heroSize * 0.62;
  const subY = bottom ? 1280 : 1020;

  return (
    <AbsoluteFill style={{opacity: fadeIn}}>
      <Background mood={scene.mood} seed={index + 1} />
      <Hero file={scene.icon} index={index} centerY={heroY} size={heroSize} mood={scene.mood} />
      {scene.extraIcons.slice(0, 2).map((f, i) => (
        <ExtraIcon key={i} file={f} slot={i} heroY={heroY} heroSize={heroSize} />
      ))}
      <Label text={scene.label} y={labelY} />
      <Subtitles words={scene.words} color={style.subtitleColor} accent={style.accentColor} centerY={subY} />
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------- Video

export const Video: React.FC<VideoProps> = ({scenes, style}) => {
  let start = 0;
  return (
    <AbsoluteFill style={{backgroundColor: '#000'}}>
      {scenes.map((scene, i) => {
        const from = start;
        start += scene.durationInFrames;
        const isLast = i === scenes.length - 1;
        // Szene läuft FADE_FRAMES länger, damit die nächste weich darüber einblendet.
        const visualDuration = scene.durationInFrames + (isLast ? 0 : FADE_FRAMES);
        return (
          <React.Fragment key={scene.id + i}>
            <Sequence from={from} durationInFrames={visualDuration}>
              <Scene scene={scene} index={i} style={style} isFirst={i === 0} />
            </Sequence>
            <Sequence from={from} durationInFrames={scene.durationInFrames}>
              <Html5Audio src={staticFile(scene.audio)} />
            </Sequence>
          </React.Fragment>
        );
      })}
    </AbsoluteFill>
  );
};
