import { useState, useEffect, useRef, useCallback } from "react";
import { Box, Text, useInput, useApp } from "ink";
import type { SpotifyApi, PlaybackState, Device, Track } from "@spotify/web-api-ts-sdk";

const POLL_INTERVAL_MS = 5_000;
const PROGRESS_BAR_WIDTH = 30;
const VOLUME_STEP = 5;

type Mode = "now_playing" | "devices";

function formatTime(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

function isTrack(item: PlaybackState["item"]): item is Track {
  return "album" in item;
}

function getTrackInfo(item: PlaybackState["item"]) {
  if (isTrack(item)) {
    return {
      name: item.name,
      artists: item.artists.map((a) => a.name).join(", "),
      album: item.album.name,
      durationMs: item.duration_ms,
    };
  }

  return {
    name: item.name,
    artists: item.show?.name ?? "Podcast",
    album: "",
    durationMs: item.duration_ms,
  };
}

function ProgressBar({
  progress,
  total,
  width,
}: {
  progress: number;
  total: number;
  width: number;
}) {
  const ratio = total > 0 ? Math.min(progress / total, 1) : 0;
  const filled = Math.round(ratio * width);
  const empty = width - filled;

  return (
    <Text>
      <Text color="green">{"█".repeat(filled)}</Text>
      <Text color="gray">{"░".repeat(empty)}</Text>
      <Text>
        {" "}
        {formatTime(progress)} / {formatTime(total)}
      </Text>
    </Text>
  );
}

interface AppProps {
  api: SpotifyApi;
}

export default function App({ api }: AppProps) {
  const { exit } = useApp();
  const [playback, setPlayback] = useState<PlaybackState | null>(null);
  const [mode, setMode] = useState<Mode>("now_playing");
  const [devices, setDevices] = useState<Device[]>([]);
  const [selectedDeviceIdx, setSelectedDeviceIdx] = useState(0);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [displayProgressMs, setDisplayProgressMs] = useState(0);

  const anchorRef = useRef({
    progressMs: 0,
    timestamp: Date.now(),
    isPlaying: false,
  });
  const statusTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isPollingRef = useRef(false);

  const showStatus = useCallback((msg: string) => {
    setStatusMessage(msg);
    if (statusTimeoutRef.current) clearTimeout(statusTimeoutRef.current);
    statusTimeoutRef.current = setTimeout(() => setStatusMessage(null), 3000);
  }, []);

  const pollPlayback = useCallback(async () => {
    if (isPollingRef.current) return;
    isPollingRef.current = true;
    try {
      const state = (await api.player.getPlaybackState()) as PlaybackState | null;
      setPlayback(state);
      const progressMs = state?.progress_ms ?? 0;
      anchorRef.current = {
        progressMs,
        timestamp: Date.now(),
        isPlaying: state?.is_playing ?? false,
      };
      setDisplayProgressMs(progressMs);
    } catch {
      // ignore polling errors
    } finally {
      isPollingRef.current = false;
    }
  }, [api]);

  useEffect(() => {
    pollPlayback();
    const id = setInterval(pollPlayback, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [pollPlayback]);

  // interpolate progress locally every second for smooth updates
  useEffect(() => {
    const id = setInterval(() => {
      const { progressMs, timestamp, isPlaying } = anchorRef.current;
      if (isPlaying) {
        setDisplayProgressMs(progressMs + (Date.now() - timestamp));
      }
    }, 1000);
    return () => clearInterval(id);
  }, []);

  const deviceId = playback?.device?.id ?? "";

  const withErrorHandling = useCallback(
    async (action: () => Promise<void>, failMsg: string) => {
      try {
        await action();
        setTimeout(pollPlayback, 500);
      } catch {
        showStatus(failMsg);
      }
    },
    [pollPlayback, showStatus]
  );

  useInput((input, key) => {
    if (key.ctrl && input === "c") {
      exit();
      return;
    }

    if (mode === "devices") {
      if (key.upArrow) {
        setSelectedDeviceIdx((i) => Math.max(0, i - 1));
      } else if (key.downArrow) {
        setSelectedDeviceIdx((i) => Math.min(devices.length - 1, i + 1));
      } else if (key.return) {
        const device = devices[selectedDeviceIdx];
        if (device?.id) {
          withErrorHandling(async () => {
            await api.player.transferPlayback([device.id!]);
            showStatus(`Transferred to ${device.name}`);
            setMode("now_playing");
          }, "Failed to transfer playback");
        }
      } else if (key.escape || input === "q") {
        setMode("now_playing");
      }
      return;
    }

    if (input === " ") {
      withErrorHandling(async () => {
        if (playback?.is_playing) {
          await api.player.pausePlayback(deviceId);
          showStatus("Paused");
        } else {
          await api.player.startResumePlayback(deviceId);
          showStatus("Playing");
        }
      }, "Failed to toggle playback");
    } else if (input === "n") {
      withErrorHandling(async () => {
        await api.player.skipToNext(deviceId);
        showStatus("Next track");
      }, "Failed to skip");
    } else if (input === "b") {
      withErrorHandling(async () => {
        await api.player.skipToPrevious(deviceId);
        showStatus("Previous track");
      }, "Failed to go back");
    } else if (input === "+" || input === "=") {
      const newVol = Math.min(100, (playback?.device?.volume_percent ?? 50) + VOLUME_STEP);
      withErrorHandling(async () => {
        await api.player.setPlaybackVolume(newVol);
        showStatus(`Volume: ${newVol}%`);
      }, "Failed to change volume");
    } else if (input === "-") {
      const newVol = Math.max(0, (playback?.device?.volume_percent ?? 50) - VOLUME_STEP);
      withErrorHandling(async () => {
        await api.player.setPlaybackVolume(newVol);
        showStatus(`Volume: ${newVol}%`);
      }, "Failed to change volume");
    } else if (input === "s") {
      const newState = !playback?.shuffle_state;
      withErrorHandling(async () => {
        await api.player.togglePlaybackShuffle(newState);
        showStatus(`Shuffle: ${newState ? "On" : "Off"}`);
      }, "Failed to toggle shuffle");
    } else if (input === "r") {
      const current = playback?.repeat_state ?? "off";
      const next =
        current === "off" ? "context" : current === "context" ? "track" : "off";
      withErrorHandling(async () => {
        await api.player.setRepeatMode(next as "track" | "context" | "off");
        showStatus(`Repeat: ${next}`);
      }, "Failed to change repeat mode");
    } else if (input === "d") {
      (async () => {
        try {
          const result = await api.player.getAvailableDevices();
          setDevices(result.devices);
          setSelectedDeviceIdx(0);
          setMode("devices");
        } catch {
          showStatus("Failed to load devices");
        }
      })();
    } else if (input === "q") {
      exit();
    }
  });

  if (mode === "devices") {
    return (
      <Box flexDirection="column" padding={1}>
        <Text color="green" bold>
          Select a device:
        </Text>
        <Text> </Text>
        {devices.length === 0 ? (
          <Text color="yellow">No devices found</Text>
        ) : (
          devices.map((device, i) => (
            <Text
              key={device.id ?? i}
              color={device.is_active ? "cyan" : "white"}
              bold={i === selectedDeviceIdx}
            >
              {i === selectedDeviceIdx ? "> " : "  "}
              {device.name} ({device.type})
              {device.is_active ? " ●" : ""}
            </Text>
          ))
        )}
        <Text> </Text>
        <Text color="gray">Enter to select, q/Esc to go back</Text>
      </Box>
    );
  }

  const trackInfo = playback?.item ? getTrackInfo(playback.item) : null;

  return (
    <Box flexDirection="column" padding={1}>
      <Text color="green" bold>
        ♫ Spotify
      </Text>
      <Text color="green">{"─".repeat(40)}</Text>

      {!playback || !trackInfo ? (
        <Box flexDirection="column" marginY={1}>
          <Text color="yellow">Nothing playing</Text>
          <Text color="gray">Start playback on any Spotify device</Text>
        </Box>
      ) : (
        <Box flexDirection="column" marginY={1}>
          <Text color="white" bold>
            {trackInfo.name}
          </Text>
          <Text color="cyan">{trackInfo.artists}</Text>
          {trackInfo.album ? <Text color="gray">{trackInfo.album}</Text> : null}
          <Text> </Text>
          <ProgressBar
            progress={displayProgressMs}
            total={trackInfo.durationMs}
            width={PROGRESS_BAR_WIDTH}
          />
          <Text> </Text>
          <Text>
            <Text color={playback.is_playing ? "green" : "yellow"}>
              {playback.is_playing ? "▶ Playing" : "⏸ Paused"}
            </Text>
            <Text color="gray"> │ </Text>
            <Text>Vol: {playback.device?.volume_percent ?? "?"}%</Text>
            <Text color="gray"> │ </Text>
            <Text color={playback.shuffle_state ? "green" : "gray"}>
              Shuffle: {playback.shuffle_state ? "On" : "Off"}
            </Text>
            <Text color="gray"> │ </Text>
            <Text color={playback.repeat_state !== "off" ? "green" : "gray"}>
              Repeat: {playback.repeat_state}
            </Text>
          </Text>
          <Text color="gray">Device: {playback.device?.name ?? "Unknown"}</Text>
        </Box>
      )}

      {statusMessage && (
        <Text color="yellow" bold>
          {statusMessage}
        </Text>
      )}

      <Text color="green">{"─".repeat(40)}</Text>
      <Text color="gray">
        {"[space] Play/Pause  [n] Next      [b] Previous"}
      </Text>
      <Text color="gray">
        {"[+/-]   Volume      [d] Devices   [s] Shuffle"}
      </Text>
      <Text color="gray">
        {"[r]     Repeat      [q] Quit"}
      </Text>
    </Box>
  );
}
