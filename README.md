# Fluxer for Unraid 7

Install and manage Fluxer from **Settings > Fluxer**. This unofficial beta plugin runs the official Fluxer Docker Compose bundle.

The web app uses Cloudflare Tunnel and Traefik. Calls connect directly through Tailscale. Every caller needs VPN access. This design needs no router port forwarding.

The public Community Applications listing still needs submission and approval. The plugin release also supports installation through **Plugins > Install Plugin**.

## Install the beta plugin

1. Install **Compose Manager Plus** and **Tailscale (Plugin)** from Unraid Apps. Connect the NAS to Tailscale. Read the [Unraid Tailscale guide](https://tailscale.com/docs/integrations/unraid).
2. Open **Plugins > Install Plugin**. Enter this release URL:

   ```text
   https://github.com/mvandenbulcke/fluxer-unraid/releases/latest/download/fluxer.plg
   ```

3. Open **Settings > Fluxer**. Enter your instance domain, certificate email, NAS Tailscale address, and Cloudflare tokens. Select **Save setup**.
4. Add the domain to your Cloudflare Tunnel. Use `https://traefik:443` as the service. Set **Origin Server Name** and **HTTP Host Header** to your instance domain. Keep **No TLS Verify** off.
5. Select **Start Fluxer**. Wait for healthy services. Select **Open Fluxer**, then **Show setup token** to create the first administrator account.

The page shows missing requirements before setup. Create the [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/) in your own account. Use a separate DNS API token with **Zone:DNS:Edit** and **Zone:Zone:Read**, scoped to your domain. Traefik uses that token for certificates.

## Data and access

The plugin stores the deployment, application keys, uploads, and database under `/mnt/user/appdata/fluxer`. It stores Cloudflare tokens in private files. Setup preserves existing application keys. **Save tokens** updates only the Cloudflare tokens. Select **Start Fluxer** after a token change to apply it.

Calls use TCP 7881 and UDP 7882, bound only to the saved Tailscale address. The web app remains public with Fluxer account authentication. Keep browser challenges and external authentication screens off for this hostname. See the [Fluxer proxy guide](https://docs.fluxer.com/operator/reverse-proxy/).

The plugin resumes a stack after Docker starts if you previously selected **Start Fluxer**. **Stop Fluxer** disables that behavior and keeps the data. Plugin removal keeps the containers and appdata. Stop Fluxer before you remove its management plugin.

Back up the complete appdata folder before updates. A plugin update replaces the management code. It does not replace an existing deployment bundle or change the database. Use the [manual deployment guide](docs/manual-deployment.md) for Fluxer release updates.

## Requirements and checks

Use Unraid 7, Docker Engine 25 or newer, and Docker Compose 2.24.4 or newer. Fluxer requires at least 2 CPU cores, 4 GB of memory, and 20 GB of disk space. Uploads need more space. See [Fluxer's requirements](https://fluxer.com/selfhost).

The bundled Fluxer release is `2026.1102.205049`. `UPSTREAM.json` records its source and checksum. Local checks cover secret creation, key preservation, VPN port bindings, and controller behavior. GitHub Actions checks PHP syntax and builds the release package. A full installation and live call still need a NAS test.

Source code uses the [AGPL-3.0-or-later license](LICENSE). This project does not represent Fluxer or Lime Technology. Report package problems through [GitHub Issues](https://github.com/mvandenbulcke/fluxer-unraid/issues).
