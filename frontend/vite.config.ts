import { defineConfig } from 'vitest/config';
import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';

export default defineConfig({
	plugins: [
		sveltekit({
			compilerOptions: {
				// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
				runes: ({ filename }) =>
					filename.split(/[/\\]/).includes('node_modules') ? undefined : true
			},
			// SPA: Caddy serves the build and falls back to index.html
			adapter: adapter({ fallback: 'index.html' })
		})
	],
	// model-viewer + three.js (~1 MB) is one lazily loaded chunk, only for the 3D screen
	build: { chunkSizeWarningLimit: 1200 },
	server: {
		// dev without Caddy: proxy /api to `uvicorn --port 8000` (or API_TARGET)
		host: true,
		allowedHosts: true, // reached through Caddy under the LAN host name
		proxy: { '/api': { target: process.env.API_TARGET ?? 'http://localhost:8000', rewrite: (p) => p.replace(/^\/api/, '') } }
	},
	test: {
		expect: { requireAssertions: true },
		passWithNoTests: true,
		projects: [
			{
				extends: './vite.config.ts',
				test: {
					name: 'server',
					environment: 'node',
					include: ['src/**/*.{test,spec}.{js,ts}'],
					exclude: ['src/**/*.svelte.{test,spec}.{js,ts}']
				}
			}
		]
	}
});
