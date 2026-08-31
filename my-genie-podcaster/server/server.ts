import { createApp, server, lakebase } from '@databricks/appkit';
import { registerRoutes } from './routes';
import { initSchema, setDb } from './db';
import { failInterruptedPodcasts } from './storage';
import { warmUp } from './tts';

createApp({
  // `lakebase` = durable Postgres for podcasts/segments/preferences.
  // Narration audio is stored in a UC Volume via the SDK Files API using the
  // app service principal (see audio-store.ts) — intentionally not the
  // `files()` plugin, which would expose public /api/files routes over it.
  plugins: [server(), lakebase()],
  async onPluginsReady(appkit) {
    // Wire the storage layer to the plugin-managed Lakebase pool.
    setDb(appkit.lakebase.query);

    // Ensure the schema exists before we start serving requests.
    await initSchema();

    // Generation runs in-process and can't survive a restart — fail any
    // podcasts left mid-generation so the UI stops polling them forever.
    const fixed = await failInterruptedPodcasts();
    if (fixed > 0) console.log(`[startup] marked ${fixed} interrupted podcast(s) as errored`);

    // Register the podcast REST API before the server starts listening.
    appkit.server.extend((app) => registerRoutes(app));

    // Warm the TTS model so the first synthesis isn't cold.
    warmUp();
  },
}).catch(console.error);
