# Fluxer for Unraid documentation

Start with the [installation guide](installation.md). It covers the Unraid interface, Cloudflare credentials, HTTPS, direct calls, storage, and backups.

## Find a guide

| Task | Guide |
| --- | --- |
| Install through the Unraid interface | [Installation](installation.md) |
| Check appdata and backups | [Storage and backups](installation.md#storage-and-backups) |
| Update or remove the plugin | [Updates and removal](installation.md#updates-and-removal) |
| Fix a connection or client problem | [Troubleshooting](troubleshooting.md) |
| Use Compose or configure an outbound VPN | [Manual deployment](manual-deployment.md) |
| Report a bug or contribute | [Contribution guide](../CONTRIBUTING.md) |
| Review releases and Apps submission work | [Publishing guide](../PUBLISHING.md) and [changelog](../CHANGELOG.md) |

## How the deployment connects

```text
Web app and signaling: Internet -> Cloudflare Tunnel -> Traefik -> Fluxer
Voice and video media: Internet -> router TCP 7881 / UDP 7882 -> LiveKit on the NAS
```

The plugin manages one instance across multiple containers. The stack has 23 services, including Traefik, Cloudflare Tunnel, and a storage initialization service. That initialization service stops after success. It is normal for the other 22 containers to remain running.

The web app uses Fluxer's own account authentication. Callers need no VPN for the direct call setup. An outbound VPN on the NAS needs [additional routing checks](manual-deployment.md#vpn-routing-and-certificates).

## What testing shows

| Area | Status |
| --- | --- |
| Unraid Settings page and 21 container health checks | Passed on Unraid 7.3.4 |
| Public HTTPS setup wizard, discovery, API, app readiness, and Gateway handshake | HTTP and browser checks passed |
| Voice and video | Operator reports success |
| Text chat | Unconfirmed after a possible desktop delay |
| Certificate renewal through the VPN alone | Untested |

Community Applications submission is in progress. Approval and an Apps listing are not confirmed.

This documentation applies to the bundled release recorded in [UPSTREAM.json](../UPSTREAM.json). The package is an unofficial beta for Unraid 7 only.
