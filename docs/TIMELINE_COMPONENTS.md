# Timeline Visual Components Library

Reusable UI components and patterns for the timeline interface.

## Component Catalog

### 1. Session Marker

**Purpose**: Interactive point on timeline that indicates session status

**Variants**:
```html
<!-- Success (< 10 errors) -->
<div class="timeline-marker success"></div>

<!-- Warning (10-100 errors) -->
<div class="timeline-marker warning"></div>

<!-- Error (> 100 errors) -->
<div class="timeline-marker error"></div>
```

**Visual Specs**:
- Size: 20px × 20px (resting), 28px × 28px (hover)
- Border: 4px solid background color
- Position: Centered on timeline spine
- Cursor: pointer
- Animation: Pulse on hover

**CSS**:
```css
.timeline-marker {
    width: 20px;
    height: 20px;
    background: var(--primary);
    border: 4px solid var(--dark-surface);
    border-radius: 50%;
    cursor: pointer;
    transition: all 0.3s;
}

.timeline-marker:hover {
    width: 28px;
    height: 28px;
    box-shadow: 0 0 20px var(--glow-primary);
    animation: pulse 1.5s infinite;
}
```

---

### 2. Metric Card

**Purpose**: Display a single key performance indicator

**Structure**:
```html
<div class="metric">
    <div class="metric-label">Total Files</div>
    <div class="metric-value">1,234</div>
    <div class="progress-bar">
        <div class="progress-fill" style="width: 85%"></div>
    </div>
</div>
```

**Variants**:
- Default (primary color)
- Success (green)
- Warning (orange)
- Danger (red)

**Visual Specs**:
- Background: Dark card
- Padding: 0.75rem
- Border: 1px solid dark border
- Border radius: 0.5rem

**Usage Examples**:
```html
<!-- Success metric -->
<div class="metric">
    <div class="metric-label">Organized</div>
    <div class="metric-value success">980</div>
</div>

<!-- Error metric (conditional red) -->
<div class="metric">
    <div class="metric-label">Errors</div>
    <div class="metric-value ${errorCount > 10 ? 'danger' : ''}">
        ${errorCount}
    </div>
</div>
```

---

### 3. Progress Bar

**Purpose**: Visual representation of completion percentage

**Structure**:
```html
<div class="progress-bar">
    <div class="progress-fill" style="width: 75%"></div>
</div>
```

**Visual Specs**:
- Height: 6px
- Background: Dark card
- Fill: Linear gradient (primary → accent)
- Border radius: 3px
- Transition: width 0.6s ease

**Accessibility**:
```html
<div class="progress-bar" role="progressbar"
     aria-valuenow="75" aria-valuemin="0" aria-valuemax="100">
    <div class="progress-fill" style="width: 75%"></div>
</div>
```

---

### 4. Category Tag

**Purpose**: Display category name with file count

**Structure**:
```html
<div class="category-tag">
    GameAssets
    <span class="category-count">800</span>
</div>
```

**Visual Specs**:
- Pill shape (border-radius: 9999px)
- Background: Dark card
- Border: 1px solid dark border
- Font size: 0.75rem
- Count badge: Primary background, white text

**Layout**:
```html
<div class="category-tags">
    <div class="category-tag">Photos <span class="category-count">120</span></div>
    <div class="category-tag">Documents <span class="category-count">60</span></div>
    <div class="category-tag">Legal <span class="category-count">20</span></div>
</div>
```

---

### 5. Session Badge

**Purpose**: Indicate run type (dry-run vs live)

**Variants**:
```html
<!-- Dry run -->
<span class="session-badge dry-run">Dry Run</span>

<!-- Live run -->
<span class="session-badge live">Live</span>
```

**Visual Specs**:
- Small caps text
- Letter spacing: 0.05em
- Padding: 0.25rem 0.75rem
- Font size: 0.7rem
- Font weight: 700

**Colors**:
- Dry run: Orange background (20% opacity), orange text
- Live: Green background (20% opacity), green text

---

### 6. Timeline Content Card

