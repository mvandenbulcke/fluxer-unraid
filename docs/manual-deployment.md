# Fluxer on Unraid

The web app uses Cloudflare Tunnel and Traefik. Calls use the private Tailscale network. This design needs no router port forwarding.

The website remains public with Fluxer account authentication. Every caller needs Tailscale access to the NAS. Traefik handles the web app. LiveKit handles call media directly through the VPN.

```text
Web:   Internet -> Cloudflare Tunnel -> Traefik -> Fluxer
Calls: Tailscale clients -> NAS Tailscale address -> LiveKit
```

This project includes the official Fluxer Compose bundle for release `2026.1102.205049`. `UPSTREAM.json` records the source and archive checksum. The three local Compose files add Unraid storage, Traefik, Cloudflare Tunnel, and VPN access for calls.

## Requirements

- A Cloudflare-managed domain, such as `example.com`.
- Unraid with Docker Engine 25 or newer and Docker Compose 2.24.4 or newer.
- At least 2 CPU cores, 4 GB of memory for Fluxer, and 20 GB of free disk space. Uploads need more space.
- The Tailscale host plugin on Unraid and Tailscale on each caller's device.

Fluxer publishes its [host requirements](https://fluxer.com/selfhost) and [Compose guide](https://docs.fluxer.com/operator/docker-compose/). The Compose version requirement comes from its [override syntax](https://docs.docker.com/reference/compose-file/merge/#replace-value).

## Deploy

1. Install **Tailscale (Plugin)** from Unraid Apps. Connect the NAS and each caller's device to your Tailscale network. Read the [Tailscale Unraid guide](https://tailscale.com/docs/integrations/unraid). Find the NAS address with `tailscale ip -4`. Use the host plugin with Docker bridge networks. Start Tailscale before this stack.

2. Copy this folder to `/mnt/user/appdata/fluxer`. Use a cache pool for appdata if available. Install [Compose Manager Plus](https://github.com/mstrhakr/compose_plugin) if the Compose command is absent. Run this command with your domain, certificate email, and NAS Tailscale address:

   ```bash
   cd /mnt/user/appdata/fluxer
   bash setup.sh chat.example.com admin@example.com 100.101.102.103
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

   Wait for the services and certificate. Open your domain. Read `FLUXER_SETUP_TOKEN` from `.env` to create the first admin account. Choose username sign-in if you do not need email. Test a call between two devices on different networks with Tailscale connected.

## Call access

`compose.voice-vpn.yml` publishes only TCP 7881 and UDP 7882 on the NAS Tailscale address. It forces LiveKit to announce that address. No service publishes a web port on the NAS. Keep the router's forwarding rules empty for this stack.

Permit callers to reach the NAS through Tailscale on TCP 7881 and UDP 7882. A subnet route or exit node is unnecessary. Users without that VPN access can open the website, but calls cannot connect.

Tailscale can relay traffic when direct connections fail. Relayed calls can have lower throughput. See [Tailscale firewall guidance](https://tailscale.com/docs/reference/faq/firewall-ports). The call configuration uses Fluxer's [LiveKit address settings](https://docs.fluxer.com/operator/environment/#fluxer_livekit_node_ip).

## Cloudflare settings

Enable WebSockets. Disable Rocket Loader and HTML caching for this hostname. Exclude Fluxer's API and WebSocket routes from browser challenges or external login screens. Use Fluxer's own account authentication. See the [Fluxer proxy guide](https://docs.fluxer.com/operator/reverse-proxy/).

Cloudflare limits uploads before they reach Fluxer. Free and Pro plans currently limit each upload to 100 MB. See [Cloudflare upload limits](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/4xx-client-error/error-413/).

## Storage and updates

All eight Docker volumes use bind mounts under `FLUXER_DATA_DIR`. Traefik stores its certificates in that folder too. Keep `.env` and `secrets/` with your backups. Keep the database and application keys unchanged after first use.

Before an update, stop the stack with `docker compose stop`. Back up the complete project and data folders. Copy the new official release bundle into the project. Keep the local Compose files and secrets. Compare the new LiveKit configuration with `compose.voice-vpn.yml`. Start the stack with `bash start.sh`.

`FLUXER_TUNNEL_SUBNET` defaults to `172.30.90.0/24`. Change it before first start if that range overlaps another network. If the Tailscale address changes, update `FLUXER_VPN_IP` and recreate the containers.

## Local checks

The archive checksum matches the official release. Script syntax, secret creation, key formats, and protection against a second setup passed. The merged Compose configuration binds both call ports only to the VPN address.

The local Docker engine is unavailable. Container startup, certificate creation, Unraid storage behavior, and live calls still need checks on the NAS.
