FROM node:24.12.0-alpine AS build
WORKDIR /app
RUN npm install --global pnpm@11.19.0
COPY apps/web/package.json apps/web/pnpm-lock.yaml apps/web/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY apps/web ./
ARG TRAVEL_API_ORIGIN=http://api:8000
ENV TRAVEL_API_ORIGIN=$TRAVEL_API_ORIGIN NEXT_TELEMETRY_DISABLED=1
RUN pnpm run build

FROM node:24.12.0-alpine
WORKDIR /app
ENV NODE_ENV=production HOSTNAME=0.0.0.0 PORT=3000 NEXT_TELEMETRY_DISABLED=1
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
USER node
CMD ["node", "server.js"]
