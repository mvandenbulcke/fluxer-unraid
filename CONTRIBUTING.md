# Contribute to Fluxer for Unraid

This repository packages an unofficial beta plugin for Unraid 7. Keep changes within the installer, controller, local Compose overrides, tests, and documentation. Community Applications submission is in progress. The beta has no approved Apps listing yet.

## Propose a change

1. Search [existing issues](https://github.com/mvandenbulcke/fluxer-unraid/issues) for the same problem.
2. Describe the trigger and expected behavior in an issue or pull request.
3. Make the smallest change that fixes the problem.
4. Run the checks below.
5. Explain the result, test evidence, and any limits in the pull request.

Add a regression test when a change can affect application keys, persistent data, port bindings, or ownership of an existing Compose project. Documentation changes need accurate links and examples. They do not need new runtime tests.

Keep the official upstream bundle separate from local packaging changes. `UPSTREAM.json` records the upstream release and checksum. Full Fluxer release upgrades remain manual and need a separate review of upstream changes.

## Required checks

Use Bash, Python 3.11 or newer, PHP, and OpenSSL for these checks:

```bash
bash -n setup.sh set-tokens.sh start.sh unraid-plugin/scripts/fluxerctl unraid-plugin/event/docker_started
php -l unraid-plugin/include/control.php
python3 -m unittest discover -s tests -v
python3 tools/build-unraid-plugin.py
git diff --check
```

The builder uses the version and repository defaults in its source. Add a matching `## YYYY.MM.DD.N` section to [CHANGELOG.md](CHANGELOG.md) before a release build or tag. For a release, pass the intended version and repository as described in [PUBLISHING.md](PUBLISHING.md). The GitHub checks must pass for the final commit.

Version `2026.11.03.6` adds documentation and package checks without a runtime change. The GitHub release page records the current public version. Keep release and submission claims consistent with their recorded results.

Changes to runtime behavior also need a separate Unraid 7 test system. Check installation, start, stop, update, and restart behavior for the affected path. Confirm that application keys and data remain unchanged. Record tests that you cannot complete.

The operator reported successful voice and video calls. Text chat remains unconfirmed after a possible desktop delay. Certificate renewal through the VPN alone remains untested. Do not describe these reports as independent maintainer tests. See the [recorded deployment checks](docs/manual-deployment.md#checks).

## Report a bug

Include these details in [GitHub Issues](https://github.com/mvandenbulcke/fluxer-unraid/issues):

- Plugin and Unraid versions.
- Docker Engine, Docker Compose, and bundled Fluxer versions, if known.
- Steps that cause the problem, expected behavior, and actual behavior.
- The affected service and its health state.
- A short relevant log excerpt after removing secrets and personal details.

Never attach `.env`, token files, setup keys, passwords, complete Compose output, or Docker inspect output. Remove personal email addresses, hostnames, and IP addresses from log excerpts. Package logs can include private values even when the error itself contains no secret.
