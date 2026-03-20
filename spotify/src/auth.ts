import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { execSync } from "node:child_process";
import { SpotifyApi } from "@spotify/web-api-ts-sdk";
import type { AccessToken } from "@spotify/web-api-ts-sdk";

const TOKEN_PATH = path.join(process.cwd(), ".spotify-token.json");

const SCOPES = [
  "user-read-playback-state",
  "user-modify-playback-state",
  "user-read-currently-playing",
  "user-read-recently-played",
  "playlist-read-private",
  "playlist-read-collaborative",
  "user-library-read",
  "user-library-modify",
];

interface StoredToken {
  access_token: string;
  refresh_token: string;
  expires_at: number;
}

function getEnv() {
  const clientId = process.env.SPOTIPY_CLIENT_ID;
  const clientSecret = process.env.SPOTIPY_CLIENT_SECRET;
  const redirectUri = process.env.SPOTIPY_REDIRECT_URI;

  if (!clientId || !clientSecret || !redirectUri) {
    throw new Error(
      "Missing environment variables. Set SPOTIPY_CLIENT_ID, SPOTIPY_CLIENT_SECRET, and SPOTIPY_REDIRECT_URI in .env"
    );
  }

  return { clientId, clientSecret, redirectUri };
}

export async function authenticate(): Promise<SpotifyApi> {
  const { clientId, clientSecret, redirectUri } = getEnv();

  let stored: StoredToken;

  if (fs.existsSync(TOKEN_PATH)) {
    stored = JSON.parse(fs.readFileSync(TOKEN_PATH, "utf-8")) as StoredToken;

    if (Date.now() >= stored.expires_at - 60_000) {
      console.log("Refreshing access token...");
      stored = await refreshAccessToken(clientId, clientSecret, stored.refresh_token);
    }
  } else {
    stored = await doAuthFlow(clientId, clientSecret, redirectUri);
  }

  const accessToken: AccessToken = {
    access_token: stored.access_token,
    token_type: "Bearer",
    expires_in: Math.floor((stored.expires_at - Date.now()) / 1000),
    refresh_token: stored.refresh_token,
  };

  return SpotifyApi.withAccessToken(clientId, accessToken, {
    deserializer: {
      async deserialize<T>(response: Response): Promise<T> {
        const text = await response.text();
        if (!text) return null as T;
        try {
          return JSON.parse(text) as T;
        } catch {
          return null as T;
        }
      },
    },
  });
}

async function doAuthFlow(
  clientId: string,
  clientSecret: string,
  redirectUri: string
): Promise<StoredToken> {
  const authUrl = new URL("https://accounts.spotify.com/authorize");
  authUrl.searchParams.set("client_id", clientId);
  authUrl.searchParams.set("response_type", "code");
  authUrl.searchParams.set("redirect_uri", redirectUri);
  authUrl.searchParams.set("scope", SCOPES.join(" "));

  console.log("Opening browser for Spotify authorization...");
  execSync(`open "${authUrl.toString()}"`);

  const code = await waitForCallback(redirectUri);
  return exchangeCode(clientId, clientSecret, redirectUri, code);
}

function waitForCallback(redirectUri: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const url = new URL(redirectUri);
    const server = http.createServer((req, res) => {
      const reqUrl = new URL(req.url!, `http://${req.headers.host}`);
      const code = reqUrl.searchParams.get("code");
      const error = reqUrl.searchParams.get("error");

      if (error) {
        res.writeHead(400, { "Content-Type": "text/html" });
        res.end(`<h1>Authorization failed</h1><p>${error}</p>`);
        server.close();
        reject(new Error(`Authorization denied: ${error}`));
        return;
      }

      if (code) {
        res.writeHead(200, { "Content-Type": "text/html" });
        res.end(
          "<h1>Authorization successful!</h1><p>You can close this tab and return to the terminal.</p>"
        );
        server.close();
        resolve(code);
      }
    });

    server.listen(parseInt(url.port), url.hostname);
  });
}

async function exchangeCode(
  clientId: string,
  clientSecret: string,
  redirectUri: string,
  code: string
): Promise<StoredToken> {
  const resp = await fetch("https://accounts.spotify.com/api/token", {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
      Authorization: `Basic ${Buffer.from(`${clientId}:${clientSecret}`).toString("base64")}`,
    },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      code,
      redirect_uri: redirectUri,
    }),
  });

  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`Token exchange failed (${resp.status}): ${text}`);
  }

  const data = (await resp.json()) as {
    access_token: string;
    refresh_token: string;
    expires_in: number;
  };

  const stored: StoredToken = {
    access_token: data.access_token,
    refresh_token: data.refresh_token,
    expires_at: Date.now() + data.expires_in * 1000,
  };

  fs.writeFileSync(TOKEN_PATH, JSON.stringify(stored, null, 2));
  return stored;
}

async function refreshAccessToken(
  clientId: string,
  clientSecret: string,
  refreshToken: string
): Promise<StoredToken> {
  const resp = await fetch("https://accounts.spotify.com/api/token", {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
      Authorization: `Basic ${Buffer.from(`${clientId}:${clientSecret}`).toString("base64")}`,
    },
    body: new URLSearchParams({
      grant_type: "refresh_token",
      refresh_token: refreshToken,
    }),
  });

  if (!resp.ok) {
    if (fs.existsSync(TOKEN_PATH)) fs.unlinkSync(TOKEN_PATH);
    throw new Error(
      `Token refresh failed (${resp.status}). Deleted cached token — restart to re-authenticate.`
    );
  }

  const data = (await resp.json()) as {
    access_token: string;
    refresh_token?: string;
    expires_in: number;
  };

  const stored: StoredToken = {
    access_token: data.access_token,
    refresh_token: data.refresh_token ?? refreshToken,
    expires_at: Date.now() + data.expires_in * 1000,
  };

  fs.writeFileSync(TOKEN_PATH, JSON.stringify(stored, null, 2));
  return stored;
}
