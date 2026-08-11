import { test, expect } from './fixtures/index.js';
import { measurePagePerformance, checkThresholds, formatMetrics, DEFAULT_THRESHOLDS } from './fixtures/performance.js';

// Single source of truth for the dashboard's feature cards, in DOM order. Count,
// title and navigation coverage all derive from it, so a new card cannot ship
// with only some of the three.
export const DASHBOARD_CARDS = [
  { title: 'Organization Report', href: 'organization_report.html' },
  { title: 'Metadata Viewer', href: 'metadata_viewer.html' },
  { title: 'Correction Interface', href: 'correction_interface.html' },
  { title: 'ML Data Explorer', href: 'ml_data_explorer.html' },
  { title: 'Residence Galleries', href: 'residence_gallery.html' },
] as const;

// Same rationale as DASHBOARD_CARDS: one array so a new stat cannot ship with
// the count updated and the label unasserted, or vice versa.
export const DASHBOARD_STATS = [
  'Files Processed',
  'Success Rate',
  'Categories',
  'ML Accuracy',
] as const;

test.describe('Dashboard', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
  });

  test('should load the main dashboard', async ({ page }) => {
    // Verify hero section
    await expect(page.locator('h1')).toContainText('Schema.org File Organization');
    await expect(page.locator('.hero-subtitle')).toContainText('AI-Powered Content Analysis');
  });

  test('should display resource usage panel', async ({ page }) => {
    const resourcePanel = page.locator('.resource-panel');
    await expect(resourcePanel).toBeVisible();

    // Check for resource items
    await expect(page.locator('#files-analyzed')).toBeVisible();
    await expect(page.locator('#time-spent')).toBeVisible();
    await expect(page.locator('#cpu-time')).toBeVisible();
    await expect(page.locator('#gpu-cost')).toBeVisible();
  });

  test('should display statistics bar', async ({ page }) => {
    const statsBar = page.locator('.stats-bar');
    await expect(statsBar).toBeVisible();

    const statItems = page.locator('.stat-item');
    await expect(statItems).toHaveCount(DASHBOARD_STATS.length);

    await expect(page.locator('.stat-label')).toHaveText([...DASHBOARD_STATS]);
  });

  test('should display feature cards', async ({ page }) => {
    const cardsGrid = page.locator('.cards-grid');
    await expect(cardsGrid).toBeVisible();

    // Two locators, so neither assertion subsumes the other: the count is over
    // .feature-card (the anchors), the text is over .card-title (their headings).
    // A card with no title, or a stray title outside a card, fails exactly one.
    const featureCards = page.locator('.feature-card');
    await expect(featureCards).toHaveCount(DASHBOARD_CARDS.length);

    // toHaveText matches each element's full text, not a substring, so a title
    // that is merely a prefix of the real one fails here. It is also ordered,
    // which pins DASHBOARD_CARDS to DOM order rather than just asserting it.
    await expect(page.locator('.card-title')).toHaveText(DASHBOARD_CARDS.map((card) => card.title));
  });

  for (const { title, href } of DASHBOARD_CARDS) {
    test(`should navigate to ${title}`, async ({ page }) => {
      await page.click(`a[href="${href}"]`);
      // URL may or may not have .html extension depending on server config
      await expect(page).toHaveURL(new RegExp(href.replace(/\.html$/, '')));
    });
  }

  test('should display technology stack in footer', async ({ page }) => {
    const footer = page.locator('.footer');
    await expect(footer).toBeVisible();

    // Verify tech badges
    await expect(page.locator('.tech-badge').filter({ hasText: 'Python 3.14' })).toBeVisible();
    await expect(page.locator('.tech-badge').filter({ hasText: 'CLIP Vision AI' })).toBeVisible();
    await expect(page.locator('.tech-badge').filter({ hasText: 'Schema.org' })).toBeVisible();
  });

  test('should have responsive layout on mobile', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await page.reload();
    await page.waitForLoadState('networkidle');

    // Cards should stack vertically on mobile
    const cardsGrid = page.locator('.cards-grid');
    await expect(cardsGrid).toBeVisible();

    // Hero should still be visible
    await expect(page.locator('.hero h1')).toBeVisible();
  });

  test('feature cards should have hover effects', async ({ page }) => {
    const firstCard = page.locator('.feature-card').first();

    // Get initial transform
    const initialTransform = await firstCard.evaluate((el) => {
      return window.getComputedStyle(el).transform;
    });

    // Hover over the card
    await firstCard.hover();

    // Wait for animation
    await page.waitForTimeout(500);

    // Transform should change on hover
    const hoverTransform = await firstCard.evaluate((el) => {
      return window.getComputedStyle(el).transform;
    });

    // The transform should be different (card moves up)
    expect(hoverTransform).not.toBe(initialTransform);
  });
});

test.describe('Dashboard Performance', () => {
  test('should meet Core Web Vitals thresholds', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('load');

    // Wait for any animations to complete
    await page.waitForTimeout(1000);

    const metrics = await measurePagePerformance(page);
    console.log(formatMetrics(metrics));

    const violations = checkThresholds(metrics, DEFAULT_THRESHOLDS);

    if (violations.length > 0) {
      console.warn('Performance threshold violations:');
      violations.forEach(v => console.warn(`  - ${v}`));
    }

    // Assert no critical violations (LCP should be under 2.5s for initial load)
    if (metrics.lcp !== null) {
      expect(metrics.lcp).toBeLessThan(2500);
    }
  });

  test('should load within acceptable time', async ({ page }) => {
    const startTime = Date.now();

    await page.goto('/');
    await page.waitForLoadState('networkidle');

    const loadTime = Date.now() - startTime;

    console.log(`Page load time: ${loadTime}ms`);

    // Page should load within 5 seconds
    expect(loadTime).toBeLessThan(5000);
  });

  test('should not have excessive network requests', async ({ page }) => {
    const requests: string[] = [];

    page.on('request', (request) => {
      requests.push(request.url());
    });

    await page.goto('/');
    await page.waitForLoadState('networkidle');

    console.log(`Total network requests: ${requests.length}`);

    // Should not have more than 50 requests for initial page load
    expect(requests.length).toBeLessThan(50);
  });
});
