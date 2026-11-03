# Fluxer on Unraid

Unraid® is a registered trademark of Lime Technology, Inc. This application is not affiliated with, endorsed, or sponsored by Lime Technology, Inc.

The web app uses Cloudflare Tunnel and Traefik. Calls connect directly through two router port forwards to the NAS. Callers need no VPN.

The website remains public with Fluxer account authentication. LiveKit detects the public IP address automatically. LAN callers use the same instance.

```text
Web:   Internet -> Cloudflare Tunnel -> Traefik -> Fluxer
Calls: Internet / LAN clients -> router public IP -> NAS LAN address -> LiveKit
```

This project includes the official Fluxer Compose bundle for release `2026.1102.205049`. `UPSTREAM.json` records the source and archive checksum. The three local Compose files add Unraid storage, Traefik, Cloudflare Tunnel, and call access.

## Requirements

- A Cloudflare-managed domain, such as `example.com`.
- Unraid with Docker Engine 25 or newer and Docker Compose 2.24.4 or newer.
- At least 2 CPU cores, 4 GB of memory for Fluxer, and 20 GB of free disk space. Uploads need more space.
- A public WAN address and router forwards for TCP 7881 and UDP 7882 to the NAS LAN address.

Fluxer publishes its [host requirements](https://fluxer.com/selfhost) and [Compose guide](https://docs.fluxer.com/operator/docker-compose/). The Compose version requirement comes from its [override syntax](https://docs.docker.com/reference/compose-file/merge/#replace-value). Install [Compose Manager Plus](https://github.com/mstrhakr/compose_plugin) if the Compose command is absent.

## Deploy

1. Copy this folder to `/mnt/user/appdata/fluxer`. Use a cache pool for appdata if available.

2. Run setup with your domain, certificate email, and NAS LAN address:

   ```bash
   cd /mnt/user/appdata/fluxer
   bash setup.sh chat.example.com admin@example.com 192.168.30.10
   ```

   Setup creates `.env`, empty token files, and data folders. It creates the application secrets once. It refuses to replace an existing `.env` file. The default data path is `/mnt/user/appdata/fluxer/data`.

3. Create a [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/). Copy its connector token. Create a separate DNS API token with **Zone:DNS:Edit** and **Zone:Zone:Read**, scoped to your domain. Traefik uses that token for its [DNS certificate challenge](https://go-acme.github.io/lego/dns/cloudflare/). Save both tokens with the hidden prompts:

   ```bash
   bash set-tokens.sh
   ```

4. Add your tunnel's public hostname with these settings:

   | Setting | Value |
   | --- | --- |
   | Public hostname | `chat.example.com` |
   | Service | `https://traefik:443` |
   | Origin Server Name | `chat.example.com` |
   | HTTP Host Header | `chat.example.com` |
   | No TLS Verify | Off |

   These names must match `FLUXER_DOMAIN` in `.env`. Cloudflare documents the [origin settings](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/origin-parameters/). The connector reaches Traefik through a private Docker network.

5. Start the stack:

   ```bash
   bash start.sh
   docker compose ps
   ```

   Wait for the services and certificate. Open your domain. Read `FLUXER_SETUP_TOKEN` from `.env` to create the first admin account. Choose username sign-in if you do not need email. Configure the router forwards below before the call test.

## Call access

`compose.voice-direct.yml` publishes TCP 7881 and UDP 7882 on the saved NAS LAN address. LiveKit uses STUN, an address discovery protocol, to detect its public IP address. The default is `FLUXER_LIVEKIT_USE_EXTERNAL_IP=true`. Call media bypasses Cloudflare Tunnel. No service publishes a web port on the NAS.

Create these router port forwards:

| WAN port | Protocol | Forward address | Forward port |
| --- | --- | --- | --- |
| 7881 | TCP | `192.168.30.10` | 7881 |
| 7882 | UDP | `192.168.30.10` | 7882 |

Use your actual NAS LAN address. Keep each external and internal port the same. UniFi documents [port forwarding](https://help.ui.com/hc/en-us/articles/235723207-UniFi-Gateway-Port-Forwarding). Test a call from a separate internet connection after the forwards are active.

LAN callers use the gateway's public address through hairpin NAT. UniFi enables [hairpin NAT](https://help.ui.com/hc/en-us/articles/30202160464023-Hairpin-NAT-in-UniFi) by default. If only LAN calls fail, check that behavior on your router.

If the gateway lacks a public WAN address, resolve double NAT or carrier-grade NAT before the call test. An upstream router may also need the same forwards. Carrier-grade NAT may require a public address from your ISP. See [UniFi public access guidance](https://help.ui.com/hc/en-us/articles/30076583334935-Setting-Up-Public-Access-to-Local-Resources-in-UniFi).

LiveKit documents its [call ports](https://docs.livekit.io/transport/self-hosting/ports-firewall/).

## Cloudflare settings

Enable WebSockets. Disable Rocket Loader and HTML caching for this hostname. Exclude Fluxer's API and WebSocket routes from browser challenges or external login screens. Use Fluxer's own account authentication. See the [Fluxer proxy guide](https://docs.fluxer.com/operator/reverse-proxy/).

Cloudflare limits uploads before they reach Fluxer. Free and Pro plans currently limit each upload to 100 MB. See [Cloudflare upload limits](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/4xx-client-error/error-413/).

## VPN routing and certificates

Cloudflare Tunnel needs outbound TCP and UDP port 7844 to its [published tunnel addresses](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/tunnel-with-firewall/). If an outbound VPN blocks this traffic, add a WAN exception for only those addresses and port 7844. Keep the VPN route for other NAS traffic.

LiveKit uses STUN to detect the public address. An outbound VPN can make it announce the VPN exit address instead of the gateway's WAN address. If STUN finds the VPN exit, set these values in `.env`:

```dotenv
FLUXER_LIVEKIT_NODE_IP=<WANIPv4>
FLUXER_LIVEKIT_USE_EXTERNAL_IP=false
```

Replace `<WANIPv4>` with the gateway's public IPv4 address. Apply the change with `docker compose up -d --no-deps livekit`. Update this address when the gateway's WAN address changes. Test the return route for call media from a separate internet connection. A destination-port exception for 7882 does not cover replies to clients on random ports. Keep other NAS applications on their existing VPN route.

Some VPNs block direct queries to authoritative DNS servers. The ingress file uses these Traefik options:

```text
--certificatesresolvers.dns-cloudflare.acme.dnschallenge.propagation.disableanschecks=true
--certificatesresolvers.dns-cloudflare.acme.dnschallenge.propagation.requireallrns=true
```

Traefik checks the challenge TXT record through all configured recursive resolvers instead. The certificate authority still validates the challenge. HTTPS certificate verification remains enabled. See [Traefik's DNS challenge options](https://doc.traefik.io/traefik/reference/install-configuration/tls/certificate-resolvers/acme/).

During testing, cached DNS misses behind an outbound VPN lasted longer than the default 120-second wait. The ingress file sets these environment variables for Traefik:

```dotenv
CLOUDFLARE_PROPAGATION_TIMEOUT=3600
CLOUDFLARE_POLLING_INTERVAL=10
```

This allows up to 3600 seconds for propagation, with a check every 10 seconds. Recursive TXT checks and certificate authority validation remain enabled. See [Lego's Cloudflare configuration](https://go-acme.github.io/lego/dns/cloudflare/#additional-configuration). Future certificate renewal through the VPN alone remains untested.

## Storage and updates

All eight Docker volumes use bind mounts under `FLUXER_DATA_DIR`. Traefik stores its certificates in that folder too. Keep `.env` and `secrets/` with your backups. Keep the database and application keys unchanged after first use.

The native plugin upgrades a known managed `compose.ingress.yml` during **Start Fluxer**. It preserves custom ingress files and stops for a manual merge. This upgrade does not change the database, application keys, or tokens.

Before an update, stop the stack with `docker compose stop`. Back up the complete project and data folders. Copy the new official release bundle into the project. Keep the local Compose files and secrets. Compare the new LiveKit configuration with `compose.voice-direct.yml`. Start the stack with `bash start.sh`.

`FLUXER_TUNNEL_SUBNET` defaults to `172.30.90.0/24`. Change it before first start if that range overlaps another network. If the NAS address changes, update `FLUXER_NAS_IP`, the router forwards, and the containers.

## Checks

Local checks cover the upstream archive checksum, script syntax, secret creation, key formats, and protection against a second setup. The merged Compose configuration binds both call ports to the saved NAS address.

The beta `2026.11.03.6` management update installed on Unraid 7.3.4. The Settings page and 21 container health checks passed. The application runtime remains unchanged from the deployment tested with beta `2026.11.03.5`. The public HTTPS setup wizard loads. These public checks passed:

| Check | Observed result |
| --- | --- |
| `/.well-known/fluxer` | HTTP 200 |
| `/api/_health` | HTTP 200 |
| `/_ready` | HTTP 200 |
| `/gateway` WebSocket | HTTP 101, then opcode 10 Hello with a 41250 ms heartbeat interval |

The operator reported successful voice and video calls. Text chat remains unconfirmed after a possible desktop delay. These reports are separate from the public checks above. Future certificate renewal through the VPN alone remains untested. Community Applications submission is pending manual review. Approval and an Apps listing are not confirmed.
