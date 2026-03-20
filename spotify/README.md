# Spotify CLI

A terminal-based Spotify controller built with TypeScript, React, Ink, and the Spotify Web API TS SDK.

## Setup

1. Create a Spotify app at https://developer.spotify.com/dashboard
2. Set the redirect URI to `http://127.0.0.1:8888/callback`
3. Copy `.env.sample` to `.env` and fill in your credentials:

```
SPOTIPY_CLIENT_ID=your_client_id
SPOTIPY_CLIENT_SECRET=your_client_secret
SPOTIPY_REDIRECT_URI=http://127.0.0.1:8888/callback
```

4. Install dependencies and run:

```bash
npm install
npm start
```

On first run, your browser will open for Spotify OAuth. After authorizing, tokens are cached in `.spotify-token.json` and automatically refreshed on subsequent runs.

## Usage

The CLI shows your current playback at the top and accepts commands via a `>` prompt.

```
♫ Spotify
────────────────────────────────────────────
Bohemian Rhapsody - Queen (A Night at the Opera)
████████████░░░░░░░░░  2:34 / 5:55
▶ │ Vol: 65% │ Shfl: Off │ Rpt: off │ MacBook Pro
────────────────────────────────────────────
> _
```

### Commands

| Command              | Description                                        |
| -------------------- | -------------------------------------------------- |
| `play`               | Resume playback                                    |
| `play <query>`       | Search (cache first, then API) and play top result |
| `play <n>`           | Play search result N                               |
| `pause`              | Pause playback                                     |
| `next`, `n`          | Skip to next track                                 |
| `prev`, `p`          | Skip to previous track                             |
| `vol [+\|-\|0-100]`  | Set or adjust volume                               |
| `search <query>`     | Search for tracks (aliased as `s`)                 |
| `add <n>`            | Add search result N to queue                       |
| `queue`              | Show upcoming queue                                |
| `playlist`, `pl`     | List your playlists                                |
| `pl <n>`             | Play playlist N                                    |
| `devices`, `dev`     | List available devices                             |
| `device <n>`         | Switch playback to device N                        |
| `shuffle`, `sh`      | Toggle shuffle                                     |
| `repeat`, `rp`       | Cycle repeat mode (off → context → track)          |
| `seek <m:ss\|sec>`   | Seek to position                                   |
| `like`               | Save current track to your library                 |
| `help`               | Show all commands                                  |
| `quit`               | Exit the CLI                                       |

### Track Cache

Every track encountered (from playback, search results, queue) is stored in an LRU cache (`.spotify-cache.json`, up to 500 entries). When you run `play <name>`, the cache is checked first for an instant match before hitting the Spotify API.

### Re-authentication

If you add new OAuth scopes or your refresh token expires, delete `.spotify-token.json` and restart to re-authenticate.
