import { useCallback, useEffect, useState } from 'react';
import { AudioPlaylistPlayer, type PlayerState } from '@/lib/player';
import { DEFAULT_VOICE } from '@/lib/voices';

/** React binding around {@link AudioPlaylistPlayer}. */
export function usePodcastPlayer() {
  const [state, setState] = useState<PlayerState>('idle');
  const [currentSegment, setCurrentSegment] = useState(-1);
  const [error, setError] = useState<string | null>(null);

  // Create the player once; the setters are stable so the callbacks stay valid.
  const [player] = useState(
    () =>
      new AudioPlaylistPlayer({
        onState: setState,
        onSegment: setCurrentSegment,
        onError: setError,
      }),
  );

  useEffect(() => () => player.dispose(), [player]);

  const play = useCallback(
    (podcastId: string, segmentIndices: number[], voice: string = DEFAULT_VOICE) => {
      setError(null);
      player.start(podcastId, segmentIndices, voice);
    },
    [player],
  );

  const pause = useCallback(() => player.pause(), [player]);
  const resume = useCallback(() => player.resume(), [player]);
  const stop = useCallback(() => player.stop(), [player]);

  return {
    state,
    currentSegment,
    error,
    isLoading: state === 'loading',
    isPlaying: state === 'playing',
    isPaused: state === 'paused',
    play,
    pause,
    resume,
    stop,
  };
}
