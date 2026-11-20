import { defineConfig } from 'vite';

// Served at the root of its own domain by default, which is what Cloudflare Pages does. GitHub Pages serves
// a project repo under /<repo>/ instead, and Vite has to know that prefix at build time to rewrite the asset
// urls in index.html, so the deploy workflow passes it in as PAGES_BASE.
export default defineConfig({ base: process.env.PAGES_BASE || '/' });
