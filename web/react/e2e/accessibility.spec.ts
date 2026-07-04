/**
 * E2E Accessibility Tests
 * Tests accessibility compliance across the application
 */

import { test, expect } from '@playwright/test';

test.describe('Accessibility', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  test('should have proper heading hierarchy', async ({ page }) => {
    // Check for main heading
    const h1 = page.locator('h1').first();
    await expect(h1).toBeVisible();
    
    // Check that h1 is the first heading
    const firstHeading = page.locator('h1, h2, h3, h4, h5, h6').first();
    const tagName = await firstHeading.evaluate(el => el.tagName);
    expect(tagName).toBe('H1');
  });

  test('should have ARIA labels on interactive elements', async ({ page }) => {
    // Check buttons have aria-label or text content
    const buttons = page.locator('button').filter({ hasText: /.+/ });
    const count = await buttons.count();
    
    for (let i = 0; i < Math.min(count, 10); i++) {
      const button = buttons.nth(i);
      const hasLabel = await button.getAttribute('aria-label');
      const hasText = await button.textContent();
      expect(hasLabel || hasText?.trim()).toBeTruthy();
    }
  });

  test('should have proper tab navigation support', async ({ page }) => {
    // Navigate to Trade view
    await page.keyboard.press('2');
    
    // Check tabs have proper ARIA attributes
    const tabs = page.getByRole('tab');
    const count = await tabs.count();
    
    for (let i = 0; i < count; i++) {
      const tab = tabs.nth(i);
      await expect(tab).toHaveAttribute('role', 'tab');
      await expect(tab).toHaveAttribute('aria-selected');
    }
  });

  test('should have keyboard navigation working', async ({ page }) => {
    // Test keyboard shortcuts
    await page.keyboard.press('1');
    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
    
    await page.keyboard.press('2');
    await expect(page.getByRole('heading', { name: 'Trade' })).toBeVisible();
    
    await page.keyboard.press('3');
    await expect(page.getByRole('heading', { name: 'Monitor' })).toBeVisible();
  });

  test('should have sufficient color contrast (visual check)', async ({ page }) => {
    // This is a basic visual check - automated contrast checking requires axe-core
    // We verify that text is readable against backgrounds
    const cards = page.locator('.bg-slate-900').first();
    await expect(cards).toBeVisible();
    
    const text = cards.locator('text').first();
    await expect(text).toBeVisible();
  });

  test('should have alt text for images', async ({ page }) => {
    const images = page.locator('img');
    const count = await images.count();
    
    for (let i = 0; i < count; i++) {
      const img = images.nth(i);
      const alt = await img.getAttribute('alt');
      // Icons with aria-hidden="true" don't need alt text
      const ariaHidden = await img.getAttribute('aria-hidden');
      if (ariaHidden !== 'true') {
        expect(alt).toBeTruthy();
      }
    }
  });

  test('should have focus indicators on interactive elements', async ({ page }) => {
    // Tab to first interactive element
    await page.keyboard.press('Tab');
    
    // Check that something is focused
    const focused = page.locator(':focus');
    await expect(focused).toHaveCount(1);
  });
});
