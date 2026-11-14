// Build the static frontend bundle for Render (or any static host).
//
// The dashboard is a single HTML file plus a small runtime configuration file.
// This script copies the page to dist/ and writes dist/config.js from the
// API_BASE_URL environment variable, so the static site knows where the Python
// API lives without bundling a framework or running a build toolchain.
import { copyFileSync, mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const out = join(root, 'dist');
const configured = (process.env.API_BASE_URL || '').trim().replace(/\/+$/, '');

if (!configured && process.env.RENDER) {
    throw new Error('API_BASE_URL must be set for a Render static-site build.');
}

if (configured) {
    let parsed;
    try {
        parsed = new URL(configured);
    } catch {
        throw new Error(`API_BASE_URL is not a valid URL: ${configured}`);
    }
    if (!['http:', 'https:'].includes(parsed.protocol) || parsed.pathname !== '/'
            || parsed.search || parsed.hash || parsed.username || parsed.password) {
        throw new Error(`API_BASE_URL must be a bare http(s) origin: ${configured}`);
    }
}

mkdirSync(out, { recursive: true });
copyFileSync(join(root, 'src/axiom/web/index.html'), join(out, 'index.html'));
writeFileSync(join(out, 'config.js'), `window.AXIOM_API_BASE = ${JSON.stringify(configured)};\n`);

console.log(`Static frontend written to ${out}`);
console.log(`API base: ${configured || '(same origin)'}`);
