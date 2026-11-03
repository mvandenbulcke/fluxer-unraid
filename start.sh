#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
[[ -f .env ]] || { printf '%s\n' 'Run setup.sh first.' >&2; exit 1; }
for name in cloudflare-dns-token cloudflare-tunnel-token; do
  [[ -s "secrets/$name" ]] || { printf '%s\n' 'Run bash set-tokens.sh before you start Fluxer.' >&2; exit 1; }
done
docker compose config --quiet
docker compose up -d
printf '%s\n' 'Check startup with: docker compose ps' 'Read README.md for the tunnel hostname and first admin account.'
