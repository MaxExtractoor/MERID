import React from 'react'
import ReactDOM from 'react-dom/client'
import './index.css'

const rootElement = document.getElementById('root');

if (rootElement) {
  try {
    const { default: App } = await import('./App');
    ReactDOM.createRoot(rootElement).render(
      <React.StrictMode>
        <App />
      </React.StrictMode>,
    );
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : JSON.stringify(err, null, 2) || String(err);
    const stack = err instanceof Error ? err.stack : new Error().stack;
    rootElement.innerHTML = `
      <div style="padding:2rem;font-family:monospace;color:#f87171;background:#0f172a;min-height:100vh">
        <h1 style="font-size:1.5rem;margin-bottom:1rem">⚠ MERID failed to start</h1>
        <pre style="white-space:pre-wrap;font-size:0.85rem;color:#fbbf24">${msg}</pre>
        <pre style="white-space:pre-wrap;font-size:0.75rem;color:#94a3b8;margin-top:1rem">${stack}</pre>
      </div>`;
    console.error('MERID boot error:', err, 'type:', typeof err, 'keys:', err && typeof err === 'object' ? Object.keys(err as Record<string, unknown>) : 'N/A');
  }
}
