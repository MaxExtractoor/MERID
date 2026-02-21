/**
 * Stub-detection utilities.
 *
 * Backend endpoints wrapped with `_stub()` include `_stub: true` and
 * `_stub_message` in their JSON response.  These helpers provide a
 * single place to check for that flag so components and guards don't
 * repeat the cast.
 */

/** Returns `true` when `data` came from a stub endpoint. */
export const isStub = (data: unknown): boolean =>
  typeof data === 'object' && data !== null && '_stub' in data && !!(data as Record<string, unknown>)._stub;

/** Extract the human-readable stub message, with a sensible default. */
export const stubMessage = (data: unknown): string =>
  (typeof data === 'object' && data !== null && (data as Record<string, unknown>)._stub_message as string) ||
  'This data is simulated and does not reflect live state.';
