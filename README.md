# Fluxer for Unraid 7

Install and manage Fluxer from **Settings > Fluxer**. This unofficial beta plugin runs the official Fluxer Docker Compose bundle.

The web app uses Cloudflare Tunnel and Traefik. Calls connect directly from the internet through two router port forwards. Callers need no VPN.

Community Applications submission remains on hold. Install the beta through **Plugins > Install Plugin** for testing.

## Install the beta plugin

Forward TCP 7881 and UDP 7882 from your router's WAN interface to the same ports on the NAS. Use the NAS LAN address, such as `192.168.30.10`. See [UniFi port forwarding](https://help.ui.com/hc/en-us/articles/235723207-UniFi-Gateway-Port-Forwarding).

1. Install **Compose Manager Plus** from Unraid Apps.
2. Open **Plugins > Install Plugin**. Enter this release URL:

   ```text
   https://github.com/mvandenbulcke/fluxer-unraid/releases/latest/download/fluxer.plg
   ```

3. Open **Settings > Fluxer**. Enter your domain, certificate email, NAS LAN address, and Cloudflare tokens. Select **Save setup**.
4. Add the domain to your Cloudflare Tunnel. Use `https://traefik:443` as the service. Set **Origin Server Name** and **HTTP Host Header** to your instance domain. Keep **No TLS Verify** off.
5. Select **Start Fluxer**. Wait for healthy services. Select **Open Fluxer**, then **Show setup token** to create the first administrator account.

The page shows missing requirements before setup. Create the [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/) in your own account. Use a separate DNS API token with **Zone:DNS:Edit** and **Zone:Zone:Read**, scoped to your domain. Traefik uses that token for certificates.

## Data and access

The plugin stores the deployment, application keys, uploads, and database under `/mnt/user/appdata/fluxer`. It stores Cloudflare tokens in private files. Setup preserves existing application keys. **Save tokens** updates only the Cloudflare tokens. Select **Start Fluxer** after a token change to apply it.

Calls use TCP 7881 and UDP 7882 on the saved NAS address, such as `192.168.30.10`. Your router forwards internet traffic to those ports. LiveKit detects the public IP address automatically. Call media bypasses Cloudflare Tunnel. The website remains public with Fluxer account authentication.

LAN callers use the same instance. UniFi enables [hairpin NAT](https://help.ui.com/hc/en-us/articles/30202160464023-Hairpin-NAT-in-UniFi) by default so LAN clients can reach the gateway's public address.

Keep browser challenges and external authentication screens off for this hostname. See the [Fluxer proxy guide](https://docs.fluxer.com/operator/reverse-proxy/).

The plugin resumes a stack after Docker starts if you previously selected **Start Fluxer**. **Stop Fluxer** disables that behavior and keeps the data. Plugin removal keeps the containers and appdata. Stop Fluxer before you remove its management plugin.

Back up the complete appdata folder before updates. A plugin update replaces the management code. **Start Fluxer** also upgrades `compose.ingress.yml` if it matches a known managed version. It preserves custom ingress files and stops for a manual merge. Application keys and data remain unchanged. Use the [manual deployment guide](docs/manual-deployment.md) for Fluxer release updates.

## Requirements and checks

Use Unraid 7, Docker Engine 25 or newer, and Docker Compose 2.24.4 or newer. Fluxer requires at least 2 CPU cores, 4 GB of memory, and 20 GB of disk space. Uploads need more space. See [Fluxer's requirements](https://fluxer.com/selfhost).

Direct calls require a public WAN address and the two router port forwards. If the gateway lacks a public WAN address, resolve the upstream NAT before the call test. A NAS that uses an outbound VPN needs additional routing checks. See [VPN routing and certificates](docs/manual-deployment.md#vpn-routing-and-certificates).

The bundled Fluxer release is `2026.1102.205049`. `UPSTREAM.json` records its source and checksum. Local checks cover secret creation, key preservation, call port bindings, and controller behavior. GitHub Actions checks PHP syntax and builds the release package.

Beta `2026.11.03.4` installed on Unraid 7.3.4. The Settings page and 21 container health checks passed. Full web, chat, and call tests remain.

Source code uses the [AGPL-3.0-or-later license](LICENSE). This project does not represent Fluxer or Lime Technology. Report package problems through [GitHub Issues](https://github.com/mvandenbulcke/fluxer-unraid/issues).
