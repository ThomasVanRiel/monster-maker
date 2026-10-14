# Caddy + the built SvelteKit app. Build context is the repo root.
FROM node:24-alpine AS build
RUN npm install -g pnpm@11.28.5
WORKDIR /app
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend ./
RUN pnpm build

FROM caddy:2-alpine
COPY web/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/build /srv
