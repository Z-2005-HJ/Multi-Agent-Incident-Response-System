FROM node:22-alpine AS build

WORKDIR /app

ARG VITE_API_BASE_URL=/api
ARG VITE_DEMO_API_TOKEN=
ARG VITE_API_TOKEN=
ARG VITE_RELEASE_APPROVAL_ID=
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ENV VITE_DEMO_API_TOKEN=$VITE_DEMO_API_TOKEN
ENV VITE_API_TOKEN=$VITE_API_TOKEN
ENV VITE_RELEASE_APPROVAL_ID=$VITE_RELEASE_APPROVAL_ID

COPY package.json package-lock.json ./
RUN npm ci

COPY index.html tsconfig.json vite.config.js ./
COPY src ./src
RUN npm run build

FROM nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
