import { defineConfig } from "tsup";

export default defineConfig({
  entry: ["src/cli.ts"],
  format: ["esm"],
  target: "node18",
  platform: "node",
  outDir: "dist",
  clean: true,
  sourcemap: true,
  // Keep dependencies external. tsup's ESM bundler chokes on CJS deps
  // that do dynamic `require("events")` (commander), and bundling the
  // MCP SDK is fragile because of its internal `node:` imports. npm /
  // pnpm / npx will resolve everything via package.json `dependencies`
  // at install time — that's the whole reason we declare them there.
  external: [
    "@modelcontextprotocol/sdk",
    "commander",
    "picocolors",
    "zod",
  ],
  // First line of dist/cli.js gets a shebang so it's directly executable
  // when symlinked via the `bin` field.
  banner: {
    js: "#!/usr/bin/env node",
  },
  shims: false,
  dts: false,
  splitting: false,
});
