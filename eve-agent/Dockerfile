# Project-agent container — the same artifact a Railway/Fly deploy would run.
# eve start serves the built Nitro output; PORT and --host come from the
# self-hosting guide (eve docs guides/deployment/self-hosting.md).
FROM node:24-alpine
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY tsconfig.json ./
COPY agent ./agent
RUN npx eve build

# Durable-run state must outlive the container (self-hosting checklist):
# compose/deploy mounts a volume at /app/.eve/.workflow-data
CMD ["npx", "eve", "start", "--host", "0.0.0.0"]
