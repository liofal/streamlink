# AGENTS.md

Guidance for coding agents (Claude Code, Codex, …) working in this repository. Read it before changing anything.

## What this is

A long-running Twitch stream recorder. It polls the Twitch Helix API (`twitchAPI`, async) to see whether a channel is live. When it is, it records the stream in-process with the `streamlink` Python API and sends Slack/Telegram notifications. It ships as a Docker image. It runs under docker-compose (Synology) or the Helm chart in `kube/charts`, with an ffmpeg sidecar that converts `.ts` to `.mp4`.

| File | Role |
|---|---|
| `streamlink-recorder.py` | Entry point: config (`AppConfig`, `first_config_value`, `parse_*`), `RecorderState`, notify policies, `loop_check` |
| `twitch_manager.py` | Helix calls (`check_user`), client lifecycle, timeout and reset |
| `streamlink_manager.py` | Session setup, playback auth-token validation, `run_streamlink` (recording) |
| `notification_manager.py` | Slack/Telegram senders with redacted error logging |
| `test_*.py` | `unittest`-style tests, run with pytest |
| `docs/` | Design specs, plans and investigations; add new ones there |

## Setup and validation gate

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt pytest
python -m pytest -q
```

- **The full test suite must pass before any PR.** CI (`.github/workflows/ci.yml`) runs it on every PR and before every release.
- Run the suite yourself and include the result in the PR.
- `requirements.txt` is the runtime set baked into the image. Dev tools (`pre-commit`, `commitizen`) go in `requirements-dev.txt`, never in `requirements.txt`.
- CI also runs `pip-audit -r requirements.txt` (blocking on PRs) and a report-only Trivy scan of the image. If a CVE has no fixed version, add `--ignore-vuln <ID>` in `ci.yml` with a comment linking a tracking issue; otherwise bump the pin.
- Workflows pin actions, reusable workflows and the base image by SHA/digest; Renovate updates them. Keep new ones pinned the same way.
- A bug fix comes with a test that fails without the fix. Say so in the PR.
- The entry script has a hyphen in its name. Tests import it with `importlib.util.spec_from_file_location` (see `test_recorder_auth_validation.py`); reuse that loader.
- Mock `streamlink` and `twitchAPI` at their boundaries. Tests never hit the network. For library behavior, read the installed source in the venv rather than guessing.

## Invariants

- **Never log or notify exception messages from Twitch, streamlink or HTTP calls.** Log `type(e).__name__`, or use `twitch_manager._twitch_error_summary`. Library messages can embed URLs carrying `client_secret` or webhook tokens (#161).
- **Never read, print or commit secrets.** `clientid.env`, `kube/charts/secret.yaml` and any `*.env` other than the examples hold real credentials, and they are gitignored. Use `clientid.env.example` and `kube/charts/secret.example.yaml`.
- **Configuration:** every option is a CLI flag plus env var(s) via `first_config_value(cli, (ENV_NAME, legacy_name), default)`, with a `parse_*` validator. Document new options in `README.md`.
- **Notifications** say once on a transition and once on recovery. Follow the flags pattern in `RecorderState`, and never notify on every poll.
- **Keep changes in scope** of the work item. Neighbouring problems go into a follow-up issue, not this diff.

## Commits, releases, deploys

- Conventional Commits (commitizen hook in `.pre-commit-config.yaml`).
- semantic-release runs on every push to `main` (`.releaserc.json`):
  - `fix:` → patch release
  - `feat:` → minor release
  - `chore(deps):` → patch release
  - `docs:`, `test:`, other `chore:` → no release
- **A releasing merge (`fix:`, `feat:`, `chore(deps):`) ships immediately.** The release publishes the image (Docker Hub, ghcr) and the Helm chart. Running pods pick up the new `latest` image whenever they restart (`pullPolicy: Always`) or the chart is upgraded. The release is gated on CI (tests, import smoke, docker build), but main has no branch protection yet, so treat every releasing merge as a production deploy.
- Branches: `fix|feat|chore|docs/<issue>-<slug>`. PRs reference `Closes #<issue>`.
- Never push to `main` directly, and never force-push.

## Open work (audit 2026-11-04)

Issues #161–#171 come from a multi-agent audit. Check the issue that owns an area before changing it:
- #164: signals and `.part` finalization
- #165: retries, empty streams, blocking notifications and the loop's sleeps
- #166: quality
- #167: filenames
- #168: non-root and pod security
- #169: Helm
- #162 and #170: CI and supply chain
- #171: grouped low-severity items
