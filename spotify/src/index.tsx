import "dotenv/config";
import { render } from "ink";
import { authenticate } from "./auth.js";
import { TrackCache } from "./cache.js";
import App from "./app.js";

async function main() {
  const cache = new TrackCache();
  cache.load();

  try {
    const api = await authenticate();
    render(<App api={api} cache={cache} />);
  } catch (err) {
    console.error(
      "Failed to start:",
      err instanceof Error ? err.message : err
    );
    process.exit(1);
  }
}

main();
