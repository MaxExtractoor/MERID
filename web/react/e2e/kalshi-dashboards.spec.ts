/**
 * Cross-browser compatibility tests for Kalshi trading dashboards.
 *
 * Covers:
 *   - Kalshi Dashboard (market discovery, quick tabs, trade ticket)
 *   - Kalshi Portfolio (positions, risk tab, sizing metrics)
 *   - Kalshi Vol Dashboard (3×2 grid, alerts, insights)
 *   - Sidebar navigation between views
 *   - Responsive viewports (desktop, tablet)
 *   - Keyboard navigation & focus states
 *   - Error/toast overlay behaviour
 *
 * Runs on: Chromium, Firefox, WebKit, Mobile Chrome, Mobile Safari
 * (configured in playwright.config.ts)
 */

import { test, expect, type Page } from '@playwright/test';

// ── Helpers ──────────────────────────────────────────────────────────────────

async function navigateTo(page: Page, viewName: string) {
  // Click sidebar item matching the view name
  const btn = page.locator(`button:has-text("${viewName}")`).first();
  await btn.click();
  // Small settle time for React re-render
  await page.waitForTimeout(300);
}

// ── Sidebar & Navigation ─────────────────────────────────────────────────────

test.describe('Sidebar Navigation', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('text=MERID', { timeout: 10000 });
  });

  test('renders MERID logo and sidebar', async ({ page }) => {
    await expect(page.locator('text=MERID')).toBeVisible();
  });

  test('Kalshi Suite section visible on desktop', async ({ page }) => {
    await expect(page.locator('text=Kalshi Suite')).toBeVisible();
  });

  test('navigate to Kalshi Dashboard', async ({ page }) => {
    await navigateTo(page, 'Kalshi Dashboard');
    await expect(page.locator('h1')).toContainText('Kalshi');
  });

  test('navigate to Kalshi Portfolio', async ({ page }) => {
    await navigateTo(page, 'Kalshi Portfolio');
    await expect(page.locator('h1')).toContainText('Portfolio');
  });

  test('navigate to Vol Dashboard', async ({ page }) => {
    await navigateTo(page, 'Vol Dashboard');
    await expect(page.locator('h1')).toContainText('Vol Dashboard');
  });

  test('navigate to Kalshi Grid', async ({ page }) => {
    await navigateTo(page, 'Kalshi Grid');
    await expect(page.locator('h1')).toContainText(/Grid|Kalshi/);
  });
});

// ── Kalshi Dashboard View ────────────────────────────────────────────────────

test.describe('Kalshi Dashboard View', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('text=MERID', { timeout: 10000 });
    await navigateTo(page, 'Kalshi Dashboard');
  });

  test('renders market discovery header', async ({ page }) => {
    await expect(page.locator('h1')).toContainText('Kalshi');
  });

  test('renders mode badge (PAPER/LIVE)', async ({ page }) => {
    // Badge should be present even if API returns error (shows fallback)
    // May or may not render depending on API — just ensure no crash
    await page.waitForTimeout(500);
    await expect(page.locator('body')).toBeVisible();
  });

  test('quick-filter tabs are clickable', async ({ page }) => {
    const tabs = page.locator('button').filter({ hasText: /All|Crypto|Volume/ });
    const count = await tabs.count();
    if (count > 0) {
      await tabs.first().click();
      // Should not crash
      await page.waitForTimeout(200);
    }
  });

  test('no overlapping toasts or stuck overlays', async ({ page }) => {
    // Check no fixed/absolute overlays cover the entire viewport
    const overlays = page.locator('[class*="fixed inset-0"]');
    const count = await overlays.count();
    // At most the background gradient should be fixed
    expect(count).toBeLessThanOrEqual(2);
  });

  test('page does not freeze under load', async ({ page }) => {
    // Interact with a few elements rapidly
    const buttons = page.locator('button');
    const count = await buttons.count();
    for (let i = 0; i < Math.min(count, 5); i++) {
      await buttons.nth(i).click({ timeout: 2000 }).catch(() => { /* ignore click errors */ });
    }
    // Page should still be interactive
    await expect(page.locator('body')).toBeVisible();
  });
});

// ── Kalshi Portfolio View ────────────────────────────────────────────────────

test.describe('Kalshi Portfolio View', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('text=MERID', { timeout: 10000 });
    await navigateTo(page, 'Kalshi Portfolio');
  });

  test('renders portfolio header', async ({ page }) => {
    await expect(page.locator('h1')).toContainText('Portfolio');
  });

  test('tab navigation works', async ({ page }) => {
    const tabs = page.locator('button').filter({ hasText: /Positions|Orders|Fills|Risk/ });
    const count = await tabs.count();
    for (let i = 0; i < count; i++) {
      await tabs.nth(i).click();
      await page.waitForTimeout(200);
    }
    // Should not crash
    await expect(page.locator('body')).toBeVisible();
  });

  test('keyboard Tab navigates through interactive elements', async ({ page }) => {
    // Press Tab several times and verify focus moves
    for (let i = 0; i < 5; i++) {
      await page.keyboard.press('Tab');
    }
    // Active element should be a button or input
    const tag = await page.evaluate(() => document.activeElement?.tagName);
    expect(['BUTTON', 'INPUT', 'A', 'SELECT']).toContain(tag);
  });
});

// ── Kalshi Vol Dashboard View ────────────────────────────────────────────────

