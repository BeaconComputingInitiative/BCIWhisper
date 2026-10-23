# BEACON COMPUTING INITIATIVE
# BCIWhisper Render Broadcast Gateway
# Developer Seal: CJB-DEV-2026
# File integrity: SHA-256 calculated during release packaging
FROM oven/bun:1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY services/broadcast-gateway/package.json ./package.json
COPY services/broadcast-gateway/src ./src
ENV BCI_HOST=0.0.0.0
ENV BCI_PORT=10000
ENV BCI_DB_PATH=/tmp/bci_gateway.db
EXPOSE 10000
CMD ["bun", "run", "src/server.ts"]
