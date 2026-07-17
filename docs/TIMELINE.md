# Timeline Visualization

The timeline interface turns file-organization session data into a visual
narrative — a vertical, chronological story of how the system performed over
time, with color-coded status markers, expandable detail modals, and run-to-run
comparison.

This single doc covers the **design system**, the **component library**, and
**data/integration** (generating data, the JSON schema, serving, automation,
troubleshooting). It supersedes the former `TIMELINE_DESIGN.md`,
`TIMELINE_COMPONENTS.md`, and `TIMELINE_INTEGRATION.md`.

- **Interface:** `_site/timeline.html`
- **Data generator:** `src/api/timeline_api.py` (`TimelineAPI`)
- **CLI:** `organize-files timeline`
- **Generated data:** `_site/timeline_data.json`

---

## Quick Start

```bash
# 1. Generate timeline data (unified CLI — canonical)
organize-files timeline
#    Or the standalone launcher (puts scripts/ on sys.path for shared imports):
#    python3 scripts/generate_timeline_data.py

# 2. Serve _site/ over HTTP (do NOT open the file directly — CORS blocks fetch)
python3 -m http.server 8000 -d _site

# 3. Open the interface
open http://localhost:8000/timeline.html
```

`--db-path` is the only option; it defaults to the shared `DEFAULT_DB_PATH`. The
output path is fixed at `_site/timeline_data.json` (the `OUTPUT_PATH` constant) —
there is no `--output` flag.

**Expected output**:
```
Generating timeline data from results/file_organization.db...
Timeline data saved to _site/timeline_data.json
  - 17 sessions
  - 30133 total files
```

---

## Part 1 — Design

### Design Philosophy

1. **Chronological journey** — a vertical timeline that reads like a story.
2. **Progressive disclosure** — overview cards summarize; modals dive deeper.
3. **Status at a glance** — color-coded markers communicate session health.
4. **Comparative analysis** — easy run-to-run comparison shows improvement.

### Component Architecture

```
Timeline Interface
├── Header (Sticky)
│   ├── Title & Branding
│   └── Aggregate Statistics (3 key metrics)
├── Controls Bar
│   ├── View Toggle (Timeline/List/Stats)
│   ├── Zoom Controls
│   └── Comparison Button
├── Timeline Container
│   ├── Timeline Spine (Vertical gradient line)
│   ├── Session Markers (Interactive points)
│   └── Session Cards (Alternating sides)
└── Modals
    ├── Snapshot Modal (Detailed session view)
    └── Comparison Modal (Side-by-side comparison)
```

### Visual Design System

#### Color Palette (dark theme)

| Variable | Hex | Usage |
|----------|-----|-------|
| `--primary` | `#667eea` | Primary actions, timeline spine |
| `--secondary` | `#764ba2` | Gradients, accents |
| `--accent` | `#f5576c` | Important highlights |
| `--dark-bg` | `#0f1419` | Page background |
| `--dark-surface` | `#1a1f2e` | Card backgrounds |
| `--success` | `#10b981` | Success states |
| `--warning` | `#f59e0b` | Warning states |
| `--danger` | `#ef4444` | Error states |

#### Typography Scale

```
Display:     1.75rem (28px) - Modal titles
Heading:     1.5rem  (24px) - Page title
Subheading:  1rem    (16px) - Section titles
Body:        0.875rem (14px) - Main content
Caption:     0.75rem (12px) - Metadata labels
Micro:       0.7rem  (11.2px) - Badges, codes
```

**Font stack**: `-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif`

#### Spacing (0.25rem / 4px increments)

```
xs: 4px   sm: 8px   md: 16px   lg: 24px   xl: 32px   2xl: 48px
```

#### Border Radius

```
Small: 8px (buttons, metrics)   Medium: 12px (cards, inputs)
Large: 16px (panels)            XLarge: 24px (modals)   Pill: 9999px (badges)
```

### Key UI Layout Notes

- **Timeline spine** — 4px vertical gradient line (`--primary` → `--accent`) with
  a glow; centered on desktop, left-aligned on mobile.
