# Troubleshoot Fluxer on Unraid

[Documentation](README.md) · [Installation](installation.md) · [Manual deployment](manual-deployment.md)

## Find the affected layer

| Symptom | First check |
| --- | --- |
| Save or Start is unavailable | Array, Docker, Compose Manager Plus, and the saved NAS LAN address |
| Many Fluxer containers appear | The expected service layout below |
| Cloudflare reports an unavailable tunnel | Tunnel connector state and outbound port 7844 |
| The hostname returns 502 | Traefik certificate and tunnel origin settings |
| The web app works but the desktop app does not | Desktop version and instance address |
| Chat pauses or reconnects | Gateway WebSockets, client version, and a second-client test |
| Calls connect without media | Router forwards, announced voice address, and VPN return routing |

## Read the status and logs

Open **Settings > Fluxer** and select **Refresh status**. For one container, open **Docker**, select its icon, then select **Logs**.

For local command checks, open your Unraid web interface and select **Terminal** in the toolbar. [This example NAS link](http://192.168.1.10) uses a placeholder address. Replace it with your NAS LAN address.

These commands read the controller status and recent log entries:

```bash
/usr/local/emhttp/plugins/fluxer/scripts/fluxerctl status
tail -n 80 /var/log/fluxer-unraid.log
docker logs --tail 80 fluxer-traefik-1
docker logs --tail 80 fluxer-cloudflared-1
```

Before posting logs, remove tokens, setup keys, passwords, email addresses, personal hostnames, and IP addresses. Include only the relevant excerpt. Do not post `.env`, token files, full Compose output, or Docker inspect output.

## Prerequisites or saved address fail

The array and Docker service must run before setup. Install Compose Manager Plus from Apps. Use Docker Engine 25 or newer and Compose 2.24.4 or newer.

The saved NAS LAN address must belong to this NAS. A stale address can prevent startup after a network change. See [manual address changes](manual-deployment.md#storage-and-updates) for the environment setting and corresponding router changes.

If the controller reports a foreign Fluxer project, use that project's original folder. The plugin refuses to manage another project with the same Compose name.

## One stopped container is expected

The stack has 23 services. `seaweedfs-init` initializes storage and exits with code 0 after success. The other 22 containers remain running. Of those, 21 have health checks. Cloudflared has no Docker health check, so also check its connection state in Cloudflare.

A running proxy alone does not prove that the application works. Check the public page and the affected API or client path.

## Cloudflare tunnel cannot connect

Cloudflare Tunnel needs outbound TCP or UDP port 7844 to its published tunnel addresses. A VPN or firewall can block this path. Check for connection timeouts in `fluxer-cloudflared-1` and compare the tunnel status in Cloudflare.

If an outbound VPN blocks the tunnel, use an exception limited to the NAS, Cloudflare's tunnel addresses, and port 7844. Keep other NAS traffic on its existing route. See [Cloudflare's firewall requirements](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/tunnel-with-firewall/) and the [VPN guide](manual-deployment.md#vpn-routing-and-certificates).

## The hostname returns 502

Check these values against the instance domain:

| Setting | Required value |
| --- | --- |
| Service URL | `https://traefik:443` |
| Origin Server Name | The Fluxer instance hostname |
| HTTP Host Header | The same hostname |
| No TLS Verify / Disable TLS certificate verification | Off |

Then read the Traefik log. A healthy Traefik container can appear before its certificate exists. A failed certificate challenge can leave Cloudflare unable to validate the origin certificate.

A DNS `REFUSED` response or propagation timeout needs a DNS-path check. The bundle uses recursive TXT checks when authoritative queries are unavailable. It allows up to 3600 seconds for propagation and checks every 10 seconds. Certificate authority validation remains enabled. See the [certificate configuration](manual-deployment.md#vpn-routing-and-certificates).

Certificate renewal through the VPN alone remains untested. Check the renewal result in the Traefik log when renewal occurs.

## A plugin update reports local ingress changes

Back up the project before merging files. Compare `compose.ingress.yml` in the project with the new bundled version. The plugin preserves custom changes and stops for a manual merge. Application keys and data must remain unchanged.

Full Fluxer release upgrades use the [manual update procedure](manual-deployment.md#storage-and-updates).

## Desktop client is outdated or slow

First open the instance in a current browser. If the browser works, check the desktop app's version and selected instance address. Get current desktop builds from [Fluxer's official download page](https://fluxer.com/download).

An outdated-client message needs a compatible client update. For a delay without a version error, compare message delivery between the browser and a second account. This helps separate a client delay from a shared Gateway problem.

## Messages pause or reconnect

Keep WebSockets enabled for the hostname. Exclude `/api/`, `/gateway`, and `/livekit/` from browser challenges and external login screens. Keep Rocket Loader and HTML caching off for this hostname. See [Fluxer's Cloudflare guidance](https://docs.fluxer.com/operator/reverse-proxy/#cloudflare).

The public checks include instance discovery, API health, app readiness, and a Gateway WebSocket handshake. A handshake checks transport connectivity. Authenticated message delivery needs a separate test with two accounts.

## Calls have no audio or video

Check TCP 7881 and UDP 7882 forwarding to the saved NAS LAN address. Keep each external and internal port the same. Test from a separate internet connection.

An outbound VPN can make LiveKit announce the VPN exit address. Use the [manual voice settings](manual-deployment.md#vpn-routing-and-certificates) to set a WAN address when needed. Also test the return route for media. A destination-port exception for 7882 does not match replies to random client ports.

If external calls work but LAN calls fail, check the gateway's NAT loopback behavior. See [UniFi hairpin NAT](https://help.ui.com/hc/en-us/articles/30202160464023-Hairpin-NAT-in-UniFi).

## Request support

Open a [GitHub issue](https://github.com/mvandenbulcke/fluxer-unraid/issues) with the plugin, Unraid, Docker Engine, and Compose versions. Add the affected service, reproduction steps, expected result, actual result, and a short redacted log excerpt.

Voice and video currently have operator-reported success. Text chat remains unconfirmed after a possible desktop delay. HTTP and browser checks are recorded separately in the [test notes](manual-deployment.md#checks).
