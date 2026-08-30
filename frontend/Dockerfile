# Multi-stage build for the Next.js frontend (chat UI + /admin dashboard,
# one app -- see app/admin/page.tsx). Runs `next start` in production,
# proxying /api/* to the backend via next.config.mjs's rewrite (BACKEND_URL).
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install

FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# next.config.mjs's rewrites() destination is resolved by `next build`, NOT
# re-read from the environment at `next start` -- so BACKEND_URL has to be
# a build arg, not just a runtime env var on the container. Default matches
# the docker-compose service name/port.
ARG BACKEND_URL=http://api:8000
ENV BACKEND_URL=$BACKEND_URL
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/next.config.mjs ./
COPY --from=builder /app/package.json ./
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/node_modules ./node_modules
EXPOSE 3000
CMD ["npm", "run", "start", "--", "--hostname", "0.0.0.0", "--port", "3000"]
