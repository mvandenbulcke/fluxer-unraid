# Changelog

Each version has an exact heading for the package builder. Release notes separate package changes from runtime test results.

## Unreleased

- Add the required Unraid trademark attribution to the public guides and catalog metadata.
- Record the beta 6 management update test and pending Community Applications review.

## 2026.11.03.6

Public beta package for Community Applications review. Runtime behavior remains the same as beta `2026.11.03.5`.

- Add a GitHub documentation index, installation guide, and troubleshooting guide.
- Include the user and maintainer guides with this changelog in the package.
- Use the exact version section for the Unraid plugin release notes.
- Add the required author field to the Community Applications catalog entry.
- Add package artifact tests and include them in the required GitHub checks.
- Add support and contribution instructions with a bug report form that excludes secrets.

## 2026.11.03.5

- Allow 3600 seconds for Cloudflare DNS propagation, with a check every 10 seconds.
- Keep recursive TXT checks and certificate authority validation enabled.
- Upgrade only known managed ingress files from beta 3 or beta 4. Preserve custom files, application keys, and data.

The public HTTPS setup wizard, instance discovery, API health, app readiness, and Gateway WebSocket handshake passed on Unraid 7.3.4. The operator later reported successful voice and video calls. Text chat remains unconfirmed after a possible desktop delay. Certificate renewal through the VPN alone remains untested.

## 2026.11.03.4

- Use recursive DNS checks when authoritative DNS queries are unavailable.
- Keep checks against all configured recursive resolvers and retain certificate authority validation.
- Add a safe upgrade from the known beta 3 ingress file.

## 2026.11.03.3

- Add direct voice forwarding for TCP 7881 and UDP 7882 on the NAS LAN address.
- Accept longer Cloudflare account and user tokens.

## 2026.11.03.2

- Fix an occasional failure during VAPID key creation.
- Install the native Unraid 7 management plugin for local beta tests.
- Add setup, token storage, start, stop, status, and Docker restart support.

The plugin installed on Unraid 7.3.4. Its Settings page and status checks passed.
