# Publish the Unraid plugin

The public source repository is `mvandenbulcke/fluxer-unraid`. The Community Applications entry is an unofficial beta plugin for Unraid 7.

## Release

1. Run the checks:

   ```bash
   python3 -m unittest discover -s tests -v
   php -l unraid-plugin/include/control.php
   python3 tools/build-unraid-plugin.py --version 2026.11.03.1
   ```

2. Push a version tag, such as `v2026.11.03.1`. The release workflow builds the archive, plugin manifest, and checksums.
3. Download the release files. Check the archive checksum against the manifest before installation.

The manifest downloads a versioned archive. The stable plugin URL points to the latest release manifest. GitHub excludes prereleases from that URL, so releases use the regular release channel. The Community Apps template retains the beta label.

## Community Applications submission

1. Open the [submission portal](https://ca.unraid.net/submit). Sign in with the maintainer account.
2. Enter `https://github.com/mvandenbulcke/fluxer-unraid`. Run **Validate**, then **Scan**.
3. Address any errors. Confirm that `templates/fluxer.xml` points to the public plugin manifest and that `ca_profile.xml` contains the repository profile.
4. Review the submission terms. Submit the repository for manual review.

The [submission rules](https://ca.unraid.net/submit/help/repository-xml) require manual review for plugins. A public GitHub release does not create an Apps listing. Keep the beta label until an Unraid installation and live call pass.

## Maintenance

Keep support available through GitHub Issues. Test future Unraid versions before changing the supported version range. Review upstream Compose changes before a Fluxer upgrade, especially the local VPN override.

Uninstall removes the management plugin. It keeps application data and containers. The plugin does not run database migrations during installation or removal.
