/**
 * Sequential audio-playlist player.
 *
 * Audio is synthesized server-side by Kokoro-82M (see server/tts.ts) and fetched
 * per segment from `/api/podcasts/:id/audio/:segment`. This player just streams
 * those segments in order through a single HTMLAudioElement, exposing
 * play/pause/resume/stop and reporting which segment is currently playing.
 */
export type PlayerState = 'idle' | 'loading' | 'playing' | 'paused' | 'ended' | 'error';

interface PlayerCallbacks {
  onState?: (s: PlayerState) => void;
  /** The real podcast segment index now playing, or -1 when nothing is. */
  onSegment?: (segmentIndex: number) => void;
  onError?: (message: string) => void;
}

export class AudioPlaylistPlayer {
  private audio: HTMLAudioElement;
  private podcastId = '';
  private segments: number[] = [];
  private voice = '';
  private pos = 0;
  private state: PlayerState = 'idle';
  private cb: PlayerCallbacks;

  constructor(cb: PlayerCallbacks = {}) {
    this.cb = cb;
    this.audio = new Audio();
    this.audio.preload = 'auto';
    this.audio.addEventListener('ended', () => this.playAt(this.pos + 1));
    this.audio.addEventListener('playing', () => this.setState('playing'));
    this.audio.addEventListener('waiting', () => {
      if (this.state === 'playing') this.setState('loading');
    });
    this.audio.addEventListener('error', () => {
      // Ignore errors triggered by clearing the source during stop().
      if (this.segments.length === 0) return;
      this.cb.onError?.('Failed to load audio for this segment.');
      this.setState('error');
    });
  }

  getState(): PlayerState {
    return this.state;
  }

  private setState(s: PlayerState): void {
    this.state = s;
    this.cb.onState?.(s);
  }

  /** Start playing the given segment indices (in order) for a podcast. */
  start(podcastId: string, segments: number[], voice: string): void {
    this.stop();
    this.podcastId = podcastId;
    this.segments = segments;
    this.voice = voice;
    this.pos = 0;
    if (segments.length === 0) {
      this.cb.onError?.('No summaries are ready to play yet.');
      return;
    }
    this.playAt(0);
  }

  private playAt(i: number): void {
    if (i >= this.segments.length) {
      this.setState('ended');
      this.cb.onSegment?.(-1);
      return;
    }
    this.pos = i;
    const segIndex = this.segments[i];
    this.cb.onSegment?.(segIndex);
    this.setState('loading');
    this.audio.src = this.segmentUrl(segIndex);
    this.audio.play().catch(() => {
      // Autoplay/abort — surfaced via the 'error' handler when relevant.
    });
    // Warm the next segment's audio (server + browser cache) while this one
    // plays, so transitions are gapless instead of pausing to synthesize.
    this.prefetch(i + 1);
  }

  private segmentUrl(segIndex: number): string {
    return `/api/podcasts/${this.podcastId}/audio/${segIndex}?voice=${encodeURIComponent(this.voice)}`;
  }

  /** Fetch a segment's audio ahead of time without playing it (best-effort). */
  private prefetch(i: number): void {
    if (i < 0 || i >= this.segments.length) return;
    void fetch(this.segmentUrl(this.segments[i])).catch(() => {});
  }

  pause(): void {
    if (this.state === 'playing') {
      this.audio.pause();
      this.setState('paused');
    }
  }

  resume(): void {
    if (this.state === 'paused') {
      void this.audio.play().catch(() => {});
      this.setState('playing');
    }
  }

  stop(): void {
    this.segments = [];
    this.pos = 0;
    this.audio.pause();
    this.audio.removeAttribute('src');
    this.audio.load();
    if (this.state !== 'idle') this.setState('idle');
    this.cb.onSegment?.(-1);
  }

  dispose(): void {
    this.stop();
  }
}
