export type Palette = {bgA: string; bgB: string; glow: string; blob: string};

// Stimmung -> Farben. Unbekannte Stimmung = "mystery".
export const PALETTES: Record<string, Palette> = {
  mystery: {bgA: '#1b1038', bgB: '#3b2a78', glow: '#9b7bff', blob: '#6a4fd6'},
  calm: {bgA: '#0b2a3d', bgB: '#17607a', glow: '#5fd4e8', blob: '#2a9bb8'},
  warm: {bgA: '#3d1a0b', bgB: '#b5541f', glow: '#ffb35c', blob: '#e07a2f'},
  cold: {bgA: '#101d2e', bgB: '#41607f', glow: '#bfe3ff', blob: '#7fa6c9'},
  tense: {bgA: '#1a0507', bgB: '#6e1220', glow: '#ff5a5f', blob: '#b0243a'},
  bright: {bgA: '#0c3b2e', bgB: '#1f8a5b', glow: '#9dffc4', blob: '#3fc486'},
};

export const getPalette = (mood: string): Palette => PALETTES[mood] ?? PALETTES.mystery;
