# Cloudflare D1 Edge Deployment

Optional edge-hosted mirror of the local file-organization graph. The canonical
store is the local SQLite database (`results/file_organization.db`) accessed via
`src/storage/graph_store.py`; D1 hosts a copy behind a Cloudflare Worker so
edge/JavaScript consumers can query it globally.

> **No Python HTTP client.** The Python application always uses the local
> `GraphStore` (SQLite). The former `GraphStoreHTTP` adapter was removed
> (commit `f347d29`); Python's only relationship to D1 is the one-directional
> export in [Data flow](#data-flow). Consumers of the D1 copy are the Worker API
> and its HTTP callers, not the Python CLI.

---

## Components

| Component | Location | Role |
|-----------|----------|------|
| **D1 database** | `file-organization-db` (Cloudflare) | Managed SQLite at the edge |
| **Worker API** | `workers/file-org-api/` (Hono / TypeScript) | HTTP query layer over D1 |
| **Schema generator** | `scripts/d1/generate_schema.py` | Emits `schema.sql` from the ORM |
| **Schema DDL** | `scripts/d1/schema.sql` | Auto-generated D1 table + index definitions |
| **Export tool** | `scripts/d1/export_to_d1.py` | SQLite → D1-compatible SQL dump |

### Worker config (`workers/file-org-api/wrangler.toml`)

```toml
name = "file-org-api"
main = "src/index.ts"
compatibility_date = "2025-03-20"
workers_dev = true

[[d1_databases]]
binding = "DB"
database_name = "file-organization-db"
database_id = "ec22b612-34da-48c7-ba44-df91875b296c"

[env.production]
name = "file-org-api-prod"
route = "api.file-org.dev/*"
zone_id = "YOUR_ZONE_ID"  # Update with your domain
```

---

## Schema is generated — do not hand-edit

`scripts/d1/schema.sql` is **auto-generated from `src/storage/models.py`**
(`Base.metadata`). Editing it by hand will be overwritten. To change the D1
schema, edit the ORM models, then regenerate:

```bash
python scripts/d1/generate_schema.py
```

The header of `schema.sql` records this contract. Association tables use
composite primary keys; indexes are emitted alongside the tables.

---

## Data flow

```
Local SQLite (results/file_organization.db)   ← canonical store, written by the Python CLI
        │
        │  python scripts/d1/export_to_d1.py --db-path … --output results/d1_dump.sql
        ▼
results/d1_dump.sql  (D1-compatible SQL)
        │
        │  wrangler d1 execute file-organization-db < results/d1_dump.sql
        ▼
Cloudflare D1  ←── served by ──►  Worker API (workers/file-org-api, Hono/TS)
                                          │
                                          ▼
                                  HTTP / edge consumers
```

Schema is applied to D1 separately from data:

```
scripts/d1/generate_schema.py → scripts/d1/schema.sql
        │
        │  wrangler d1 execute file-organization-db --file scripts/d1/schema.sql
        ▼
Cloudflare D1 (empty tables)
```

---

## Setup

Prerequisites: [Wrangler CLI](https://developers.cloudflare.com/workers/wrangler/)
(`npm install -g wrangler`, then `wrangler login`).

```bash
# 1. (Re)generate the schema from the ORM if models changed
python scripts/d1/generate_schema.py

# 2. Apply the schema to D1
wrangler d1 execute file-organization-db --file scripts/d1/schema.sql

# 3. Export local data to a D1-compatible SQL dump
python scripts/d1/export_to_d1.py \
  --db-path results/file_organization.db \
  --output results/d1_dump.sql

# 4. Load the data into D1
wrangler d1 execute file-organization-db < results/d1_dump.sql

# 5. Deploy the Worker API
cd workers/file-org-api && npm install && wrangler deploy
# → https://file-org-api.<account>.workers.dev
```

Verify tables and row counts:

```bash
wrangler d1 execute file-organization-db "SELECT name FROM sqlite_master WHERE type='table';"
wrangler d1 execute file-organization-db "SELECT COUNT(*) FROM files;"
```

### Local development

```bash
cd workers/file-org-api
npm install
npm run dev          # http://localhost:8787, bound to the D1 database
npm run type-check   # tsc --noEmit
curl http://localhost:8787/health
```

### Production (custom domain)

Set `route`/`zone_id` under `[env.production]` in `wrangler.toml`, then:

```bash
wrangler deploy --env production
```

---

## Worker API

Framework: [Hono](https://hono.dev/). CORS is open (`origin: '*'`). Routes as
defined in `workers/file-org-api/src/index.ts`:

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/health` | Health check (`{status, timestamp}`) |
| `GET`  | `/api/files` | List files (`?status=&limit=&offset=`) |
| `GET`  | `/api/files/:id` | Get a file by ID |
| `POST` | `/api/files` | Create a file |
| `PUT`  | `/api/files/:id/status` | Update file status |
| `GET`  | `/api/categories` | Category hierarchy |
| `POST` | `/api/categories` | Create a category |
| `GET`  | `/api/stats` | Aggregate statistics |
| `GET`  | `/api/search` | Full-text search (`?q=`) |

---

## Operations

### Backup

```bash
wrangler d1 export file-organization-db > backups/d1_$(date +%Y%m%d_%H%M%S).sql
```

Restore by loading a dump back in:

```bash
wrangler d1 execute file-organization-db < backups/d1_20260320_112345.sql
```

### Logs & metrics

```bash
wrangler tail                     # real-time Worker logs
wrangler d1 list                  # confirm the database exists / binding
```

Cloudflare Dashboard → Workers → `file-org-api` → Metrics for requests, errors,
CPU time, and bandwidth.

### Large migrations

D1 rate-limits large executions. Split big dumps:

```bash
split -l 1000 results/d1_dump.sql results/d1_dump_
for f in results/d1_dump_*; do wrangler d1 execute file-organization-db < "$f"; done
```

---

## Limits & cost

| Feature | Free tier | Notes |
|---------|-----------|-------|
| D1 reads | 25k/day | Then $0.75 / million |
| D1 writes | 100k/day | Then $1.50 / million |
| Storage | 5 GB | Included with D1 |
| Worker requests | 100k/day | Included CPU |
| Query result set | 1 MB | Per query |
| Request body | 100 KB | Worker input |

Reads are served from globally distributed replicas; writes go to the primary
(ENAM). See [Cloudflare pricing](https://www.cloudflare.com/pricing/workers/).

---

## Troubleshooting

| Symptom | Check |
|---------|-------|
| Can't reach the API | `wrangler tail`; `curl …/health`; `wrangler d1 list` |
| Worker deploy fails | `npm install` completed; `npm run type-check`; DB `database_id` in `wrangler.toml` |
| Schema drift | Regenerate: `python scripts/d1/generate_schema.py`, re-apply `schema.sql` |
| Migration failed / slow | Verify row counts; split the dump (see above); re-run `export_to_d1.py` |
| Slow queries | Inspect indexes: `SELECT name, sql FROM sqlite_master WHERE type='index'` |

---

## References

- Worker source: `workers/file-org-api/src/index.ts`
- Schema generator: `scripts/d1/generate_schema.py` → `scripts/d1/schema.sql`
- Export tool: `scripts/d1/export_to_d1.py`
- ORM models (schema source of truth): `src/storage/models.py`
- [Cloudflare D1](https://developers.cloudflare.com/d1/) · [Hono](https://hono.dev/) · [Wrangler](https://developers.cloudflare.com/workers/wrangler/)
