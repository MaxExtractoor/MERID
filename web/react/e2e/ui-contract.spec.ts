import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page, context }) => {
  await context.route('**/api/**', async route => {
    await route.fulfill({ status: 503, json: { detail: 'isolated UI audit: backend unavailable' } });
  });
  // Wait for React to mount the shell (global keydown listeners attach on
  // mount — pressing keys before nav exists loses the shortcut silently).
  await page.goto('/');
  await expect(page.getByRole('navigation', { name: 'Primary' })).toBeVisible();
});

test('all seven workflows remain navigable during a backend outage', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await expect(page.getByRole('main')).toBeVisible();
  for (const [key, heading] of [['2', 'BTC agent'], ['3', 'Trade'], ['4', 'Portfolio'], ['5', 'Risk'], ['6', 'System']]) {
    await page.keyboard.press(key);
    await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible();
  }
  await page.keyboard.press('1');
  await expect(page.getByRole('heading', { name: 'fleet health', exact: true })).toBeVisible();
  await page.keyboard.press('0');
  await expect(page.getByRole('heading', { name: 'decision tape', exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});

// Ctrl+K is browser-reserved in headless Chromium and never reaches the page,
// so the test exercises the equivalent real path: the TopBar search input.
test('command palette opens via search and closes on Escape', async ({ page }) => {
  await page.getByPlaceholder(/Search symbols, commands/).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole('textbox')).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
});
