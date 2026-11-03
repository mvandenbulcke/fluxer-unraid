#!/usr/bin/env bash
set -euo pipefail
umask 077
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
[[ -d secrets && -f .env ]] || { printf '%s\n' 'Run setup.sh first.' >&2; exit 1; }
for name in cloudflare-dns-token cloudflare-tunnel-token; do
  if [[ -s "secrets/$name" ]]; then
    printf 'Kept secrets/%s.\n' "$name"
    continue
  fi
  read -r -s -p "Paste the $name: " value
  printf '\n'
  [[ -n "$value" ]] || { printf '%s\n' 'The token cannot be empty.' >&2; exit 1; }
  printf '%s' "$value" > "secrets/$name"
  chmod 600 "secrets/$name"
  unset value
done
printf '%s\n' 'Saved the token files. Next: run bash start.sh.'
