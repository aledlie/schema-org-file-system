# Timeline Integration Guide

Quick guide to connecting the timeline visualization to your actual database.

## Setup Steps

### 1. Generate Timeline Data

```bash
# From project root
python3 src/api/timeline_api.py --db-path results/file_organization.db --output _site/timeline_data.json
```

**Expected Output**:
```
✅ Timeline data exported successfully to _site/timeline_data.json

📊 Summary:
   Total Sessions: 17
   Total Files: 30,133
   Success Rate: 98.6%
   Total Cost: $45.23
```

### 2. Update Timeline HTML to Use Real Data

Edit `/Users/alyshialedlie/schema-org-file-system/_site/timeline.html` and replace the `loadSessionData()` function:

```javascript
async function loadSessionData() {
    try {
        // Fetch from generated JSON file
        const response = await fetch('timeline_data.json');
        const data = await response.json();

        sessions = data.sessions;

        renderTimeline();
        updateHeaderStats();

        document.getElementById('loadingState').style.display = 'none';
        document.getElementById('timelineContainer').style.display = 'block';
    } catch (error) {
        console.error('Failed to load session data:', error);
        document.getElementById('loadingState').innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">⚠️</div>
                <h2>Failed to load data</h2>
                <p>${error.message}</p>
                <p style="color: var(--text-secondary); margin-top: 1rem;">
                    Make sure you've generated timeline data:<br>
                    <code style="background: var(--dark-card); padding: 0.5rem; border-radius: 0.25rem; display: inline-block; margin-top: 0.5rem;">
                        python3 src/api/timeline_api.py
                    </code>
                </p>
                <button class="btn btn-primary" onclick="loadSessionData()" style="margin-top: 1rem;">Retry</button>
            </div>
        `;
    }
}
```

### 3. Serve the Timeline Locally

```bash
# Option 1: Python simple server
cd _site
python3 -m http.server 8000

# Option 2: Node.js http-server (if installed)
npx http-server _site -p 8000

# Then open: http://localhost:8000/timeline.html
```

## CLI Usage

### Get All Sessions
```bash
python3 src/api/timeline_api.py
```

### Get Specific Session
```bash
python3 src/api/timeline_api.py --session-id "session-uuid-here"
```

### Compare Two Sessions
```bash
python3 src/api/timeline_api.py --compare session-1 session-2
```

### Show Aggregate Statistics
```bash
python3 src/api/timeline_api.py --stats
```

**Output Example**:
```json
{
  "total_sessions": 17,
  "total_files_processed": 30133,
  "total_organized": 29703,
  "total_errors": 142,
  "total_cost": 45.23,
  "average_success_rate": 98.6,
  "category_breakdown": {
    "GameAssets": 25567,
    "Photos": 2450,
    "Documents": 1850,
    "Legal": 266
  },
  "dry_run_count": 3,
  "live_run_count": 14
}
```

## Automation

### Auto-Generate After Each Run

Add this to your file organizer script:

```python
from src.api.timeline_api import TimelineAPI

# After organization completes
api = TimelineAPI('results/file_organization.db')
api.export_to_json('_site/timeline_data.json')
print("Timeline data updated!")
```

### Scheduled Refresh

Create a cron job to regenerate timeline data:

```bash
# Edit crontab
crontab -e

# Add this line (updates every hour)
0 * * * * cd /Users/alyshialedlie/schema-org-file-system && python3 src/api/timeline_api.py > /dev/null 2>&1
```

## Flask API (Optional)

For real-time data, create a Flask endpoint:

```python
# src/api/flask_server.py
from flask import Flask, jsonify
from flask_cors import CORS
from timeline_api import TimelineAPI

app = Flask(__name__)
CORS(app)

api = TimelineAPI('results/file_organization.db')

@app.route('/api/sessions')
def get_sessions():
    """Get all sessions."""
    return jsonify(api.get_all_sessions())

@app.route('/api/sessions/<session_id>')
def get_session(session_id):
    """Get specific session."""
    session = api.get_session_by_id(session_id)
    if session:
        return jsonify(session)
    return jsonify({'error': 'Session not found'}), 404