- **Session markers** — status by error count: **success** `< 10`, **warning**
  `10–100`, **error** `> 100`. Hover scales up + pulses; click opens the snapshot
  modal. (Full spec in [Component Library](#part-2--component-library).)
- **Session cards** — alternate sides of the spine (odd = right, even = left);
  all left-aligned on mobile. Hover lifts `-4px`; click opens the modal.
- **Snapshot modal** — primary metrics (3×2 grid), derived metrics (success rate,
  files/sec, cost/file), and a 2-column charts grid; slides in from top.
- **Comparison modal** — two sessions side-by-side with delta indicators, then a
  summary panel.

### Animation System

```css
/* Timeline items — staggered entrance */
animation: fadeInUp 0.6s ease forwards;
animation-delay: calc(var(--index) * 0.1s);

/* Modal — slide in from top with scale */
animation: modalSlideIn 0.4s ease;
```

- Hover transitions: `0.3s` on all properties.
- Button presses: `0.2s` with `scale(0.98)`.
- Progress bars: `0.6s ease` on width.
- Micro-animations: `pulse` (marker hover), `spin` (loading spinner).

### Responsive Design

| Breakpoint | Range | Layout |
|------------|-------|--------|
| Desktop | `> 1024px` | Default (alternating cards) |
| Tablet | `640–1024px` | Spine → left; all cards right; adjusted grid |
| Mobile | `< 640px` | Single-column grids; stacked header/modals |

```css
@media (max-width: 1024px) {
    .timeline-spine { left: 20px; }
    .timeline-item:nth-child(odd) .timeline-content,
    .timeline-item:nth-child(even) .timeline-content {
        margin-left: 3rem;
        margin-right: 0;
    }
    .timeline-content::before {
        left: -24px !important;
        border-right-color: var(--dark-border) !important;
        border-left-color: transparent !important;
    }
}

@media (max-width: 640px) {
    .metrics-grid, .charts-grid { grid-template-columns: 1fr; }
}
```

### Accessibility

- **Contrast** — meets WCAG AA (primary text 13.5:1, secondary 7.2:1, buttons 4.5:1+).
- **Keyboard** — `Escape` closes modals; `Tab` navigates; `Enter`/`Space` activates.
- **Screen readers** — semantic HTML, ARIA labels, status announcements.
- **Motion** — respect `prefers-reduced-motion`; all animation is decorative.

```css
@media (prefers-reduced-motion: reduce) {
    * { animation: none !important; transition: none !important; }
}
```

### Performance

- Hardware-accelerated transforms (`translateY`, `scale`); `will-change` hints.
- Debounced scroll handlers; lazy loading and virtual scrolling for 100+ sessions.
- No images required — pure CSS/SVG.

---

## Part 2 — Component Library

Reusable UI components and patterns. Each entry gives HTML structure + visual
specs; see `_site/timeline.html` for the canonical CSS.

### 1. Session Marker

Interactive point indicating session status.

```html
<div class="timeline-marker success"></div>  <!-- < 10 errors -->
<div class="timeline-marker warning"></div>  <!-- 10-100 errors -->
<div class="timeline-marker error"></div>    <!-- > 100 errors -->
```

- Size: 20px (resting) → 28px (hover); 4px border; centered on spine; pulse on hover.

```css
.timeline-marker {
    width: 20px; height: 20px;
    background: var(--primary);
    border: 4px solid var(--dark-surface);
    border-radius: 50%;
    cursor: pointer;
    transition: all 0.3s;
}
.timeline-marker:hover {
    width: 28px; height: 28px;
    box-shadow: 0 0 20px var(--glow-primary);
    animation: pulse 1.5s infinite;
}
```

### 2. Metric Card

Single KPI. Variants: default (primary), success (green), warning (orange),
danger (red).

```html
<div class="metric">
    <div class="metric-label">Total Files</div>
    <div class="metric-value">1,234</div>
    <div class="progress-bar"><div class="progress-fill" style="width: 85%"></div></div>
</div>
```

- Background: dark card; padding `0.75rem`; 1px border; radius `0.5rem`.

### 3. Progress Bar

```html
<div class="progress-bar" role="progressbar"
     aria-valuenow="75" aria-valuemin="0" aria-valuemax="100">
    <div class="progress-fill" style="width: 75%"></div>
</div>
```

- Height 6px; dark background; gradient fill (`--primary` → `--accent`); radius 3px;
  `width 0.6s ease`.

### 4. Category Tag

```html
<div class="category-tags">
    <div class="category-tag">GameAssets <span class="category-count">800</span></div>
    <div class="category-tag">Photos <span class="category-count">120</span></div>
</div>
```

- Pill shape; dark background; count badge = primary bg / white text; font `0.75rem`.

### 5. Session Badge

Run type (dry-run vs live).

```html
<span class="session-badge dry-run">Dry Run</span>  <!-- orange @ 20% -->
<span class="session-badge live">Live</span>        <!-- green @ 20% -->
```

- Small caps; letter-spacing `0.05em`; padding `0.25rem 0.75rem`; font `0.7rem` / 700.

### 6. Timeline Content Card

Container for a session summary; has a triangular pointer toward the spine.

```html
<div class="timeline-content">
    <div class="session-header">
        <div>
            <div class="session-date">Dec 10, 2025 at 10:30 AM</div>
            <div class="session-id">session-uuid</div>
        </div>
        <span class="session-badge live">Live</span>
    </div>
    <div class="metrics-grid"><!-- 4 metric cards --></div>
    <div class="progress-bar"><div class="progress-fill" style="width: 98%"></div></div>
    <div class="category-tags"><!-- category tags --></div>
</div>
```

- Resting → hover: border → primary, lifts 4px. Click → snapshot modal.
- Odd items point left; even items point right; mobile all point left.

### 7. Button System

```html
<button class="btn btn-primary">Compare Runs</button>
<button class="btn btn-secondary">Export Data</button>
```

- Padding `0.75rem 1.5rem`; radius `0.5rem`; font `0.875rem` / 600; `transition: all 0.3s`.
- Primary hover: bg → `--secondary` + glow. Secondary hover: border → primary.

### 8. Modal Container

```html
<div class="modal-overlay" id="modalId">
    <div class="snapshot-modal">
        <div class="modal-header">
            <div>
                <div class="modal-title">Session Details</div>
                <div class="session-date">December 10, 2025</div>
            </div>
            <button class="close-btn">&times;</button>
        </div>
        <div class="modal-body"><!-- content --></div>
    </div>
</div>
```

```javascript
document.getElementById('modalId').classList.add('active');     // open
document.getElementById('modalId').classList.remove('active');  // close
modal.addEventListener('click', (e) => {                        // close on overlay
    if (e.target === modal) modal.classList.remove('active');
});
```

### 9. Diff Indicator

```html
<span class="diff-indicator positive">↑ 120</span>
<span class="diff-indicator negative">↓ 15</span>
```

- Font `0.75rem` / 700; inline-flex, gap `0.25rem`; green (positive) / red (negative).

### 10. Loading Spinner

```html
<div class="loading-container">
    <div class="loading-spinner"></div>
    <div class="loading-text">Loading organization history...</div>
</div>
```

- 64px; 4px border with primary `border-top`; `spin 1s linear infinite`.

### 11. Empty State

```html
<div class="empty-state">
    <div class="empty-state-icon">📊</div>
    <h2>No sessions found</h2>
    <p>Run the file organizer to see your timeline</p>
    <button class="btn btn-primary">Run Organizer</button>
</div>
```

- Center-aligned; padding `4rem`; icon `4rem` @ opacity `0.5`.

### 12. Chart Card

```html
<div class="chart-card">
    <div class="chart-title">Top Categories</div>
    <div>
        <div style="margin-bottom: 0.75rem;">
            <div style="display: flex; justify-content: space-between; margin-bottom: 0.25rem;">
                <span style="font-size: 0.875rem;">GameAssets</span>
                <span style="font-weight: 700;">84.8%</span>
            </div>
            <div class="progress-bar"><div class="progress-fill" style="width: 84.8%"></div></div>
        </div>
    </div>
</div>
```

### 13. View Toggle

```html
<div class="view-toggle">
    <button class="active" onclick="switchView('timeline')">Timeline View</button>
    <button onclick="switchView('list')">List View</button>
    <button onclick="switchView('stats')">Statistics</button>
</div>
```

- Container: dark card, `0.25rem` padding. Active button: primary bg + glow.

### 14. Zoom Controls

```html
<div class="zoom-controls">
    <button class="zoom-btn" onclick="adjustZoom(-1)">−</button>
    <span class="zoom-level">100%</span>
    <button class="zoom-btn" onclick="adjustZoom(1)">+</button>
</div>
```

```javascript
let zoomLevel = 100;
function adjustZoom(direction) {
    zoomLevel = Math.max(50, Math.min(200, zoomLevel + direction * 10));
    document.getElementById('zoomLevel').textContent = zoomLevel + '%';
    document.getElementById('timelineItems').style.transform = `scale(${zoomLevel / 100})`;
}
```

### Composition Patterns

- **Metrics grid** — 2–4 related metrics; 4 cols (desktop) → 2 (tablet) → 1 (mobile).
- **Comparison layout** — two `comparison-card`s split by a `→ vs` arrow; the right
  card carries diff indicators.
- **Timeline item** — `timeline-marker` + `timeline-content`; odd right / even left,
  mobile all right.

### Utility Classes

```css
/* Spacing */ .mt-1/.mt-2/.mt-4  .mb-1/.mb-2/.mb-4
/* Text color */ .text-primary .text-secondary .text-success .text-warning .text-danger
/* Type */ .font-bold .font-semibold .text-xs .text-sm .text-base .text-lg
```

### Customization

```css
/* Recolor: edit :root variables */
:root { --primary: #your; --secondary: #your; --accent: #your; }

/* Animation speed */
* { transition-duration: 0.2s !important; }  /* faster */

/* Disable motion */
@media (prefers-reduced-motion: reduce) { * { animation: none !important; transition: none !important; } }
```

### Component Checklist

- [ ] Follows dark-theme color scheme
- [ ] Hover states for interactive elements
- [ ] Mobile-responsive behavior
- [ ] Keyboard navigation (if applicable)
- [ ] Smooth animation (60fps)
- [ ] Loading / empty / error states defined
- [ ] Accessibility attributes (ARIA, roles)

---

## Part 3 — Data & Integration

### Generating & Serving

```bash
# Generate (canonical)
organize-files timeline --db-path results/file_organization.db

# Serve _site/ over HTTP
python3 -m http.server 8000 -d _site
# → http://localhost:8000/timeline.html
```

The HTML fetches `timeline_data.json` via `loadSessionData()`; on failure it
renders an empty-state card prompting the user to run `organize-files timeline`
and retry.

### CLI Usage

The command generates the full timeline document in one shot — there are no
per-session, compare, or stats-only CLI modes. Everything the frontend needs
(per-session deltas via `calculate_session_changes`, cumulative totals via
`get_cumulative_stats`) is baked into `_site/timeline_data.json`.

```bash
organize-files timeline                                  # default DB path
organize-files timeline --db-path results/file_organization.db
```

Inspect slices of the generated JSON with `jq`:

```bash
jq '.cumulative' _site/timeline_data.json
jq '.sessions[] | select(.id == "session-uuid-here")' _site/timeline_data.json
```

For programmatic access, use `TimelineAPI` directly (see [Automation](#automation)).
Its public methods: `get_sessions`, `get_session_categories`,
`get_session_schema_types`, `get_session_extensions`, `calculate_session_changes`,
`get_cumulative_stats`, `generate_document`, `export_to_json`.

### Data Structure Reference

Shape matches `TimelineAPI.generate_document()` — the exact document written to
`_site/timeline_data.json`.

#### Top-Level Document
```json
{
  "generated_at": "2025-12-10T10:35:00.123456",
  "cumulative": { ... },
  "sessions": [ { ... } ],
  "session_count": 17
}
```

#### Session Object

Sessions are ordered oldest-first, and only sessions with `total_files > 0` are
included. `categories`, `schema_types`, and `extensions` are **arrays** (not
maps); `categories` and `extensions` are capped at the top 10.

```json
{
  "id": "uuid-string",
  "id_short": "uuid-str",
  "started_at": "2025-12-10T10:30:00",
  "completed_at": "2025-12-10T10:35:00",
  "dry_run": false,
  "source_directories": ["/Users/name/Downloads"],
  "base_path": "/Users/name/Documents",
  "file_limit": 1000,
  "total_files": 1000,
  "organized_count": 980,
  "skipped_count": 15,
  "error_count": 5,
  "total_cost": 2.45,
  "total_processing_time_sec": 300.5,
  "success_rate": 98.0,
  "categories": [
    {"name": "GameAssets", "color": "#667eea", "icon": "🎮", "count": 800, "avg_confidence": 0.94}
  ],
  "schema_types": [
    {"schema_type": "ImageObject", "count": 750}
  ],
  "extensions": [
    {"extension": ".png", "count": 700}
  ],
  "changes": {
    "is_first": false,
    "files_delta": 30,
    "organized_delta": 25,
    "success_rate_delta": 1.2,
    "cost_delta": 0.15,
    "time_delta": 12.4
  }
}
```

**Field notes**:
- `success_rate` = `round(organized_count / total_files * 100, 1)`.
- `changes` is computed vs the preceding session. For the first session it holds
  only `{"is_first": true, "files_delta": …, "organized_delta": …}`; the
  `success_rate_delta` / `cost_delta` / `time_delta` fields appear only when
  `is_first` is `false`.

#### Cumulative Stats Object

The `cumulative` block (from `get_cumulative_stats`) aggregates the `files` table,
so `total_files` / `total_sessions` count rows there — not the per-session
`total_files` sums.

```json
{
  "total_sessions": 17,
  "total_files": 30133,
  "total_organized": 29703,
  "avg_processing_time": 0.42,
  "top_categories": [
    {"name": "sprites", "count": 122717}
  ]
}
```

### Automation

Regenerate after each organization run:

```python
from src.api.timeline_api import TimelineAPI

api = TimelineAPI('results/file_organization.db')
api.export_to_json('_site/timeline_data.json')
print("Timeline data updated!")
```

Or on a schedule (cron):

```bash
# Update every hour
0 * * * * cd /Users/alyshialedlie/schema-org-file-system && organize-files timeline > /dev/null 2>&1
```

### Flask API (optional)

For real-time data instead of static JSON:

```python
# src/api/flask_server.py
from flask import Flask, jsonify
from flask_cors import CORS
from src.api.timeline_api import TimelineAPI

app = Flask(__name__)
CORS(app)
api = TimelineAPI('results/file_organization.db')

@app.route('/api/timeline')
def get_timeline():
    """Full timeline document (sessions + cumulative stats)."""
    return jsonify(api.generate_document())

@app.route('/api/sessions')
def get_sessions():
    return jsonify(api.get_sessions())

@app.route('/api/sessions/<session_id>')
def get_session(session_id):
    session = next((s for s in api.get_sessions() if s['id'] == session_id), None)
    if session:
        return jsonify(session)
    return jsonify({'error': 'Session not found'}), 404

@app.route('/api/stats')
def get_stats():
    return jsonify(api.get_cumulative_stats())

if __name__ == '__main__':
    app.run(debug=True, port=5000)
```

Method names above match `TimelineAPI`'s actual public surface. There is no
built-in session-comparison method — compute deltas client-side, or reuse
`calculate_session_changes`, which annotates each session with change fields.
Then point the HTML at the endpoint: `fetch('http://localhost:5000/api/sessions')`.

### Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Database not found` | Run the organizer once: `organize-files content --source ~/Downloads --dry-run --limit 10` |
| Empty `sessions: []` | Check `sqlite3 results/file_organization.db "SELECT COUNT(*) FROM organization_sessions;"` |
| A `type`/`name` run isn't on the timeline | Expected — only `organize-files content` records sessions. `organize-files type` and `organize-files name` are DB-free by design (see [`docs/FILE_ORGANIZATION.md`](FILE_ORGANIZATION.md) §5). Re-run with `organize-files content` to populate the timeline. |
| CORS error (`origin 'null'`) | Serve over HTTP: `python3 -m http.server 8000 -d _site` — don't open the file directly |
| Old/deleted sessions still shown | Regenerate (`organize-files timeline`) then hard-refresh (Cmd+Shift+R) |

Verify the generated data:
```bash
jq . _site/timeline_data.json                                   # validate JSON
organize-files timeline && jq '.cumulative' _site/timeline_data.json  # regenerate + inspect
sqlite3 results/file_organization.db ".schema organization_sessions"  # DB integrity
```

### Performance Notes

For 100+ sessions: paginate/virtual-scroll on the frontend, cache the generated
JSON with a TTL, and add DB indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_files_session ON files(session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_date ON organization_sessions(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_categories_name ON categories(name);
```

---

## Roadmap

- **Filtering** — date-range picker, quick filters (7d/30d/all), by category / cost
  / success rate.
- **Advanced comparisons** — multi-session (3+), trend lines, anomaly detection.
- **Export** — PDF reports, CSV, shareable links.
- **Real-time** — WebSocket live sessions, progress indicators, notifications.
- **Advanced viz** — D3 category sunburst, performance trends, cost forecasting.
- **Session playback** — animated file-by-file replay.
- **AI insights** — auto anomaly detection, performance / cost recommendations.

---

## File Structure

```
schema-org-file-system/
├── _site/
│   ├── timeline.html          # Main timeline interface
│   └── timeline_data.json     # Generated session data (organize-files timeline)
├── src/api/timeline_api.py    # TimelineAPI — data generator
├── scripts/generate_timeline_data.py  # Standalone launcher
├── docs/TIMELINE.md           # This file
└── results/file_organization.db  # SQLite source database
```

**Browser support**: Chrome/Edge 90+, Firefox 88+, Safari 14+, iOS 14+, Android
Chrome 90+ (requires CSS Grid, Custom Properties, Flexbox, Fetch, ES6+).
