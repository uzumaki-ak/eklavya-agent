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

# Templates in this directory get envsubst applied at container start.
COPY nginx.conf.template /etc/nginx/templates/default.conf.template

# Substitute ONLY this variable, so nginx's own $uri/$host survive.
ENV NGINX_ENVSUBST_FILTER=API_UPSTREAM
# Compose default; Railway overrides with the private-network hostname.
ENV API_UPSTREAM=http://api:8000

# nginx:alpine ships an unprivileged `nginx` user; give it the dirs it needs
# so the server can run without root. Port 3000 is >1024, so no privileged bind.
RUN touch /var/run/nginx.pid \
    && chown -R nginx:nginx /var/run/nginx.pid /var/cache/nginx /usr/share/nginx/html /etc/nginx/conf.d
USER nginx

EXPOSE 3000
