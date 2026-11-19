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
const MAX_CONTACT_NAME_LENGTH = 100;
const MAX_CONTACT_EMAIL_LENGTH = 320;
const MAX_CONTACT_MESSAGE_LENGTH = 5000;
const RATE_LIMIT_WINDOW_MS = 10 * 60 * 1000;
const SUGGESTION_RATE_LIMIT_MAX = 8;
const CONTACT_RATE_LIMIT_MAX = 3;

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
    if (url.pathname === "/contact" && request.method === "POST") {
      return handleContact(request, env, origin);
    }

    return json({ error: "not_found" }, 404, origin);
  },
};

async function handleSuggestion(request, env, origin) {
  const body = await requestBody(request, origin);
  if (body instanceof Response) return body;

  const fen = normalizeText(body.fen, MAX_FEN_LENGTH);
  const notes = normalizeText(body.notes, MAX_NOTES_LENGTH);
  const pageUrl = normalizeText(body.page, MAX_PAGE_URL_LENGTH);
  const trap = normalizeText(body.website || "", 80);
  if (trap) return json({ ok: true }, 202, origin);
  if (!looksLikeSeirawanFen(fen)) return json({ error: "invalid_fen" }, 400, origin);

  const ipHash = await rateLimitHash(request, env);
  const limited = await isRateLimited(env.DB, "suggestions", ipHash, SUGGESTION_RATE_LIMIT_MAX);
  if (limited) return json({ error: "rate_limited" }, 429, origin);

  const userAgent = normalizeText(request.headers.get("User-Agent") || "", 300);
  const result = await env.DB.prepare(
    "INSERT INTO suggestions (fen, notes, page_url, user_agent, ip_hash) VALUES (?, ?, ?, ?, ?) RETURNING id, created_at"
  ).bind(fen, notes, pageUrl, userAgent, ipHash).first();

  return json({ ok: true, id: result?.id, created_at: result?.created_at }, 201, origin);
}

async function handleContact(request, env, origin) {
  const body = await requestBody(request, origin);
  if (body instanceof Response) return body;

  const name = normalizeText(body.name, MAX_CONTACT_NAME_LENGTH);
  const email = normalizeText(body.email, MAX_CONTACT_EMAIL_LENGTH).toLowerCase();
  const message = normalizeText(body.message, MAX_CONTACT_MESSAGE_LENGTH);
  const pageUrl = normalizeText(body.page, MAX_PAGE_URL_LENGTH);
  const trap = normalizeText(body.website || "", 80);
  if (trap) return json({ ok: true }, 202, origin);
  if (!name || !looksLikeEmail(email) || message.length < 4) {
    return json({ error: "invalid_contact" }, 400, origin);
  }

  const ipHash = await rateLimitHash(request, env);
  const limited = await isRateLimited(env.DB, "contact_messages", ipHash, CONTACT_RATE_LIMIT_MAX);
  if (limited) return json({ error: "rate_limited" }, 429, origin);

  const userAgent = normalizeText(request.headers.get("User-Agent") || "", 300);
  const result = await env.DB.prepare(
    "INSERT INTO contact_messages (name, email, message, page_url, user_agent, ip_hash) VALUES (?, ?, ?, ?, ?, ?) RETURNING id, created_at"
  ).bind(name, email, message, pageUrl, userAgent, ipHash).first();

  // CONTACT_RECIPIENT is a Worker secret. D1 remains a durable inbox if email
  // delivery has not been configured yet or is temporarily unavailable.
  await notifyContact(env, { id: result?.id, createdAt: result?.created_at, name, email, message, pageUrl });
  return json({ ok: true, id: result?.id, created_at: result?.created_at }, 201, origin);
}

async function requestBody(request, origin) {
  if (!ALLOWED_ORIGINS.has(origin)) {
    return json({ error: "origin_not_allowed" }, 403, origin);
  }
  const contentType = request.headers.get("Content-Type") || "";
  if (!contentType.toLowerCase().includes("application/json")) {
    return json({ error: "expected_json" }, 415, origin);
  }
  try {
    return await request.json();
  } catch {
    return json({ error: "invalid_json" }, 400, origin);
  }
}

async function isRateLimited(db, table, ipHash, maximum) {
  const since = new Date(Date.now() - RATE_LIMIT_WINDOW_MS).toISOString();
  const recent = await db.prepare(
    `SELECT COUNT(*) AS count FROM ${table} WHERE ip_hash = ? AND created_at >= ?`
  ).bind(ipHash, since).first();
  return (recent?.count || 0) >= maximum;
}

async function notifyContact(env, contact) {
  if (!env.EMAIL || !env.CONTACT_RECIPIENT) return;
  const subject = `S-Chess Puzzles contact #${contact.id || "new"}`;
  const text = [
    `From: ${contact.name} <${contact.email}>`,
    `Page: ${contact.pageUrl || "(not supplied)"}`,
    `Received: ${contact.createdAt || new Date().toISOString()}`,
    "",
    contact.message,
  ].join("\n");
  const html = `<p><strong>From:</strong> ${escapeHtml(contact.name)} &lt;${escapeHtml(contact.email)}&gt;</p>`
    + `<p><strong>Page:</strong> ${escapeHtml(contact.pageUrl || "(not supplied)")}</p>`
    + `<p><strong>Received:</strong> ${escapeHtml(contact.createdAt || new Date().toISOString())}</p>`
    + `<hr><p>${escapeHtml(contact.message).replace(/\n/g, "<br>")}</p>`;
  try {
    await env.EMAIL.send({
      to: env.CONTACT_RECIPIENT,
      from: { email: env.CONTACT_FROM || "contact@schesspuzzles.com", name: "S-Chess Puzzles" },
      replyTo: contact.email,
      subject,
      text,
      html,
    });
  } catch (error) {
    console.error("Contact email delivery failed", error?.message || error);
  }
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

function looksLikeEmail(email) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) && email.length <= MAX_CONTACT_EMAIL_LENGTH;
}

async function rateLimitHash(request, env) {
  return hashIp(request.headers.get("CF-Connecting-IP") || "unknown", env.RATE_LIMIT_SALT || "dev-salt");
}

async function hashIp(ip, salt) {
  const data = new TextEncoder().encode(`${salt}:${ip}`);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
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
