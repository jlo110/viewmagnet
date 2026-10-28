import express from "express";
import { createServer } from "http";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// ---------------------------------------------------------------------------
// Bot-targeted markdown redirect
//
// Research (see the GEO study referenced in the codebase) shows that
// per-page plain-markdown files reliably surface in LLM responses, while
// schema markup and stripped HTML are inconsistent. When a verified AI
// crawler requests an HTML route that has a .md twin in /public, we 302
// it to the markdown version so the bot gets clean prose without React
// shell, nav, or CSS noise.
//
// Human browsers never match this middleware because their User-Agent
// strings don't contain these bot tokens. Adding a new bot is one line.
// ---------------------------------------------------------------------------

const AI_BOT_UA_TOKENS = [
  "GPTBot",
  "ChatGPT-User",
  "ClaudeBot",
  "anthropic-ai",
  "PerplexityBot",
  "Google-Extended",
  "Applebot-Extended",
  "Bytespider",
  "CCBot",
  "YouBot",
  "DataForSeoBot",
  "Meta-ExternalAgent",
  "Amazonbot",
];

// Maps HTML routes → relative public path of their markdown twin.
// Only routes that have an actual .md file in public/ should be listed.
const MD_TWINS: Record<string, string> = {
  "/": "/index.md",
  "/methodology": "/methodology.md",
  "/frameworks": "/frameworks.md",
  "/analyzer-guide": "/analyzer-guide.md",
  "/mcp": "/mcp.md",
  "/docs": "/docs.md",
  "/pricing": "/pricing.md",
  "/faq": "/faq.md",
};

function isAiBot(ua: string): boolean {
  const uaLower = ua.toLowerCase();
  return AI_BOT_UA_TOKENS.some((token) => uaLower.includes(token.toLowerCase()));
}

async function startServer() {
  const app = express();
  const server = createServer(app);

  // Serve static files from dist/public in production
  const staticPath =
    process.env.NODE_ENV === "production"
      ? path.resolve(__dirname, "public")
      : path.resolve(__dirname, "..", "dist", "public");

  app.use(express.static(staticPath));

  // Bot-targeted markdown redirect — must come before the catch-all
  // so verified AI crawlers get /methodology.md instead of index.html.
  app.get("*", (req, res, next) => {
    const ua = req.headers["user-agent"] ?? "";
    const mdPath = MD_TWINS[req.path];

    if (mdPath && isAiBot(ua)) {
      // 302 (not 301) so humans still hit the React app if the UA
      // heuristic ever misfires — we don't want to permanently cache
      // a redirect that bypasses the SPA for human traffic.
      res.redirect(302, mdPath);
      return;
    }

    next();
  });

  // Handle client-side routing - serve index.html for all routes
  app.get("*", (_req, res) => {
    res.sendFile(path.join(staticPath, "index.html"));
  });

  const port = process.env.PORT || 3000;

  server.listen(port, () => {
    console.log(`Server running on http://localhost:${port}/`);
  });
}

startServer().catch(console.error);
