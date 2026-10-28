# ViewMagnet Frontend Dockerfile
# Multi-stage build for development and production

# ============================================================
# Stage 1: Base with dependencies
# ============================================================
FROM node:20-alpine AS base

WORKDIR /app

# Install pnpm
RUN corepack enable && corepack prepare pnpm@latest --activate

# Copy package files and patches (patches must be present before install)
COPY package.json pnpm-lock.yaml* ./
COPY patches/ ./patches/

# Install dependencies
RUN pnpm install

# ============================================================
# Stage 2: Development
# ============================================================
FROM base AS development

WORKDIR /app

# Copy source code
COPY . .

# Expose Vite dev server port
EXPOSE 3000

# Start development server
CMD ["pnpm", "dev", "--host", "0.0.0.0", "--port", "3000"]

# ============================================================
# Stage 3: Builder (for production)
# ============================================================
FROM base AS builder

WORKDIR /app

# Copy source code
COPY . .

# Build arguments for environment variables
ARG VITE_API_URL=/api
ENV VITE_API_URL=$VITE_API_URL

# Build the application
RUN pnpm build

# ============================================================
# Stage 4: Production with Nginx
# ============================================================
FROM nginx:alpine AS production

# Copy custom nginx config and remove the default that shows the welcome page
COPY nginx.conf /etc/nginx/nginx.conf
RUN rm -f /etc/nginx/conf.d/default.conf

# Copy built assets from builder (vite outputs to dist/public per vite.config.ts)
COPY --from=builder /app/dist/public /usr/share/nginx/html

# Add healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD wget --quiet --tries=1 --spider http://localhost:80/health || exit 1

# Expose port
EXPOSE 80

# Start nginx
CMD ["nginx", "-g", "daemon off;"]
