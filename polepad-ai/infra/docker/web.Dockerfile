FROM node:20-alpine AS builder

ARG FRONTEND_DIR=apps/web
WORKDIR /app

COPY ${FRONTEND_DIR}/package*.json ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

COPY ${FRONTEND_DIR}/ ./
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# Production image
FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV HOSTNAME=0.0.0.0
ENV PORT=3000

COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

EXPOSE 3000
CMD ["node", "server.js"]
