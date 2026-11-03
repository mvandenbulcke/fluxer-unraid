# Install Fluxer through Unraid

[Documentation](README.md) · [Troubleshooting](troubleshooting.md) · [Manual deployment](manual-deployment.md)

This guide uses the native Unraid interface. The plugin supports Unraid 7 only. It runs the official Fluxer bundle with Cloudflare Tunnel, Traefik, and direct call ports.

## Before installation

1. Start the Unraid array and Docker service.
2. Install **Compose Manager Plus** from **Apps**.
3. Choose a hostname in a domain that Cloudflare manages, such as `chat.example.com`.
4. Check the storage pool for the `appdata` and Docker system shares.
5. Confirm that your gateway has a public WAN address for direct calls.

Use Docker Engine 25 or newer and Compose 2.24.4 or newer. Allow at least 2 CPU cores, 4 GB of memory, and 20 GB of free space. See [Fluxer's requirements](https://fluxer.com/selfhost).

Use the NAS LAN address throughout the guide. `192.168.1.10` is an example. Use your own hostname, email address, and LAN address in the forms.

## Create the Cloudflare credentials

The deployment uses two separate credentials:

| Credential | Purpose |
| --- | --- |
| Tunnel connector token | Connect the NAS to one Cloudflare Tunnel |
| DNS API token | Create certificate challenge records for your selected domain |

### Tunnel connector token

1. Open Cloudflare's **Networking > Tunnels** page or the corresponding Zero Trust tunnel page.
2. Create a cloudflared tunnel with a descriptive name, such as `fluxer`.
3. Select the Docker connector instructions.
4. Copy the token from the connector command.

Keep this page open. Some Cloudflare setup screens require the connector to connect before they allow hostname configuration. The plugin starts the connector after its first setup.

See [Cloudflare's tunnel guide](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/).

### DNS API token

Create a separate custom API token with these permissions:

| Resource | Permission |
| --- | --- |
| Your selected domain only | Zone DNS Edit, sometimes shown as DNS Write |
| Your selected domain only | Zone Read |

Limit the token to that domain. The certificate flow needs no broader account permissions. See [Cloudflare token creation](https://developers.cloudflare.com/fundamentals/api/get-started/create-token/) and [Lego's Cloudflare permissions](https://go-acme.github.io/lego/dns/cloudflare/).

Choose an expiration policy that supports unattended certificate renewal. If you use an expiry date, replace the token before it expires. Save the token securely when Cloudflare shows it. Cloudflare may show it only once.

## Install and configure the plugin

1. Open **Plugins > Install Plugin**.
2. Enter this URL and select **Install**:

   ```text
   https://github.com/mvandenbulcke/fluxer-unraid/releases/latest/download/fluxer.plg
   ```

3. Open **Settings > Fluxer**.
4. Fill the fields below and select **Save setup**.
5. Select **Start Fluxer**.

| Field | Example or value |
| --- | --- |
| Instance domain | `chat.example.com`, without a scheme or path |
| Certificate email | Your email address for the certificate account |
| NAS LAN address | The NAS address, such as `192.168.1.10` |
| Cloudflare DNS token | The domain-scoped DNS API token |
| Cloudflare Tunnel token | The tunnel connector token |

The certificate email goes to Let's Encrypt. The plugin saves the application keys and tokens under `/mnt/user/appdata/fluxer`. It preserves existing application keys.

The first image download can take several minutes. Use **Refresh status** to check progress. Follow the next section while the tunnel connector connects.

## Configure the HTTPS tunnel route

1. Return to the tunnel in Cloudflare.
2. Add a published application or public hostname route.
3. Enter the values in the table below.
4. Save the route.

| Setting | Value |
| --- | --- |
| Public hostname | `chat.example.com` |
| Service URL | `https://traefik:443` |
| Path | Empty, so every application path reaches Fluxer |
| Origin Server Name | `chat.example.com` |
| HTTP Host Header | `chat.example.com` |
| No TLS Verify / Disable TLS certificate verification | Off |

Use the same hostname as **Instance domain** in Unraid. Cloudflare creates the tunnel DNS route when you save the published application. The connector reaches Traefik inside the Docker network. The web app needs no inbound NAS web port.

Keep origin certificate verification enabled. Traefik gets the origin certificate through a DNS challenge. See [Cloudflare origin parameters](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/origin-parameters/).

Keep WebSockets enabled. Disable Rocket Loader and HTML caching for this hostname. Exclude `/api/`, `/gateway`, and `/livekit/` from browser challenges or external login screens. Use Fluxer's account authentication. See [Fluxer's proxy settings](https://docs.fluxer.com/operator/reverse-proxy/#cloudflare).

## Configure direct voice and video

Create these forwards on the gateway's public WAN interface:

| WAN port | Protocol | Forward address | Forward port |
| --- | --- | --- | --- |
| 7881 | TCP | NAS LAN address, such as `192.168.1.10` | 7881 |
| 7882 | UDP | NAS LAN address, such as `192.168.1.10` | 7882 |

Keep the external and internal port numbers the same. This deployment sends call media directly to LiveKit. Traefik and Cloudflare Tunnel carry the web app and signaling.

If another router sits upstream, it may also need these forwards. Carrier-grade NAT can prevent direct access without a public address from the ISP. See [UniFi port forwarding](https://help.ui.com/hc/en-us/articles/235723207-UniFi-Gateway-Port-Forwarding) and [LiveKit's ports](https://docs.livekit.io/transport/self-hosting/ports-firewall/).

An outbound VPN can change the address that LiveKit announces. Read the [VPN guide](manual-deployment.md#vpn-routing-and-certificates) before testing calls on that route. LAN callers also depend on the gateway's NAT loopback support.

## Create the first administrator

1. Wait for the public hostname to load over HTTPS.
2. Select **Show setup token** on **Settings > Fluxer**.
3. Select **Open Fluxer**.
4. Enter the setup token in Fluxer's setup wizard.
5. Complete the instance setup and create the first administrator account.

Enter the new account password directly in Fluxer. Keep the setup token private. A username sign-in method can avoid the need for an email server. Self-hosting requires no Operator Pass license key. See [Fluxer's self-hosting guide](https://fluxer.com/selfhost).

Test text chat with a second account. Test voice and video from a separate internet connection as well as the LAN.

## Storage and backups

The default project path is `/mnt/user/appdata/fluxer`. Unraid maps this user-share path to the pool selected for `appdata`. The pool can be an SSD or NVMe pool named `nand`, `cache`, or another name.

For example, a pool named `nand` can store the project at `/mnt/nand/appdata/fluxer`. Check **Shares > appdata** for its primary and secondary storage settings. For an existing share, check its current data location before changing pools.

All eight Fluxer volumes use bind mounts under the project's data folder. Traefik stores certificates there too. Docker images and container layers use Unraid's Docker storage location, which is separate from appdata. Check that location in **Settings > Docker** and check the pool for its share.

Unraid also stores the plugin manifest and cached package on its boot device. Those plugin files are separate from Fluxer's application data.

To make a consistent backup:

1. Select **Stop Fluxer**.
2. Back up the complete `/mnt/user/appdata/fluxer` folder, including `.env`, `secrets/`, certificates, and data.
3. Select **Start Fluxer** after the backup completes.

Keep the database and its matching application keys together for restoration. A plugin archive is not an application-data backup.

## Updates and removal

A plugin update replaces the management code. **Start Fluxer** also upgrades known managed ingress files. It preserves custom ingress files and requests a manual merge. These actions preserve application keys and data.

A full Fluxer release upgrade remains manual. Use the [manual deployment guide](manual-deployment.md#storage-and-updates) before changing the upstream bundle. The plugin does not automate a full application upgrade or database migration.

**Start Fluxer** enables automatic start after Docker starts. **Stop Fluxer** disables that behavior. Plugin removal keeps the containers and appdata. Stop Fluxer before removing its management plugin.

To replace a Cloudflare token, use **Save tokens** on **Settings > Fluxer**. Empty fields keep their saved values. Select **Start Fluxer** to apply a token change.
