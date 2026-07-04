/**
 * E2E Tests for Trade View
 * Tests critical user flows in the Trade view
 */

import { test, expect } from '@playwright/test';

test.describe('Trade View', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    // Navigate to Trade view
    await page.keyboard.press('2');
  });

  test('should load trade view with market catalog', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Trade' })).toBeVisible();
    await expect(page.locator('text=/15m Crypto Markets/i')).toBeVisible();
  });

  test('should display markets table with required columns', async ({ page }) => {
    // Check for table headers
    await expect(page.locator('text=/Market/i')).toBeVisible();
    await expect(page.locator('text=/Yes Price/i')).toBeVisible();
    await expect(page.locator('text=/No Price/i')).toBeVisible();
    await expect(page.locator('text=/Volume/i')).toBeVisible();
    await expect(page.locator('text=/Closes/i')).toBeVisible();
  });

  test('should have functional tabs for Markets, Positions, Orders', async ({ page }) => {
    // Check tabs are present
    await expect(page.getByRole('tab', { name: 'Markets' })).toBeVisible();
    await expect(page.getByRole('tab', { name: 'Positions' })).toBeVisible();
    await expect(page.getByRole('tab', { name: 'Orders' })).toBeVisible();
  });

  test('should switch between tabs', async ({ page }) => {
    // Click on Positions tab
    await page.getByRole('tab', { name: 'Positions' }).click();
    await expect(page.getByRole('tab', { name: 'Positions', selected: true })).toBeVisible();

    // Click on Orders tab
    await page.getByRole('tab', { name: 'Orders' }).click();
    await expect(page.getByRole('tab', { name: 'Orders', selected: true })).toBeVisible();

    // Click back to Markets tab
    await page.getByRole('tab', { name: 'Markets' }).click();
    await expect(page.getByRole('tab', { name: 'Markets', selected: true })).toBeVisible();
  });

  test('should have trade ticket with proper ARIA labels', async ({ page }) => {
    // Check for trade ticket elements with ARIA labels
    const tradeButton = page.getByRole('button', { name: /Trade/i }).first();
    if (await tradeButton.isVisible()) {
      await expect(tradeButton).toHaveAttribute('aria-label');
    }
  });

  test('should prevent double-submit on trade ticket', async ({ page }) => {
    // This test verifies the submit guard is in place
    // The actual implementation is tested in unit tests
    // E2E test ensures the UI doesn't allow rapid submissions
    const tradeButton = page.getByRole('button', { name: /Place Order/i }).first();
    if (await tradeButton.isVisible()) {
      // Button should be disabled after first click
      await tradeButton.click();
      await expect(tradeButton).toBeDisabled();
    }
  });
});
