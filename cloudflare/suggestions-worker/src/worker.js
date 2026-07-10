const ALLOWED_ORIGINS = new Set([
  "https://schesspuzzles.com",
  "https://www.schesspuzzles.com",
  "http://localhost:8000",
  "http://127.0.0.1:8000",
  "http://localhost:8765",
  "http://127.0.0.1:8765",
]);

const MAX_FEN_LENGTH = 220;
const MAX_NOTES_LENGTH = 1200;
const MAX_PAGE_URL_LENGTH = 500;
const RATE_LIMIT_WINDOW_MS = 10 * 60 * 1000;
const RATE_LIMIT_MAX = 8;

export default {
  async fetch(request, env) {
    const origin = request.headers.get("Origin") || "";

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders(origin) });
    }

    const url = new URL(request.url);
    if (url.pathname === "/health" && request.method === "GET") {
      return json({ ok: true }, 200, origin);
    }

    if (url.pathname === "/suggestions" && request.method === "POST") {
      return handleSuggestion(request, env, origin);
    }

    return json({ error: "not_found" }, 404, origin);
  },
};

async function handleSuggestion(request, env, origin) {
  if (!ALLOWED_ORIGINS.has(origin)) {
    return json({ error: "origin_not_allowed" }, 403, origin);
  }

  const contentType = request.headers.get("Content-Type") || "";
  if (!contentType.toLowerCase().includes("application/json")) {
    return json({ error: "expected_json" }, 415, origin);
  }

  let body;
  try {
    body = await request.json();
  } catch {
    return json({ error: "invalid_json" }, 400, origin);
  }

  const fen = normalizeText(body.fen, MAX_FEN_LENGTH);
  const notes = normalizeText(body.notes, MAX_NOTES_LENGTH);
  const pageUrl = normalizeText(body.page, MAX_PAGE_URL_LENGTH);
  const trap = normalizeText(body.website || "", 80);

  if (trap) return json({ ok: true }, 202, origin);
  if (!looksLikeSeirawanFen(fen)) return json({ error: "invalid_fen" }, 400, origin);

  const ipHash = await hashIp(request.headers.get("CF-Connecting-IP") || "unknown", env.RATE_LIMIT_SALT || "dev-salt");
  const since = new Date(Date.now() - RATE_LIMIT_WINDOW_MS).toISOString();
  const recent = await env.DB.prepare(
    "SELECT COUNT(*) AS count FROM suggestions WHERE ip_hash = ? AND created_at >= ?"
  ).bind(ipHash, since).first();
  if ((recent?.count || 0) >= RATE_LIMIT_MAX) {
    return json({ error: "rate_limited" }, 429, origin);
  }

  const userAgent = normalizeText(request.headers.get("User-Agent") || "", 300);
  const result = await env.DB.prepare(
    "INSERT INTO suggestions (fen, notes, page_url, user_agent, ip_hash) VALUES (?, ?, ?, ?, ?) RETURNING id, created_at"
  ).bind(fen, notes, pageUrl, userAgent, ipHash).first();

  return json({ ok: true, id: result?.id, created_at: result?.created_at }, 201, origin);
}

function normalizeText(value, maxLength) {
  return String(value || "").replace(/[\u0000-\u001F\u007F]/g, " ").trim().slice(0, maxLength);
}

function looksLikeSeirawanFen(fen) {
  const fields = fen.split(/\s+/);
  if (fields.length < 6) return false;
  if (!fields[0].includes("/")) return false;
  if (!/^[wb]$/.test(fields[1])) return false;
  if (fen.length > MAX_FEN_LENGTH) return false;
  return /^[A-Za-z0-9/\[\]_\-\s]+$/.test(fen);
}

async function hashIp(ip, salt) {
  const data = new TextEncoder().encode(`${salt}:${ip}`);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function json(payload, status, origin) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      ...corsHeaders(origin),
    },
  });
}

function corsHeaders(origin) {
  const allowedOrigin = ALLOWED_ORIGINS.has(origin) ? origin : "https://schesspuzzles.com";
  return {
    "Access-Control-Allow-Origin": allowedOrigin,
    "Access-Control-Allow-Methods": "POST, OPTIONS, GET",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
    "Vary": "Origin",
  };
}
