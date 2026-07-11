# S-Chess Puzzle Suggestions Worker

Small Cloudflare Worker + D1 endpoint for collecting user-suggested puzzle FENs without requiring GitHub login.

## Endpoints

- `GET /health` returns `{ "ok": true }`.
- `POST /suggestions` accepts JSON:

```json
{
  "fen": "6n1/6kp/6p1/8/1e6/5K1P/1pr3P1/3E4[] w - - 0 56",
  "notes": "Optional solution idea or source",
  "page": "https://schesspuzzles.com/#...",
  "website": ""
}
```

`website` is a honeypot field. Real users should leave it empty.

## Setup

Install Node.js first. Wrangler requires Node.js 16.17.0 or later; using the current LTS is simplest.

```powershell
cd cloudflare\suggestions-worker
npx wrangler login
npx wrangler d1 create schess-puzzle-suggestions
```

Copy the returned `database_id` into `wrangler.toml`.

Initialize the remote database:

```powershell
npx wrangler d1 execute schess-puzzle-suggestions --remote --file=./schema/schema.sql
```

Set a private salt for hashed IP rate limiting:

```powershell
npx wrangler secret put RATE_LIMIT_SALT
```

Deploy:

```powershell
npx wrangler deploy
```

## Read Suggestions

```powershell
npx wrangler d1 execute schess-puzzle-suggestions --remote --command "SELECT id, created_at, status, fen, notes, page_url FROM suggestions ORDER BY created_at DESC LIMIT 50"
```

Mark reviewed suggestions manually from the D1 console or with:

```powershell
npx wrangler d1 execute schess-puzzle-suggestions --remote --command "UPDATE suggestions SET status = 'accepted' WHERE id = 1"
```

## Review Workflow

1. Query new suggestions:

```powershell
$env:Path = "D:\Program Files\nodejs;$env:Path"
& "D:\Program Files\nodejs\npx.cmd" wrangler d1 execute schess-puzzle-suggestions --remote --command "SELECT id, created_at, status, fen, notes, page_url FROM suggestions WHERE status = 'new' ORDER BY created_at ASC LIMIT 20"
```

2. Run the suggested FEN through the local high-depth pipeline, using `user_suggestion_d1_<id>` as source.
3. If accepted, explicitly combine its generated report into the public dataset and export the website.
4. Mark the row:

```powershell
& "D:\Program Files\nodejs\npx.cmd" wrangler d1 execute schess-puzzle-suggestions --remote --command "UPDATE suggestions SET status = 'accepted' WHERE id = 3"
```

Use `rejected` for suggestions that fail engine verification or are not suitable as puzzles.