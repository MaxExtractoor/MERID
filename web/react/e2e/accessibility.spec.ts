/**
 * E2E Accessibility Tests — seven-view console.
 *
 * All backend calls are routed to 503 so these specs never touch production
 * state; they verify keyboard/ARIA structure of the shell only.
 */

import { test, expect } from '@playwright/test';

test.describe('Accessibility', () => {
  test.beforeEach(async ({ page, context }) => {
    await context.route('**/api/**', async route => {
      await route.fulfill({ status: 503, json: { detail: 'isolated a11y run' } });
    });
    await page.goto('/');
    await expect(page.getByRole('navigation', { name: 'Primary' })).toBeVisible();
  });

  test('sidebar navigation is labelled and marks the current page', async ({ page }) => {
    const nav = page.getByRole('navigation', { name: 'Primary' });
    await expect(nav).toBeVisible();
    const current = nav.locator('[aria-current="page"]');
    await expect(current).toHaveCount(1);
  });

  test('every view heading resolves after keyboard navigation', async ({ page }) => {
    const routes: Array<[string, string | RegExp]> = [
      ['1', 'fleet health'],
      ['2', /agent$/],
      ['3', 'Trade'],
      ['4', 'Portfolio'],
      ['5', 'Risk'],
      ['6', 'System'],
    ];
    for (const [key, name] of routes) {
      await page.keyboard.press(key);
      await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();
    }
  });

  test('interactive elements expose accessible names', async ({ page }) => {
    const buttons = page.locator('button');
    const count = await buttons.count();
    let unnamed = 0;
    for (let i = 0; i < Math.min(count, 20); i++) {
      const button = buttons.nth(i);
      const name = (await button.getAttribute('aria-label')) ?? (await button.textContent()) ?? (await button.getAttribute('title'));
      if (!name?.trim()) unnamed += 1;
    }
    expect(unnamed).toBe(0);
  });

  test('alerts use role=alert so screen readers announce them', async ({ page }) => {
    await page.waitForTimeout(3500);
    const alerts = page.locator('[role="alert"]');
    await expect(alerts.first()).toBeVisible();
  });

  test('focus indicators on interactive elements', async ({ page }) => {
    await page.keyboard.press('Tab');
    const tag = await page.evaluate(() => document.activeElement?.tagName);
    expect(['BUTTON', 'INPUT', 'A', 'SELECT']).toContain(tag);
  });
});