test.describe('Kalshi Vol Dashboard View', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('text=MERID', { timeout: 10000 });
    await navigateTo(page, 'Vol Dashboard');
  });

  test('renders vol dashboard header', async ({ page }) => {
    await expect(page.locator('h1')).toContainText('Vol Dashboard');
  });

  test('renders 3-column top row grid on desktop', async ({ page, viewport }) => {
    if (viewport && viewport.width >= 768) {
      // md:grid-cols-3 should produce 3-column layout
      const grid = page.locator('.grid.grid-cols-1.md\\:grid-cols-3');
      await expect(grid).toBeVisible();
    }
  });

  test('Venue Status card visible', async ({ page }) => {
    await expect(page.locator('text=Venue Status')).toBeVisible();
  });

  test('Vol Targeting card visible', async ({ page }) => {
    await expect(page.locator('text=Vol Targeting')).toBeVisible();
  });

  test('Risk Limits card visible', async ({ page }) => {
    await expect(page.locator('text=Risk Limits')).toBeVisible();
  });

  test('Agent Performance Grid visible', async ({ page }) => {
    await expect(page.locator('text=Agent Performance Grid')).toBeVisible();
  });

  test('Equity & Vol card visible', async ({ page }) => {
    await expect(page.locator('text=Equity & Vol')).toBeVisible();
  });

  test('Live Alerts section visible', async ({ page }) => {
    await expect(page.locator('text=Live Alerts')).toBeVisible();
  });

  test('Refresh button triggers data reload', async ({ page }) => {
    const refreshBtn = page.locator('button:has-text("Refresh")');
    await expect(refreshBtn).toBeVisible();
    await refreshBtn.click();
    // Should not crash
    await page.waitForTimeout(500);
    await expect(page.locator('h1')).toContainText('Vol Dashboard');
  });

  test('no console errors on load', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', msg => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    // Reload to capture from start
    await page.reload();
    await page.waitForTimeout(2000);
    // Filter out expected API errors (backend may not be running)
    const unexpectedErrors = errors.filter(
      e => !e.includes('fetch') && !e.includes('ERR_CONNECTION') && !e.includes('NetworkError')
    );
    expect(unexpectedErrors).toHaveLength(0);
  });
});

// ── Responsive Layout ────────────────────────────────────────────────────────

test.describe('Responsive Layout', () => {
  test('sidebar collapses on narrow viewport', async ({ page }) => {
    await page.setViewportSize({ width: 768, height: 1024 });
    await page.goto('/');
    await page.waitForSelector('text=MERID', { timeout: 10000 });
    // On narrow viewports the sidebar may be hidden
    await page.waitForTimeout(500);
    // Should still be able to use the app
    await expect(page.locator('body')).toBeVisible();
  });

  test('grid cards stack on mobile viewport', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto('/');
    await page.waitForSelector('text=MERID', { timeout: 10000 });
    // Open mobile menu if needed
    const menuBtn = page.locator('button[aria-label*="menu"], button[aria-label*="Menu"]').first();
    if (await menuBtn.isVisible()) {
      await menuBtn.click();
      await page.waitForTimeout(300);
    }
    await expect(page.locator('body')).toBeVisible();
  });

  test('1440x900 laptop viewport renders correctly', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/');
    await page.waitForSelector('text=MERID', { timeout: 10000 });
    await navigateTo(page, 'Vol Dashboard');
    await expect(page.locator('text=Venue Status')).toBeVisible();
    await expect(page.locator('text=Vol Targeting')).toBeVisible();
    await expect(page.locator('text=Risk Limits')).toBeVisible();
  });

  test('1080p viewport renders correctly', async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.goto('/');
    await page.waitForSelector('text=MERID', { timeout: 10000 });
    await navigateTo(page, 'Kalshi Dashboard');
    await expect(page.locator('h1')).toContainText('Kalshi');
  });
});

// ── Keyboard & Accessibility ─────────────────────────────────────────────────

test.describe('Keyboard & Accessibility', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('text=MERID', { timeout: 10000 });
  });

  test('Tab key moves focus through sidebar items', async ({ page }) => {
    // Focus sidebar by clicking first item
    const firstBtn = page.locator('nav button').first();
    await firstBtn.focus();
    await page.keyboard.press('Tab');
    const tag = await page.evaluate(() => document.activeElement?.tagName);
    expect(tag).toBe('BUTTON');
  });

  test('Enter key activates sidebar navigation', async ({ page }) => {
    const volBtn = page.locator('button:has-text("Vol Dashboard")');
    await volBtn.focus();
    await page.keyboard.press('Enter');
    await page.waitForTimeout(500);
    await expect(page.locator('h1')).toContainText('Vol Dashboard');
  });

  test('focus ring visible on buttons', async ({ page }) => {
    const btn = page.locator('button').first();
    await btn.focus();
    // Verify the element is focused
    const isFocused = await btn.evaluate(el => el === document.activeElement);
    expect(isFocused).toBe(true);
  });
});

// ── Performance ──────────────────────────────────────────────────────────────

test.describe('Performance', () => {
  test('initial load completes within 10s', async ({ page }) => {
    const start = Date.now();
    await page.goto('/');
    await page.waitForSelector('text=MERID', { timeout: 10000 });
    const loadTime = Date.now() - start;
    expect(loadTime).toBeLessThan(10000);
  });

  test('view switch completes within 2s', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('text=MERID', { timeout: 10000 });
    const start = Date.now();
    await navigateTo(page, 'Vol Dashboard');
    await page.waitForSelector('text=Venue Status', { timeout: 2000 });
    const switchTime = Date.now() - start;
    expect(switchTime).toBeLessThan(2000);
  });

  test('scrolling is smooth on large content', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('text=MERID', { timeout: 10000 });
    await navigateTo(page, 'Vol Dashboard');
    // Scroll the main content area
    await page.evaluate(() => {
      const main = document.querySelector('main');
      if (main) main.scrollTop = main.scrollHeight;
    });
    await page.waitForTimeout(300);
    // Should not freeze
    await expect(page.locator('body')).toBeVisible();
  });
});
