# Build the static bundle, then serve it behind nginx which also proxies /api.
# Same-origin by design: no API URL is ever baked into the JavaScript.

FROM node:22-alpine AS build
WORKDIR /app
# `npm ci` when a lockfile exists (reproducible), else fall back to install.
COPY package.json package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html

# Templates here get envsubst applied at container start.
COPY nginx.conf.template /etc/nginx/templates/default.conf.template

# Exports NGINX_RESOLVER before templates are rendered, so nginx can re-resolve
# upstreams at request time instead of caching them at startup.
COPY docker-entrypoint.d/10-resolver.envsh /docker-entrypoint.d/10-resolver.envsh
RUN chmod +x /docker-entrypoint.d/10-resolver.envsh

# Substitute ONLY these, so nginx's own $uri/$host/$remote_addr survive.
ENV NGINX_ENVSUBST_FILTER="^(API_UPSTREAM|PORT|NGINX_RESOLVER)$"
# Compose defaults; the platform overrides these at runtime.
ENV API_UPSTREAM=http://api:8000
ENV PORT=3000

# nginx:alpine ships an unprivileged `nginx` user; give it the dirs it needs
# so the server can run without root. Port 3000 is >1024, so no privileged bind.
RUN touch /var/run/nginx.pid \
    && chown -R nginx:nginx /var/run/nginx.pid /var/cache/nginx /usr/share/nginx/html /etc/nginx/conf.d
USER nginx

EXPOSE 3000
