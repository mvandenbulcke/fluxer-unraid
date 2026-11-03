# Fluxer for Unraid 7

Run the official Fluxer Compose bundle through a native **Settings > Fluxer** page. This unofficial beta uses Cloudflare Tunnel and Traefik for the web app. Voice and video use two direct router port forwards.

**[Open the documentation](docs/README.md)** · [Installation](docs/installation.md) · [Troubleshooting](docs/troubleshooting.md)

## Install the beta

1. Install **Compose Manager Plus** from Unraid Apps.
2. Open **Plugins > Install Plugin** and install this URL:

   ```text
   https://github.com/mvandenbulcke/fluxer-unraid/releases/latest/download/fluxer.plg
   ```

3. Follow the [installation guide](docs/installation.md) for Cloudflare credentials, the HTTPS route, voice ports, and first administrator setup.

Community Applications submission is in progress. An approved Apps listing is not confirmed. The plugin install URL remains available during review.

## Requirements

Use Unraid 7, Docker Engine 25 or newer, and Docker Compose 2.24.4 or newer. Allow at least 2 CPU cores, 4 GB of memory, and 20 GB of disk space. Uploads need more space. See [Fluxer's host requirements](https://fluxer.com/selfhost).

You need a Cloudflare-managed hostname and a public WAN address for direct calls. The [installation guide](docs/installation.md) covers appdata on an SSD or NVMe pool. The [manual guide](docs/manual-deployment.md#vpn-routing-and-certificates) covers outbound VPN routing.

## Test status

HTTP and browser checks passed for the public setup wizard, instance discovery, API health, app readiness, and the Gateway WebSocket handshake. The Settings page and 21 container health checks also passed on Unraid 7.3.4.

The operator reports working voice and video. Text chat needs another test because the operator reported a possible desktop delay. Certificate renewal through the VPN alone remains untested. See the [test notes](docs/manual-deployment.md#checks).

The bundled Fluxer release is `2026.1102.205049`. [UPSTREAM.json](UPSTREAM.json) records its source and checksum. Plugin updates manage the wrapper and known ingress changes. Full Fluxer release upgrades remain manual.

## Support and development

Use [GitHub Issues](https://github.com/mvandenbulcke/fluxer-unraid/issues) for package problems. Include versions, reproduction steps, service health, and a short redacted log excerpt. Keep `.env`, tokens, setup keys, and passwords private.

See [CONTRIBUTING.md](CONTRIBUTING.md), [PUBLISHING.md](PUBLISHING.md), and [CHANGELOG.md](CHANGELOG.md) for checks, releases, and changes.

Source code uses the [AGPL-3.0-or-later license](LICENSE). This project does not represent Fluxer or Lime Technology.
