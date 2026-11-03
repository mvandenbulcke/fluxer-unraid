#!/usr/bin/env bash
set -euo pipefail
umask 077

fail() { printf '%s\n' "$*" >&2; exit 1; }

if [[ $# != 3 ]]; then
  fail 'Usage: bash setup.sh chat.example.com admin@example.com 100.101.102.103'
fi

domain=$1
email=$2
vpn_ip=$3
[[ ${#domain} -le 253 && "$domain" == *.* && "$domain" != *[!a-z0-9.-]* ]] || fail 'Enter a lowercase domain without a scheme, port, or path.'
IFS=. read -r -a domain_labels <<< "$domain"
for label in "${domain_labels[@]}"; do
  [[ -n "$label" && ${#label} -le 63 && "$label" != -* && "$label" != *- ]] || fail 'The domain contains an invalid label.'
done
[[ "$domain" != *. && "$domain" != *..* ]] || fail 'The domain contains an empty label.'
[[ "$email" == ?*@?*.?* && "$email" != *[!a-zA-Z0-9@._+%-]* ]] || fail 'Enter an email address for certificate notices.'
[[ "$vpn_ip" =~ ^100\.([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})$ ]] || fail 'Enter the Tailscale IPv4 address of the NAS.'
octet2=$((10#${BASH_REMATCH[1]}))
octet3=$((10#${BASH_REMATCH[2]}))
octet4=$((10#${BASH_REMATCH[3]}))
(( octet2 >= 64 && octet2 <= 127 && octet3 <= 255 && octet4 <= 255 )) || fail 'The Tailscale address must be in 100.64.0.0/10.'

command -v openssl >/dev/null || fail 'Install OpenSSL before setup.'
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
cd "$script_dir"
[[ ! -e .env && ! -L .env ]] || fail 'The .env file exists. Keep it. Setup does not replace existing keys.'
data_dir=${FLUXER_DATA_DIR:-$script_dir/data}
[[ "$data_dir" == /* && "$data_dir" != / && "$data_dir" != *[\'$'\r\n']* ]] || fail 'Use a dedicated absolute data path without apostrophes or line breaks.'
for volume in edge-data edge-config postgres-data valkey-data nats-data meilisearch-data seaweedfs-data media-proxy-tmp traefik-acme; do
  if [[ -d "$data_dir/$volume" ]] && [[ -n "$(ls -A -- "$data_dir/$volume")" ]]; then
    fail 'The data folder contains files. Restore the original .env file before you start Fluxer.'
  fi
done

work_dir=$(mktemp -d "$script_dir/.setup.XXXXXXXX")
trap 'rm -rf -- "$work_dir"' EXIT
openssl ecparam -name prime256v1 -genkey -noout -out "$work_dir/vapid.pem"
vapid_public=$(openssl ec -in "$work_dir/vapid.pem" -pubout -outform DER 2>/dev/null | tail -c 65 | openssl base64 -A | tr '/+' '_-' | tr -d '=')
vapid_private=$(openssl ec -in "$work_dir/vapid.pem" -outform DER 2>/dev/null | tail -c +8 | head -c 32 | openssl base64 -A | tr '/+' '_-' | tr -d '=')
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -outform DER -out "$work_dir/activitypub.der" 2>/dev/null

while IFS= read -r line || [[ -n "$line" ]]; do
  [[ -n "$line" && "$line" != \#* ]] || continue
  key=${line%%=*}
  value=${line#*=}
  case "$key" in
    FLUXER_DOMAIN) value=$domain ;;
    FLUXER_SETUP_TOKEN|POSTGRES_PASSWORD|MEILI_MASTER_KEY|FLUXER_S3_SECRET_KEY|LIVEKIT_API_SECRET|FLUXER_SUDO_MODE_SECRET|FLUXER_CONNECTION_INITIATION_SECRET|FLUXER_PROFILE_PSEUDONYM_SECRET|FLUXER_GATEWAY_RPC_AUTH_TOKEN|FLUXER_ERLANG_COOKIE|FLUXER_MEDIA_PROXY_SECRET_KEY|FLUXER_ADMIN_SECRET_KEY_BASE|FLUXER_ADMIN_OAUTH_CLIENT_SECRET)
      value=$(openssl rand -hex 32) ;;
    FLUXER_MEDIA_PROXY_UPLOAD_RELAY_SECRET_BASE64) value=$(openssl rand -base64 32) ;;
    FLUXER_ACTIVITYPUB_SIGNING_KEY_BASE64) value=$(openssl base64 -A -in "$work_dir/activitypub.der") ;;
    FLUXER_VAPID_PUBLIC_KEY) value=$vapid_public ;;
    FLUXER_VAPID_PRIVATE_KEY) value=$vapid_private ;;
  esac
  printf "%s='%s'\n" "$key" "$value"
done < .env.example > "$work_dir/env"

cat >> "$work_dir/env" <<EOF
COMPOSE_FILE=docker-compose.yml:docker-compose.proxy.yml:compose.unraid.yml:compose.ingress.yml:compose.voice-vpn.yml
FLUXER_DATA_DIR='$data_dir'
FLUXER_ACME_EMAIL='$email'
FLUXER_VPN_IP='$vpn_ip'
FLUXER_LIVEKIT_NODE_IP='$vpn_ip'
FLUXER_LIVEKIT_USE_EXTERNAL_IP=false
FLUXER_LIVEKIT_TURN_SERVERS='[]'
TRAEFIK_NETWORK=fluxer-proxy
FLUXER_TUNNEL_SUBNET=172.30.90.0/24
EOF

if [[ ! -d "$data_dir" ]]; then
  mkdir -p -m 700 -- "$data_dir"
fi
mkdir -p -m 755 certs ca caddy.d/sites
for volume in edge-data edge-config postgres-data valkey-data nats-data meilisearch-data seaweedfs-data media-proxy-tmp; do
  mkdir -p -m 755 -- "$data_dir/$volume"
done
mkdir -p -m 700 -- "$data_dir/traefik-acme" secrets
for token in cloudflare-dns-token cloudflare-tunnel-token; do
  if [[ ! -e "secrets/$token" ]]; then
    : > "secrets/$token"
  fi
done
chmod 700 secrets
chmod 600 secrets/cloudflare-dns-token secrets/cloudflare-tunnel-token
(set -o noclobber; cat "$work_dir/env" > .env)
printf '%s\n' 'Created .env and the data folders.' 'Next: run bash set-tokens.sh to save your Cloudflare tokens.'