@app.route('/api/sessions/compare/<id1>/<id2>')
def compare_sessions(id1, id2):
    """Compare two sessions."""
    comparison = api.get_session_comparison(id1, id2)
    return jsonify(comparison)

@app.route('/api/stats')
def get_stats():
    """Get aggregate statistics."""
    return jsonify(api.get_aggregate_stats())

if __name__ == '__main__':
    app.run(debug=True, port=5000)
```

**Install dependencies**:
```bash
pip install flask flask-cors
```

**Run server**:
```bash
python3 src/api/flask_server.py
```

**Update timeline.html**:
```javascript
// Change fetch URL
const response = await fetch('http://localhost:5000/api/sessions');
```

## Troubleshooting

### Database Not Found
```
❌ Error: Database not found: results/file_organization.db
```

**Solution**: Run the file organizer at least once to create the database:
```bash
python3 scripts/file_organizer_content_based.py --dry-run --limit 10
```

### No Sessions in Database
```json
{
  "sessions": [],
  "aggregate_stats": {
    "total_sessions": 0
  }
}
```

**Solution**: Check if `organization_sessions` table has data:
```bash
sqlite3 results/file_organization.db "SELECT COUNT(*) FROM organization_sessions;"
```

### CORS Errors in Browser
```
Access to fetch at 'file:///...' from origin 'null' has been blocked by CORS policy
```

**Solution**: Use a local server instead of opening file directly:
```bash
python3 -m http.server 8000 -d _site
```

### Old Data Showing
```
Timeline shows old sessions that were deleted
```

**Solution**: Regenerate timeline data:
```bash
python3 src/api/timeline_api.py
# Then hard refresh in browser (Cmd+Shift+R)
```

## Data Structure Reference

### Session Object
```json
{
  "id": "uuid-string",
  "started_at": "2025-12-10T10:30:00",
  "completed_at": "2025-12-10T10:35:00",
  "dry_run": false,
  "total_files": 1000,
  "organized_count": 980,
  "skipped_count": 15,
  "error_count": 5,
  "total_cost": 2.45,
  "processing_time": 300.5,
  "source_directories": ["/Users/name/Downloads"],
  "base_path": "/Users/name/Documents",
  "categories": {
    "GameAssets": 800,
    "Photos": 120
  },
  "schema_types": {
    "ImageObject": 750
  },
  "success_rate": 98.0,
  "files_per_second": 3.33,
  "cost_per_file": 0.0025
}
```

### Aggregate Stats Object
```json
{
  "total_sessions": 17,
  "total_files_processed": 30133,
  "total_organized": 29703,
  "total_errors": 142,
  "total_cost": 45.23,
  "average_success_rate": 98.6,
  "total_processing_time": 4500.0,
  "category_breakdown": {
    "GameAssets": 25567
  },
  "dry_run_count": 3,
  "live_run_count": 14
}
```

## Performance Notes

### Large Datasets

For 100+ sessions, consider:

1. **Pagination**: Load sessions in chunks
2. **Virtual scrolling**: Only render visible items
3. **Indexing**: Add database indexes on `started_at`
4. **Caching**: Cache generated JSON with TTL

### Query Optimization

The API uses efficient SQL queries with joins. For even better performance:

```sql
-- Add indexes
CREATE INDEX IF NOT EXISTS idx_files_session ON files(session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_date ON organization_sessions(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_categories_name ON categories(name);
```

## Next Steps

1. Generate initial timeline data
2. Open timeline.html in browser
3. Verify all sessions display correctly
4. Test snapshot and comparison modals
5. Customize colors/branding if needed
6. Set up auto-refresh after runs

## Support

If you encounter issues:

1. Check browser console for JavaScript errors
2. Verify JSON structure with `jq`:
   ```bash
   jq . _site/timeline_data.json
   ```
3. Test API directly:
   ```bash
   python3 src/api/timeline_api.py --stats
   ```
4. Check database integrity:
   ```bash
   sqlite3 results/file_organization.db ".schema organization_sessions"
   ```

---

**Ready to launch!** Generate your timeline data and watch your organization history come to life.
