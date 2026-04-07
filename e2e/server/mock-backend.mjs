/**
 * Minimal HTTP + WebSocket server for Playwright E2E (mirrors FastAPI static + /status + /ws/chat).
 */
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { WebSocketServer } from "ws";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.join(__dirname, "..", "..");
const STATIC_ROOT = path.join(REPO_ROOT, "static");
const PORT = Number.parseInt(process.env.E2E_MOCK_PORT || "4173", 10);

/** @type {object | null} */
let lastQuery = null;

/** @type {number | null} */
let statusFailedOverride = null;

function mimeFor(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  if (ext === ".html") return "text/html; charset=utf-8";
  if (ext === ".js") return "text/javascript; charset=utf-8";
  if (ext === ".css") return "text/css; charset=utf-8";
  return "application/octet-stream";
}

function sendJson(res, status, body) {
  const data = typeof body === "string" ? body : JSON.stringify(body);
  res.writeHead(status, { "Content-Type": "application/json; charset=utf-8" });
  res.end(data);
}

function sendFile(res, relativeUrl) {
  const safePath = relativeUrl === "/" ? "/index.html" : relativeUrl;
  const filePath = path.join(STATIC_ROOT, safePath);
  if (!filePath.startsWith(STATIC_ROOT) || !fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) {
    res.writeHead(404);
    res.end("Not found");
    return;
  }
  res.writeHead(200, { "Content-Type": mimeFor(filePath) });
  fs.createReadStream(filePath).pipe(res);
}

const wss = new WebSocketServer({ noServer: true });

wss.on("connection", (ws) => {
  ws.on("message", async (raw) => {
    let data;
    try {
      data = JSON.parse(raw.toString());
    } catch {
      return;
    }
    if (data.type !== "query") return;
    lastQuery = data;

    const q = data.query ?? "";
    if (q.includes("__WS_ERROR__")) {
      ws.send(JSON.stringify({ type: "error", message: "Mock WebSocket failure" }));
      return;
    }

    const tokens = q.includes("__SLOW_TOKENS__") ? ["One", " ", "Two", " ", "Three"] : ["Hello", " ", "Darovi"];
    const slow = q.includes("__SLOW_TOKENS__");
    for (const content of tokens) {
      ws.send(JSON.stringify({ type: "token", content }));
      if (slow) {
        await new Promise((resolve) => setTimeout(resolve, 120));
      }
    }

    const sources =
      q.includes("__NO_SOURCES__") || q.includes("__WS_ERROR__")
        ? []
        : [
            {
              source_file_id: "e2e-file-1",
              source_name: "Sample.pdf",
              section_title: "Section A",
              chunk_index: 0,
              text_preview: "Preview text for the source card body",
              score: 0.91,
              document_type: "pdf",
            },
          ];

    await ws.send(
      JSON.stringify({
        type: "done",
        sources,
        conversation_id: data.conversation_id || "mock-conversation-id",
      }),
    );
  });

});

const server = http.createServer((req, res) => {
  const url = new URL(req.url || "/", `http://${req.headers.host || "localhost"}`);

  if (req.method === "GET" && url.pathname === "/__e2e/health") {
    sendJson(res, 200, { ok: true });
    return;
  }
  if (req.method === "GET" && url.pathname === "/__e2e/last-query") {
    sendJson(res, 200, { last: lastQuery });
    return;
  }
  if (req.method === "POST" && url.pathname === "/__e2e/reset") {
    lastQuery = null;
    statusFailedOverride = null;
    res.writeHead(204);
    res.end();
    return;
  }

  if (req.method === "POST" && url.pathname === "/__e2e/status-failed") {
    let body = "";
    req.on("data", (c) => {
      body += c;
    });
    req.on("end", () => {
      try {
        const j = JSON.parse(body || "{}");
        statusFailedOverride = typeof j.failed === "number" ? j.failed : 0;
      } catch {
        statusFailedOverride = 0;
      }
      res.writeHead(204);
      res.end();
    });
    return;
  }

  if (req.method === "GET" && url.pathname === "/status") {
    const fromQuery = Number.parseInt(url.searchParams.get("failed") || "0", 10) || 0;
    const failed = statusFailedOverride !== null ? statusFailedOverride : fromQuery;
    sendJson(res, 200, {
      total_files: 0,
      pending: 0,
      downloaded: 0,
      converted: 0,
      embedded: 0,
      failed,
    });
    return;
  }

  if (req.method === "GET" && url.pathname === "/") {
    sendFile(res, "/");
    return;
  }
  if (req.method === "GET" && (url.pathname === "/app.js" || url.pathname === "/styles.css")) {
    sendFile(res, url.pathname);
    return;
  }

  res.writeHead(404);
  res.end("Not found");
});

server.on("upgrade", (request, socket, head) => {
  const url = new URL(request.url || "/", `http://${request.headers.host || "localhost"}`);
  if (url.pathname === "/ws/chat") {
    wss.handleUpgrade(request, socket, head, (ws) => {
      wss.emit("connection", ws, request);
    });
  } else {
    socket.destroy();
  }
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`E2E mock backend listening on http://127.0.0.1:${PORT}`);
});
