/**
 * Antikythera F1 Custom Icon Set
 * 
 * Cyberpunk racing / esports aesthetic icons for the F1 Video Generator
 * 
 * Usage with SVGR (recommended):
 *   import { DashboardIcon, EpisodesIcon } from '@/icons';
 *   <DashboardIcon className="w-6 h-6 text-neon-cyan" />
 * 
 * All icons use currentColor for easy theming.
 * Default size: 24x24px
 */

// Navigation Icons
export { default as DashboardIcon } from './dashboard.svg';
export { default as EpisodesIcon } from './episodes.svg';
export { default as CharactersIcon } from './characters.svg';
export { default as AnalyticsIcon } from './analytics.svg';
export { default as SettingsIcon } from './settings.svg';

// Status Icons
export { default as GeneratingIcon } from './generating.svg';
export { default as CompleteIcon } from './complete.svg';
export { default as FailedIcon } from './failed.svg';
export { default as PendingIcon } from './pending.svg';
export { default as UploadingIcon } from './uploading.svg';

// Action Icons
export { default as PlayIcon } from './play.svg';
export { default as PauseIcon } from './pause.svg';
export { default as RegenerateIcon } from './regenerate.svg';
export { default as UploadIcon } from './upload.svg';
export { default as DownloadIcon } from './download.svg';
export { default as DeleteIcon } from './delete.svg';

// Content Icons
export { default as VideoIcon } from './video.svg';
export { default as SceneIcon } from './scene.svg';
export { default as AudioIcon } from './audio.svg';
export { default as ScriptIcon } from './script.svg';

// Racing Themed Icons
export { default as RaceFlagIcon } from './race-flag.svg';
export { default as HelmetIcon } from './helmet.svg';
export { default as TrackIcon } from './track.svg';
export { default as PodiumIcon } from './podium.svg';

/**
 * Icon name mapping for dynamic imports
 */
export const iconNames = [
  // Navigation
  'dashboard',
  'episodes', 
  'characters',
  'analytics',
  'settings',
  // Status
  'generating',
  'complete',
  'failed',
  'pending',
  'uploading',
  // Actions
  'play',
  'pause',
  'regenerate',
  'upload',
  'download',
  'delete',
  // Content
  'video',
  'scene',
  'audio',
  'script',
  // Racing
  'race-flag',
  'helmet',
  'track',
  'podium',
] as const;

export type IconName = typeof iconNames[number];

/**
 * Icon categories for organized access
 */
export const iconCategories = {
  navigation: ['dashboard', 'episodes', 'characters', 'analytics', 'settings'],
  status: ['generating', 'complete', 'failed', 'pending', 'uploading'],
  actions: ['play', 'pause', 'regenerate', 'upload', 'download', 'delete'],
  content: ['video', 'scene', 'audio', 'script'],
  racing: ['race-flag', 'helmet', 'track', 'podium'],
} as const;