**Purpose**: Container for session summary information

**Structure**:
```html
<div class="timeline-content">
    <div class="session-header">
        <div>
            <div class="session-date">Dec 10, 2025 at 10:30 AM</div>
            <div class="session-id">session-uuid</div>
        </div>
        <span class="session-badge live">Live</span>
    </div>

    <div class="metrics-grid">
        <!-- 4 metric cards -->
    </div>

    <div class="progress-bar">
        <div class="progress-fill" style="width: 98%"></div>
    </div>

    <div class="category-tags">
        <!-- Category tags -->
    </div>
</div>
```

**Interaction States**:
- **Resting**: Default styling
- **Hover**: Border color changes to primary, lifts 4px
- **Active**: Opens snapshot modal

**Arrow Indicator**:
The card has a triangular pointer toward the timeline spine:
```css
.timeline-content::before {
    content: '';
    position: absolute;
    top: 24px;
    width: 0;
    height: 0;
    border: 12px solid transparent;
}

/* Odd items (right side) */
.timeline-item:nth-child(odd) .timeline-content::before {
    right: -24px;
    border-left-color: var(--dark-border);
}

/* Even items (left side) */
.timeline-item:nth-child(even) .timeline-content::before {
    left: -24px;
    border-right-color: var(--dark-border);
}
```

---

### 7. Button System

**Variants**:

```html
<!-- Primary button -->
<button class="btn btn-primary">
    Compare Runs
</button>

<!-- Secondary button -->
<button class="btn btn-secondary">
    Export Data
</button>
```

**Visual Specs**:
- Padding: 0.75rem 1.5rem
- Border radius: 0.5rem
- Font size: 0.875rem
- Font weight: 600
- Transition: all 0.3s

**States**:
```css
/* Primary */
.btn-primary {
    background: var(--primary);
    color: white;
}

.btn-primary:hover {
    background: var(--secondary);
    box-shadow: 0 4px 16px var(--glow-primary);
}

/* Secondary */
.btn-secondary {
    background: var(--dark-card);
    color: var(--text-primary);
    border: 1px solid var(--dark-border);
}

.btn-secondary:hover {
    background: var(--dark-surface);
    border-color: var(--primary);
}
```

**With Icons**:
```html
<button class="btn btn-primary">
    <span>🔄</span>
    Compare Runs
</button>
```

---

### 8. Modal Container

**Purpose**: Full-screen overlay for detailed views

**Structure**:
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
        <div class="modal-body">
            <!-- Modal content -->
        </div>
    </div>
</div>
```

**Interaction**:
```javascript
// Open modal
document.getElementById('modalId').classList.add('active');

// Close modal
document.getElementById('modalId').classList.remove('active');

// Close on overlay click
modal.addEventListener('click', (e) => {
    if (e.target === modal) {
        modal.classList.remove('active');
    }
});
```

**Animation**:
```css
.snapshot-modal {
    animation: modalSlideIn 0.4s ease;
}

@keyframes modalSlideIn {
    from {
        opacity: 0;
        transform: translateY(-50px) scale(0.95);
    }
    to {
        opacity: 1;
        transform: translateY(0) scale(1);
    }
}
```

---

### 9. Diff Indicator

**Purpose**: Show positive/negative changes between sessions

**Structure**:
```html
<!-- Positive change -->
<span class="diff-indicator positive">
    ↑ 120
</span>

<!-- Negative change -->
<span class="diff-indicator negative">
    ↓ 15
</span>
```

**Visual Specs**:
- Font size: 0.75rem
- Font weight: 700
- Inline-flex with gap: 0.25rem
- Colors: Green (positive), Red (negative)

**Usage in Context**:
```html
<div class="metric-value">
    1,234
    <span class="diff-indicator positive">↑ 120</span>
</div>
```

---

### 10. Loading Spinner

**Purpose**: Indicate data loading state

**Structure**:
```html
<div class="loading-container">
    <div class="loading-spinner"></div>
    <div class="loading-text">Loading organization history...</div>
