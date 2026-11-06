FROM node:20-bookworm-slim AS node
FROM eclipse-temurin:21-jre
COPY --from=node /usr/local/bin/node /usr/local/bin/node
RUN apt-get update && apt-get install -y --no-install-recommends python3 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY package.json /app/package.json
COPY --from=node /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN node /usr/local/lib/node_modules/npm/bin/npm-cli.js install --omit=dev --no-audit --no-fund
COPY chem_mcp.py bot.js Dockerfile world.zip* /app/
ENV CHEM_MC_DIR=/data/mcserver CHEM_WORLD_ZIP=/app/world.zip CHEM_HEAP=1400M
CMD ["python3", "/app/chem_mcp.py", "--http"]
