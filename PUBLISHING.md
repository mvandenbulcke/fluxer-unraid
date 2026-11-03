# Publish the Unraid plugin

The public source repository is [mvandenbulcke/fluxer-unraid](https://github.com/mvandenbulcke/fluxer-unraid). This unofficial beta plugin supports Unraid 7 only.

Community Applications submission remains on hold. No submission exists. GitHub releases distribute the beta through **Plugins > Install Plugin**. A GitHub release does not create an Unraid Apps entry.

Beta `2026.11.03.5` installed on Unraid 7.3.4. The Settings page and 21 container health checks passed. The public HTTPS setup wizard loads. Instance discovery, API health, app readiness, and the Gateway WebSocket handshake passed. Authenticated chat, voice, and video tests remain. Certificate renewal through the VPN alone also remains untested.

## Candidate preparation

Version `2026.11.03.6` is the next candidate. [CHANGELOG.md](CHANGELOG.md) records its package, catalog, and check changes. Beta `2026.11.03.5` remains the latest public release. Candidate preparation does not create a tag, public release, NAS update, or Community Applications submission. No NAS runtime test exists for version `2026.11.03.6`.

## Beta release

1. Add the matching `## YYYY.MM.DD.N` section to [CHANGELOG.md](CHANGELOG.md) before a release build or tag.
2. Run the checks in [CONTRIBUTING.md](CONTRIBUTING.md) for the final commit. Use the intended version for the package build:

   ```text
   python3 tools/build-unraid-plugin.py --version YYYY.MM.DD.N --repository mvandenbulcke/fluxer-unraid
   ```

   Replace `YYYY.MM.DD.N` with a new version, with `N` greater than zero.
3. Complete the package review below.
4. Push a new `vYYYY.MM.DD.N` tag for that tested commit. The version must match the package build and changelog entry.
5. Download the release artifacts. Check their SHA256 checksums before installation.

The manifest uses the changelog section for the exact package version as its release notes. The release workflow tests the tagged commit and builds three artifacts: the versioned archive, `fluxer.plg`, and `SHA256SUMS`. The manifest downloads that exact archive. The stable install URL points to the latest release manifest:

```text
https://github.com/mvandenbulcke/fluxer-unraid/releases/latest/download/fluxer.plg
```

GitHub excludes prereleases from this URL. Beta releases therefore use the regular release channel. The package and Community Applications template must retain the unofficial beta label.

## Package review

- [ ] Archive paths remain inside `/usr/local/emhttp/plugins/fluxer`. Scripts are executable, and the package contains no instance data or credentials.
- [ ] The manifest version, archive URL, SHA256 checksum, supported Unraid version, and project links match the release.
- [ ] A separate Unraid 7 test system passes installation, plugin update, start, stop, Docker restart, and plugin removal checks.
- [ ] The update preserves application keys, tokens, and data. Custom ingress files remain unchanged, and the controller requests a manual merge.
- [ ] Test notes record public HTTPS checks, authenticated chat, voice, video, and certificate renewal results, including any incomplete checks.

Keep the beta label while required chat, call, and renewal tests remain incomplete. Keep the Community Applications hold in place.

## Future Community Applications review

The following work prepares a later review. Do not submit while the hold remains.

- Check `ca_profile.xml` and `templates/fluxer.xml` against the [repository XML rules](https://ca.unraid.net/submit/help/repository-xml).
- Keep `<PluginURL>` pointed at the public manifest. Include working support and project links.
- Keep the overview clear about Unraid 7, the Compose dependency, public web access, call ports, and the beta status.
- Review the submission terms and the remaining test results before a future submission.

The submission portal requires manual review for plugins. Validation and scanning belong to that later submission flow. Repository preparation does not submit an entry or create a support thread.

## Support and maintenance

Use [GitHub Issues](https://github.com/mvandenbulcke/fluxer-unraid/issues) for package support. Request versions, reproduction steps, service health, and short redacted log excerpts. Never request `.env`, token files, setup keys, full Compose output, or Docker inspect output.

Full Fluxer release upgrades remain manual. Use the [manual deployment guide](docs/manual-deployment.md) and compare the upstream Compose changes before an upgrade. A plugin update does not perform a full Fluxer upgrade or database migration.

Plugin removal keeps application data and containers. Stop Fluxer before removing its management plugin.
