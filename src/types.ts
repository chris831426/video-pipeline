export type Word = {text: string; start: number; end: number};

export type SceneData = {
  id: string;
  /** Datei unter public/, z.B. "emoji/1F511.svg" */
  icon: string;
  extraIcons: string[];
  mood: string;
  label: string;
  durationInFrames: number;
  /** Datei unter public/, z.B. "audio/scene-0.mp3" */
  audio: string;
  /** Wortzeiten in Sekunden, relativ zum Szenenstart */
  words: Word[];
};

export type VideoProps = {
  fps: number;
  scenes: SceneData[];
  style: {
    subtitleColor: string;
    accentColor: string;
    subtitlePosition: 'bottom' | 'middle';
  };
};

export const defaultProps: VideoProps = {
  fps: 30,
  scenes: [],
  style: {subtitleColor: '#FFFFFF', accentColor: '#FFD84D', subtitlePosition: 'bottom'},
};
