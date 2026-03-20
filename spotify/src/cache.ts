import fs from "node:fs";
import path from "node:path";

const CACHE_PATH = path.join(process.cwd(), ".spotify-cache.json");
const MAX_SIZE = 500;

export interface CachedTrack {
  uri: string;
  id: string;
  name: string;
  artists: string;
  album: string;
}

export class TrackCache {
  private map = new Map<string, CachedTrack>();

  add(track: {
    uri: string;
    id: string;
    name: string;
    artists: { name: string }[];
    album?: { name: string };
  }) {
    const entry: CachedTrack = {
      uri: track.uri,
      id: track.id,
      name: track.name,
      artists: track.artists.map((a) => a.name).join(", "),
      album: track.album?.name ?? "",
    };

    this.map.delete(track.uri);
    this.map.set(track.uri, entry);

    while (this.map.size > MAX_SIZE) {
      const oldest = this.map.keys().next().value;
      if (oldest !== undefined) this.map.delete(oldest);
    }
  }

  search(query: string): CachedTrack[] {
    const q = query.toLowerCase();
    return [...this.map.values()]
      .filter(
        (t) =>
          t.name.toLowerCase().includes(q) ||
          t.artists.toLowerCase().includes(q)
      )
      .slice(0, 10);
  }

  get(uri: string): CachedTrack | undefined {
    return this.map.get(uri);
  }

  format(t: CachedTrack): string {
    return t.album
      ? `${t.name} - ${t.artists} (${t.album})`
      : `${t.name} - ${t.artists}`;
  }

  load() {
    try {
      if (fs.existsSync(CACHE_PATH)) {
        const entries = JSON.parse(
          fs.readFileSync(CACHE_PATH, "utf-8")
        ) as [string, CachedTrack][];
        for (const [key, val] of entries) {
          this.map.set(key, val);
        }
      }
    } catch {
      // ignore corrupt cache
    }
  }

  save() {
    try {
      fs.writeFileSync(
        CACHE_PATH,
        JSON.stringify([...this.map.entries()])
      );
    } catch {
      // ignore save errors
    }
  }
}
