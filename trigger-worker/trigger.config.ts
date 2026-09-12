import { defineConfig } from "@trigger.dev/sdk/v3";

export default defineConfig({
  // Your project ref from https://cloud.trigger.dev -> project -> Settings
  project: process.env.TRIGGER_PROJECT_REF ?? "proj_xxxxx",
  dirs: ["./trigger"],
  maxDuration: 120,
  retries: {enabledInDev: true, default: {maxAttempts: 10, minTimeoutInMs: 1000, maxTimeoutInMs: 60000, factor: 2, randomize: true}},
});