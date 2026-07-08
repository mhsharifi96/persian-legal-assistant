# Next.js web frontend (the "web-ui" service in docker-compose.yml).
FROM node:20-alpine AS builder
WORKDIR /app

# Install dependencies from the lockfile (cached until it changes).
COPY package.json package-lock.json ./
RUN npm ci

# Build. SITE_URL is baked into robots.txt/sitemap at build time.
ARG SITE_URL=http://localhost:3000
ENV SITE_URL=${SITE_URL}
COPY . .
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production

COPY --from=builder /app/package.json /app/package-lock.json ./
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/next.config.mjs ./next.config.mjs
COPY --from=builder /app/public ./public

RUN addgroup -S app && adduser -S app -G app && chown -R app:app /app
USER app

EXPOSE 3000
CMD ["npm", "run", "start"]
