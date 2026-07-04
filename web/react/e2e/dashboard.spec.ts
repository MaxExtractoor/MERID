/**
 * E2E Tests for Dashboard View
 * Tests critical user flows in the Dashboard
 */

import { test, expect } from '@playwright/test';

test.describe('Dashboard View', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  test('should load dashboard and display key metrics', async ({ page }) => {
    // Wait for dashboard to load
    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
    
    // Check for key metric cards
    await expect(page.locator('text=/Portfolio Value/i')).toBeVisible();
    await expect(page.locator('text=/Unrealized PnL/i')).toBeVisible();
    await expect(page.locator('text=/Daily PnL/i')).toBeVisible();
  });

  test('should display per-asset metrics for BTC, ETH, SOL, XRP, DOGE', async ({ page }) => {
    // Check for all 5 crypto assets
    await expect(page.locator('text=/BTC/i')).toBeVisible();
    await expect(page.locator('text=/ETH/i')).toBeVisible();
    await expect(page.locator('text=/SOL/i')).toBeVisible();
    await expect(page.locator('text=/XRP/i')).toBeVisible();
    await expect(page.locator('text=/DOGE/i')).toBeVisible();
  });

  test('should display Kalshi 15m Alignment Panel', async ({ page }) => {
    // Check for alignment panel
    await expect(page.locator('text=/Alignment Status/i')).toBeVisible();
    await expect(page.locator('text=/Invariants/i')).toBeVisible();
  });

  test('should display Kalshi 15m Health Panel', async ({ page }) => {
    // Check for health panel
    await expect(page.locator('text=/Health Status/i')).toBeVisible();
    await expect(page.locator('text=/Series Health/i')).toBeVisible();
  });

  test('should navigate to Trade view via keyboard shortcut (2)', async ({ page }) => {
    // Press '2' to navigate to Trade
    await page.keyboard.press('2');
    
    // Verify navigation to Trade view
    await expect(page.getByRole('heading', { name: 'Trade' })).toBeVisible();
  });

  test('should navigate to Monitor view via keyboard shortcut (3)', async ({ page }) => {
    // Press '3' to navigate to Monitor
    await page.keyboard.press('3');
    
    // Verify navigation to Monitor view
    await expect(page.getByRole('heading', { name: 'Monitor' })).toBeVisible();
  });
});