</div>
```

**Visual Specs**:
- Size: 64px × 64px
- Border: 4px solid dark border
- Border-top: Primary color
- Animation: 1s linear infinite rotation

**CSS**:
```css
.loading-spinner {
    width: 64px;
    height: 64px;
    border: 4px solid var(--dark-border);
    border-top-color: var(--primary);
    border-radius: 50%;
    animation: spin 1s linear infinite;
}

@keyframes spin {
    to { transform: rotate(360deg); }
}
```

---

### 11. Empty State

**Purpose**: Display when no data is available

**Structure**:
```html
<div class="empty-state">
    <div class="empty-state-icon">📊</div>
    <h2>No sessions found</h2>
    <p>Run the file organizer to see your timeline</p>
    <button class="btn btn-primary">Run Organizer</button>
</div>
```

**Visual Specs**:
- Text align: center
- Padding: 4rem
- Icon size: 4rem
- Icon opacity: 0.5
- Color: Secondary text

---

### 12. Chart Card

**Purpose**: Container for data visualizations

**Structure**:
```html
<div class="chart-card">
    <div class="chart-title">Category Distribution</div>
    <div class="chart-content">
        <!-- Chart content (bars, etc.) -->
    </div>
</div>
```

**Bar Chart Pattern**:
```html
<div class="chart-card">
    <div class="chart-title">Top Categories</div>
    <div>
        <!-- Single bar -->
        <div style="margin-bottom: 0.75rem;">
            <div style="display: flex; justify-content: space-between; margin-bottom: 0.25rem;">
                <span style="font-size: 0.875rem;">GameAssets</span>
                <span style="font-weight: 700;">84.8%</span>
            </div>
            <div class="progress-bar">
                <div class="progress-fill" style="width: 84.8%"></div>
            </div>
        </div>
    </div>
</div>
```

---

### 13. View Toggle

**Purpose**: Switch between different view modes

**Structure**:
```html
<div class="view-toggle">
    <button class="active" onclick="switchView('timeline')">
        Timeline View
    </button>
    <button onclick="switchView('list')">
        List View
    </button>
    <button onclick="switchView('stats')">
        Statistics
    </button>
</div>
```

**Visual Specs**:
- Container: Dark card background, 0.25rem padding
- Buttons: Transparent background, 0.5rem padding
- Active: Primary background with glow
- Border radius: 0.5rem (container), 0.4rem (buttons)

---

### 14. Zoom Controls

**Purpose**: Adjust timeline scale

**Structure**:
```html
<div class="zoom-controls">
    <button class="zoom-btn" onclick="adjustZoom(-1)">−</button>
    <span class="zoom-level">100%</span>
    <button class="zoom-btn" onclick="adjustZoom(1)">+</button>
</div>
```

**Visual Specs**:
- Button size: 36px × 36px
- Font size: 1.2rem
- Border: 1px solid dark border
- Border radius: 0.5rem

**Interaction**:
```javascript
let zoomLevel = 100;

function adjustZoom(direction) {
    zoomLevel += direction * 10;
    zoomLevel = Math.max(50, Math.min(200, zoomLevel));

    document.getElementById('zoomLevel').textContent = zoomLevel + '%';
    document.getElementById('timelineItems').style.transform =
        `scale(${zoomLevel / 100})`;
}
```

---

## Composition Patterns

### Pattern 1: Metrics Grid

**Use Case**: Display 2-4 related metrics

```html
<div class="metrics-grid">
    <div class="metric">
        <div class="metric-label">Total Files</div>
        <div class="metric-value">1,234</div>
    </div>
    <div class="metric">
        <div class="metric-label">Organized</div>
        <div class="metric-value success">1,200</div>
    </div>
    <div class="metric">
        <div class="metric-label">Errors</div>
        <div class="metric-value">5</div>
    </div>
    <div class="metric">
        <div class="metric-label">Cost</div>
        <div class="metric-value">$2.45</div>
    </div>
