FROM node:20-bookworm-slim AS node
FROM eclipse-temurin:21-jre
COPY --from=node /usr/local/bin/node /usr/local/bin/node
RUN apt-get update && apt-get install -y --no-install-recommends python3 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY package.json /app/package.json
COPY --from=node /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN node /usr/local/lib/node_modules/npm/bin/npm-cli.js install --omit=dev --no-audit --no-fund
COPY chem_mcp.py bot.js selftest.py Dockerfile /app/
COPY *.zip /app/zips/
ENV CHEM_MC_DIR=/data/mcserver CHEM_HEAP=256M
ENV JAVA_TOOL_OPTIONS="-XX:+UseSerialGC -XX:TieredStopAtLevel=1 -XX:ReservedCodeCacheSize=48m -XX:MaxMetaspaceSize=128m -Xss512k"
CMD ["python3", "/app/selftest.py"]
