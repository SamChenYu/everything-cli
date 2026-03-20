import { useState, useEffect, useRef, useCallback } from "react";
import { Box, Text, useInput, useApp } from "ink";
import type {
  SpotifyApi,
  PlaybackState,
  Track,
  SimplifiedPlaylist,
} from "@spotify/web-api-ts-sdk";
import type { TrackCache, CachedTrack } from "./cache.js";

const POLL_INTERVAL_MS = 5_000;
const PROGRESS_BAR_WIDTH = 30;
const VOLUME_STEP = 5;

function formatTime(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

function parseCommand(raw: string): { cmd: string; args: string } {
  const trimmed = raw.trim();
  const i = trimmed.indexOf(" ");
  if (i === -1) return { cmd: trimmed.toLowerCase(), args: "" };
  return {
    cmd: trimmed.slice(0, i).toLowerCase(),
    args: trimmed.slice(i + 1).trim(),
  };
}

function parseSeek(s: string): number | null {
  if (s.includes(":")) {
    const [min, sec] = s.split(":");
    const m = parseInt(min!, 10);
    const sc = parseInt(sec!, 10);
    if (isNaN(m) || isNaN(sc)) return null;
    return (m * 60 + sc) * 1000;
  }
  const n = parseInt(s, 10);
  return isNaN(n) ? null : n * 1000;
}

function isTrack(item: PlaybackState["item"]): item is Track {
  return "album" in item;
}

interface OutputLine {
  text: string;
  color: string;
}

function line(text: string, color = "white"): OutputLine {
  return { text, color };
}

interface AppProps {
  api: SpotifyApi;
  cache: TrackCache;
}

export default function App({ api, cache }: AppProps) {
  const { exit } = useApp();
  const [playback, setPlayback] = useState<PlaybackState | null>(null);
  const [input, setInput] = useState("");
  const [output, setOutput] = useState<OutputLine[]>([]);
  const [displayProgressMs, setDisplayProgressMs] = useState(0);

  const searchResultsRef = useRef<Track[]>([]);
  const playlistResultsRef = useRef<SimplifiedPlaylist[]>([]);
  const anchorRef = useRef({
    progressMs: 0,
    timestamp: Date.now(),
    isPlaying: false,
  });
  const isPollingRef = useRef(false);

  const cacheTrack = useCallback(
    (item: PlaybackState["item"]) => {
      if (isTrack(item)) {
        cache.add(item);
      }
    },
    [cache]
  );

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
      if (state?.item) cacheTrack(state.item);
    } catch {
      // ignore polling errors
    } finally {
      isPollingRef.current = false;
    }
  }, [api, cacheTrack]);

  useEffect(() => {
    pollPlayback();
    const id = setInterval(pollPlayback, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [pollPlayback]);

  useEffect(() => {
    const id = setInterval(() => {
      const { progressMs, timestamp, isPlaying } = anchorRef.current;
      if (isPlaying) {
        setDisplayProgressMs(progressMs + (Date.now() - timestamp));
      }
    }, 1000);
    return () => clearInterval(id);
  }, []);

  // save cache on unmount
  useEffect(() => () => cache.save(), [cache]);

  const getDeviceId = () => playback?.device?.id ?? "";

  const executeCommand = useCallback(
    async (raw: string) => {
      const { cmd, args } = parseCommand(raw);
      if (!cmd) return;

      const deviceId = getDeviceId();

      try {
        switch (cmd) {
          // ── playback ──────────────────────────────────
          case "play":
          case "resume": {
            if (!args) {
              setPlayback((p) =>
                p ? { ...p, is_playing: true } : p
              );
              await api.player.startResumePlayback(deviceId);
              setOutput([line("▶ Resumed", "green")]);
            } else {
              const n = parseInt(args, 10);
              if (
                !isNaN(n) &&
                n >= 1 &&
                n <= searchResultsRef.current.length
              ) {
                const track = searchResultsRef.current[n - 1]!;
                cache.add(track);
                await api.player.startResumePlayback(
                  deviceId,
                  undefined,
                  [track.uri]
                );
                setOutput([
                  line(
                    `▶ Playing: ${track.name} - ${track.artists.map((a) => a.name).join(", ")}`,
                    "green"
                  ),
                ]);
              } else {
                const cached = cache.search(args);
                if (cached.length > 0) {
                  const hit = cached[0]!;
                  await api.player.startResumePlayback(
                    deviceId,
                    undefined,
                    [hit.uri]
                  );
                  setOutput([
                    line(`▶ Playing (cached): ${cache.format(hit)}`, "green"),
                  ]);
                } else {
                  const results = await api.search(
                    args,
                    ["track"],
                    undefined,
                    1
                  );
                  const top = results.tracks.items[0];
                  if (top) {
                    cache.add(top);
                    await api.player.startResumePlayback(
                      deviceId,
                      undefined,
                      [top.uri]
                    );
                    setOutput([
                      line(
                        `▶ Playing: ${top.name} - ${top.artists.map((a) => a.name).join(", ")}`,
                        "green"
                      ),
                    ]);
                  } else {
                    setOutput([line(`No results for "${args}"`, "yellow")]);
                  }
                }
              }
            }
            setTimeout(pollPlayback, 800);
            break;
          }

          case "pause": {
            setPlayback((p) =>
              p ? { ...p, is_playing: false } : p
            );
            await api.player.pausePlayback(deviceId);
            setOutput([line("⏸ Paused", "yellow")]);
            break;
          }

          case "next":
          case "n": {
            await api.player.skipToNext(deviceId);
            setOutput([line("⏭ Next track", "green")]);
            setTimeout(pollPlayback, 800);
            break;
          }

          case "prev":
          case "p": {
            await api.player.skipToPrevious(deviceId);
            setOutput([line("⏮ Previous track", "green")]);
            setTimeout(pollPlayback, 800);
            break;
          }

          // ── volume ────────────────────────────────────
          case "vol":
          case "v": {
            const currentVol = playback?.device?.volume_percent ?? 50;
            let newVol: number;
            if (args === "+" || args === "") {
              newVol = Math.min(100, currentVol + VOLUME_STEP);
            } else if (args === "-") {
              newVol = Math.max(0, currentVol - VOLUME_STEP);
            } else if (args.startsWith("+")) {
              newVol = Math.min(
                100,
                currentVol + (parseInt(args.slice(1), 10) || VOLUME_STEP)
              );
            } else if (args.startsWith("-")) {
              newVol = Math.max(
                0,
                currentVol - (parseInt(args.slice(1), 10) || VOLUME_STEP)
              );
            } else {
              newVol = Math.max(0, Math.min(100, parseInt(args, 10) || 0));
            }
            setPlayback((p) =>
              p
                ? { ...p, device: { ...p.device, volume_percent: newVol } }
                : p
            );
            await api.player.setPlaybackVolume(newVol);
            setOutput([line(`Volume: ${newVol}%`, "green")]);
            break;
          }

          // ── shuffle / repeat ──────────────────────────
          case "shuffle":
          case "sh": {
            const newShuffle = !playback?.shuffle_state;
            setPlayback((p) =>
              p ? { ...p, shuffle_state: newShuffle } : p
            );
            await api.player.togglePlaybackShuffle(newShuffle);
            setOutput([
              line(`Shuffle: ${newShuffle ? "On" : "Off"}`, "green"),
            ]);
            break;
          }

          case "repeat":
          case "rp": {
            const cur = playback?.repeat_state ?? "off";
            const next =
              cur === "off"
                ? "context"
                : cur === "context"
                  ? "track"
                  : "off";
            setPlayback((p) =>
              p ? { ...p, repeat_state: next } : p
            );
            await api.player.setRepeatMode(
              next as "track" | "context" | "off"
            );
            setOutput([line(`Repeat: ${next}`, "green")]);
            break;
          }

          // ── seek ──────────────────────────────────────
          case "seek": {
            if (!args) {
              setOutput([line("Usage: seek <m:ss> or seek <seconds>", "yellow")]);
              break;
            }
            const ms = parseSeek(args);
            if (ms === null) {
              setOutput([line("Invalid time format", "red")]);
              break;
            }
            await api.player.seekToPosition(ms);
            anchorRef.current = {
              progressMs: ms,
              timestamp: Date.now(),
              isPlaying: playback?.is_playing ?? false,
            };
            setDisplayProgressMs(ms);
            setOutput([line(`Seeked to ${formatTime(ms)}`, "green")]);
            break;
          }

          // ── search ────────────────────────────────────
          case "search":
          case "s": {
            if (!args) {
              setOutput([line("Usage: search <query>", "yellow")]);
              break;
            }
            const results = await api.search(
              args,
              ["track"],
              undefined,
              10
            );
            const tracks = results.tracks.items;
            searchResultsRef.current = tracks;
            for (const t of tracks) cache.add(t);

            if (tracks.length === 0) {
              setOutput([line(`No results for "${args}"`, "yellow")]);
            } else {
              const lines: OutputLine[] = [
                line(`Search results for "${args}":`, "cyan"),
              ];
              tracks.forEach((t, i) => {
                const artists = t.artists
                  .map((a) => a.name)
                  .join(", ");
                lines.push(
                  line(
                    `  ${i + 1}. ${t.name} - ${artists} (${t.album.name})`,
                    "white"
                  )
                );
              });
              lines.push(
                line(
                  'Use "play <n>" to play or "add <n>" to queue',
                  "gray"
                )
              );
              setOutput(lines);
            }
            break;
          }

          // ── queue ─────────────────────────────────────
          case "queue": {
            const q = await api.player.getUsersQueue();
            const items = q.queue.slice(0, 10);
            if (items.length === 0) {
              setOutput([line("Queue is empty", "yellow")]);
            } else {
              const lines: OutputLine[] = [line("Up next:", "cyan")];
              items.forEach((item, i) => {
                if (isTrack(item)) {
                  cache.add(item);
                  lines.push(
                    line(
                      `  ${i + 1}. ${item.name} - ${item.artists.map((a) => a.name).join(", ")}`,
                      "white"
                    )
                  );
                } else {
                  lines.push(
                    line(`  ${i + 1}. ${item.name}`, "white")
                  );
                }
              });
              setOutput(lines);
            }
            break;
          }

          case "add": {
            const idx = parseInt(args, 10);
            if (
              isNaN(idx) ||
              idx < 1 ||
              idx > searchResultsRef.current.length
            ) {
              setOutput([
                line(
                  `Pick a number 1-${searchResultsRef.current.length || "?"} from search results`,
                  "yellow"
                ),
              ]);
              break;
            }
            const track = searchResultsRef.current[idx - 1]!;
            await api.player.addItemToPlaybackQueue(track.uri);
            setOutput([
              line(
                `Added to queue: ${track.name} - ${track.artists.map((a) => a.name).join(", ")}`,
                "green"
              ),
            ]);
            break;
          }

          // ── playlists ─────────────────────────────────
          case "playlist":
          case "pl": {
            if (!args) {
              const page = await api.currentUser.playlists.playlists(20);
              playlistResultsRef.current = page.items;
              const lines: OutputLine[] = [
                line("Your playlists:", "cyan"),
              ];
              page.items.forEach((pl, i) => {
                lines.push(
                  line(
                    `  ${i + 1}. ${pl.name} (${pl.tracks?.total ?? "?"} tracks)`,
                    "white"
                  )
                );
              });
              lines.push(line('Use "pl <n>" to play', "gray"));
              setOutput(lines);
            } else {
              const idx = parseInt(args, 10);
              if (
                isNaN(idx) ||
                idx < 1 ||
                idx > playlistResultsRef.current.length
              ) {
                setOutput([
                  line(
                    `Pick a number 1-${playlistResultsRef.current.length || "?"}`,
                    "yellow"
                  ),
                ]);
                break;
              }
              const pl = playlistResultsRef.current[idx - 1]!;
              await api.player.startResumePlayback(
                deviceId,
                pl.uri
              );
              setOutput([line(`▶ Playing playlist: ${pl.name}`, "green")]);
              setTimeout(pollPlayback, 800);
            }
            break;
          }

          // ── devices ───────────────────────────────────
          case "devices":
          case "dev": {
            const devResult = await api.player.getAvailableDevices();
            const devs = devResult.devices;
            if (devs.length === 0) {
              setOutput([line("No devices found", "yellow")]);
            } else {
              const lines: OutputLine[] = [line("Devices:", "cyan")];
              devs.forEach((d, i) => {
                lines.push(
                  line(
                    `  ${i + 1}. ${d.name} (${d.type})${d.is_active ? " ●" : ""}`,
                    d.is_active ? "cyan" : "white"
                  )
                );
              });
              lines.push(line('Use "device <n>" to switch', "gray"));
              setOutput(lines);
            }
            break;
          }

          case "device": {
            const devResult2 = await api.player.getAvailableDevices();
            const devs2 = devResult2.devices;
            const dIdx = parseInt(args, 10);
            if (isNaN(dIdx) || dIdx < 1 || dIdx > devs2.length) {
              setOutput([
                line(
                  `Pick a number 1-${devs2.length || "?"}. Run "devices" first.`,
                  "yellow"
                ),
              ]);
              break;
            }
            const target = devs2[dIdx - 1]!;
            if (!target.id) {
              setOutput([line("Device has no ID", "red")]);
              break;
            }
            await api.player.transferPlayback([target.id]);
            setOutput([
              line(`Transferred to: ${target.name}`, "green"),
            ]);
            setTimeout(pollPlayback, 1000);
            break;
          }

          // ── like ──────────────────────────────────────
          case "like":
          case "save": {
            if (!playback?.item) {
              setOutput([line("Nothing playing to save", "yellow")]);
              break;
            }
            await api.currentUser.tracks.saveTracks([playback.item.id]);
            setOutput([line(`Saved: ${playback.item.name}`, "green")]);
            break;
          }

          // ── help ──────────────────────────────────────
          case "help":
          case "?": {
            setOutput([
              line("Commands:", "cyan"),
              line("  play [n|query]     Resume, play search result, or search & play", "white"),
              line("  pause              Pause playback", "white"),
              line("  next, n            Next track", "white"),
              line("  prev, p            Previous track", "white"),
              line("  vol, v [+|-|0-100] Set or adjust volume", "white"),
              line("  seek <m:ss|sec>    Seek to position", "white"),
              line("  search, s <query>  Search for tracks", "white"),
              line("  add <n>            Add search result to queue", "white"),
              line("  queue              Show upcoming queue", "white"),
              line("  playlist, pl [n]   List playlists or play one", "white"),
              line("  devices, dev       List available devices", "white"),
              line("  device <n>         Switch to device", "white"),
              line("  shuffle, sh        Toggle shuffle", "white"),
              line("  repeat, rp         Cycle repeat (off/context/track)", "white"),
              line("  like               Save current track to library", "white"),
              line("  quit               Exit", "white"),
            ]);
            break;
          }

          case "quit":
          case "exit": {
            cache.save();
            exit();
            break;
          }

          default:
            setOutput([
              line(`Unknown command: ${cmd}. Type "help" for commands.`, "yellow"),
            ]);
        }
      } catch (err) {
        const msg =
          err instanceof Error ? err.message : String(err);
        setOutput([line(`Error: ${msg}`, "red")]);
      }
    },
    [api, playback, cache, pollPlayback, exit]
  );

  useInput((char, key) => {
    if (key.ctrl && char === "c") {
      cache.save();
      exit();
      return;
    }

    if (key.return) {
      if (input.trim()) {
        executeCommand(input);
      }
      setInput("");
    } else if (key.backspace || key.delete) {
      setInput((prev) => prev.slice(0, -1));
    } else if (!key.ctrl && !key.meta && !key.escape && !key.tab) {
      setInput((prev) => prev + char);
    }
  });

  // ── render ──────────────────────────────────────────────

  const item = playback?.item;
  let trackName = "";
  let trackArtists = "";
  let trackAlbum = "";
  let durationMs = 0;

  if (item) {
    trackName = item.name;
    durationMs = item.duration_ms;
    if (isTrack(item)) {
      trackArtists = item.artists.map((a) => a.name).join(", ");
      trackAlbum = item.album.name;
    } else {
      trackArtists = item.show?.name ?? "Podcast";
    }
  }

  const ratio =
    durationMs > 0
      ? Math.min(displayProgressMs / durationMs, 1)
      : 0;
  const filled = Math.round(ratio * PROGRESS_BAR_WIDTH);
  const empty = PROGRESS_BAR_WIDTH - filled;

  return (
    <Box flexDirection="column" paddingX={1}>
      <Text color="green" bold>
        ♫ Spotify
      </Text>
      <Text color="green">{"─".repeat(44)}</Text>

      {!playback || !item ? (
        <Box marginY={0}>
          <Text color="gray">Nothing playing</Text>
        </Box>
      ) : (
        <Box flexDirection="column">
          <Text>
            <Text color="white" bold>
              {trackName}
            </Text>
            <Text color="gray"> - </Text>
            <Text color="cyan">{trackArtists}</Text>
            {trackAlbum ? (
              <Text color="gray"> ({trackAlbum})</Text>
            ) : null}
          </Text>
          <Text>
            <Text color="green">{"█".repeat(filled)}</Text>
            <Text color="gray">{"░".repeat(empty)}</Text>
            <Text>
              {" "}
              {formatTime(displayProgressMs)} / {formatTime(durationMs)}
            </Text>
          </Text>
          <Text>
            <Text color={playback.is_playing ? "green" : "yellow"}>
              {playback.is_playing ? "▶" : "⏸"}
            </Text>
            <Text color="gray"> │ </Text>
            <Text>Vol: {playback.device?.volume_percent ?? "?"}%</Text>
            <Text color="gray"> │ </Text>
            <Text color={playback.shuffle_state ? "green" : "gray"}>
              Shfl: {playback.shuffle_state ? "On" : "Off"}
            </Text>
            <Text color="gray"> │ </Text>
            <Text
              color={playback.repeat_state !== "off" ? "green" : "gray"}
            >
              Rpt: {playback.repeat_state}
            </Text>
            <Text color="gray"> │ </Text>
            <Text color="gray">{playback.device?.name ?? ""}</Text>
          </Text>
        </Box>
      )}

      <Text color="green">{"─".repeat(44)}</Text>

      {output.length > 0 && (
        <Box flexDirection="column" marginBottom={0}>
          {output.map((l, i) => (
            <Text key={i} color={l.color}>
              {l.text}
            </Text>
          ))}
        </Box>
      )}

      <Box>
        <Text color="green">&gt; </Text>
        <Text>{input}</Text>
        <Text color="gray">█</Text>
      </Box>

      <Text color="gray" dimColor>
        play, pause, next, prev, vol, search, queue, playlist, devices,
        shuffle, repeat, seek, like, help, quit
      </Text>
    </Box>
  );
}
