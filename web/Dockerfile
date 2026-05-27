# syntax=docker/dockerfile:1.7
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm cache clean --force && npm ci --no-audit --no-fund
RUN node -e "const v=require('./node_modules/picomatch/package.json').version; if(v!=='4.0.4'){process.exit(1)} console.log('picomatch',v,'OK')"

FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1 \
    API_BASE_URL=http://api:8000
RUN npm run build
RUN echo "=== picomatch package.json files in standalone ===" && \
    find .next/standalone -name "package.json" -path "*/picomatch/*" -exec sh -c 'echo "$1:"; cat "$1"' _ {} \; && \
    echo "=== checking for 4.0.3 ===" && \
    ! grep -r '"version": "4.0.3"' .next/standalone/node_modules/picomatch/ 2>/dev/null && \
    echo "standalone picomatch OK"

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000

RUN addgroup -S app && adduser -S app -G app
USER app

COPY --from=builder --chown=app:app /app/.next/standalone ./
COPY --from=builder --chown=app:app /app/.next/static ./.next/static
COPY --from=builder --chown=app:app /app/public ./public

EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD wget -qO- http://localhost:3000 >/dev/null 2>&1 || exit 1

CMD ["node", "server.js"]
