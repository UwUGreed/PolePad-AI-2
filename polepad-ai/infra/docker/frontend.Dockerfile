FROM node:20-alpine AS deps
WORKDIR /app
COPY GridstormFrontEnd/package*.json ./
RUN npm ci

FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY GridstormFrontEnd/ ./
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

# harmless if unused; required by some auth setups
ENV SESSION_SECRET=dev-change-me

VOLUME ["/app/data"]

COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/.next/standalone ./

EXPOSE 3000
CMD ["node","server.js"]