</div>
```

**Grid Behavior**:
- Desktop: 4 columns
- Tablet: 2 columns
- Mobile: 1 column

---

### Pattern 2: Comparison Layout

**Use Case**: Side-by-side session comparison

```html
<div class="comparison-container">
    <!-- Left session -->
    <div class="comparison-card">
        <h3>Previous Run</h3>
        <div class="metrics-grid">
            <!-- Metrics -->
        </div>
    </div>

    <!-- Arrow -->
    <div class="comparison-arrow">
        →
        <span>vs</span>
    </div>

    <!-- Right session -->
    <div class="comparison-card">
        <h3>Latest Run</h3>
        <div class="metrics-grid">
            <!-- Metrics with diff indicators -->
        </div>
    </div>
</div>
```

---

### Pattern 3: Timeline Item

**Use Case**: Single session on timeline

```html
<div class="timeline-item">
    <div class="timeline-marker success"></div>
    <div class="timeline-content">
        <!-- Session content -->
    </div>
</div>
```

**Layout Behavior**:
- Odd items: Content on right, arrow points left
- Even items: Content on left, arrow points right
- Mobile: All content on right, arrows point left

---

## Utility Classes

### Spacing
```css
.mt-1 { margin-top: 0.25rem; }
.mt-2 { margin-top: 0.5rem; }
.mt-4 { margin-top: 1rem; }
.mb-1 { margin-bottom: 0.25rem; }
.mb-2 { margin-bottom: 0.5rem; }
.mb-4 { margin-bottom: 1rem; }
```

### Text Colors
```css
.text-primary { color: var(--text-primary); }
.text-secondary { color: var(--text-secondary); }
.text-success { color: var(--success); }
.text-warning { color: var(--warning); }
.text-danger { color: var(--danger); }
```

### Typography
```css
.font-bold { font-weight: 700; }
.font-semibold { font-weight: 600; }
.text-xs { font-size: 0.7rem; }
.text-sm { font-size: 0.875rem; }
.text-base { font-size: 1rem; }
.text-lg { font-size: 1.125rem; }
```

---

## Responsive Behavior

### Mobile Adaptations

**Timeline**:
```css
@media (max-width: 1024px) {
    /* Move spine to left */
    .timeline-spine { left: 20px; }

    /* All content to right */
    .timeline-item:nth-child(odd) .timeline-content,
    .timeline-item:nth-child(even) .timeline-content {
        margin-left: 3rem;
        margin-right: 0;
    }

    /* All arrows point left */
    .timeline-content::before {
        left: -24px !important;
        border-right-color: var(--dark-border) !important;
        border-left-color: transparent !important;
    }
}
```

**Grids**:
```css
@media (max-width: 640px) {
    .metrics-grid {
        grid-template-columns: 1fr;
    }

    .charts-grid {
        grid-template-columns: 1fr;
    }
}
```

---

## Customization Guide

### Change Color Scheme

Edit CSS variables in `:root`:
```css
:root {
    --primary: #your-color;
    --secondary: #your-color;
    --accent: #your-color;
}
```

### Adjust Animation Speed

```css
/* Faster animations */
* { transition-duration: 0.2s !important; }
animation-duration: 0.4s !important;

/* Slower animations */
* { transition-duration: 0.5s !important; }
animation-duration: 0.8s !important;
```

### Disable Animations

```css
@media (prefers-reduced-motion: reduce) {
    * {
        animation: none !important;
        transition: none !important;
    }
}
```

---

## Component Checklist

Use this when building new timeline features:

- [ ] Component follows dark theme color scheme
- [ ] Hover states defined for interactive elements
- [ ] Mobile responsive behavior implemented
- [ ] Keyboard navigation works (if applicable)
- [ ] Animation performance is smooth (60fps)
- [ ] Loading states defined
- [ ] Empty states defined
- [ ] Error states defined
- [ ] Accessibility attributes added (ARIA, roles)
- [ ] Component documented in this file

---

**Component Library Version**: 1.0.0
**Last Updated**: 2025-12-10
**Maintained By**: Visual Storyteller Agent
