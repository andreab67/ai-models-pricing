# syntax=docker/dockerfile:1.7
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
# picomatch is overridden for CVE-2026-33671; fail the build if the resolved
# version ever drops below the fixed release.
RUN node -e "const [a,b,c]=require('./node_modules/picomatch/package.json').version.split('.').map(Number); const ok=a>4||(a===4&&(b>0||c>=4)); if(!ok){console.error('picomatch too old');process.exit(1)} console.log('picomatch OK')"

FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
# API_BASE_URL is read at request time by src/app/api/[...path]/route.ts, so
# the Deployment/compose value takes effect without rebuilding the image.
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0 \
    API_BASE_URL=http://api:8000

# The base image's `node` user is UID/GID 1000, matching the pods'
# securityContext (runAsUser/runAsGroup 1000).
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static
COPY --from=builder --chown=node:node /app/public ./public
USER 1000:1000

EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD wget -qO- http://localhost:3000 >/dev/null 2>&1 || exit 1

CMD ["node", "server.js"]
