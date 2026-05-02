# High-Severity Secret Leak Remediation Design

Date: 2026-05-02  
Repository revision: `95b3b32`  
Scope: High-severity secret disclosure risks from `security_best_practices_report.md`.

## Goal

Remove direct secret leak paths while preserving existing community deployment models.

This pass addresses:

- SEC-003: Twitch app refresh token is logged.
- SEC-002 / GitHub #115: Slack and Telegram notifier secrets can leak through raw HTTP exception logging.
- SEC-001 / GitHub #114: Docker entrypoint expands secrets into process arguments.

## Non-Goals

This pass does not implement:

- README auth-token lifecycle documentation for #117.
- Twitch auth-token validity checking for #116.
- VOD backfill workflow for #119.
- Kubernetes security context hardening.
- username/path safety hardening.
- dependency vulnerability scanning automation.

Those items should be handled in follow-up work.

## Compatibility Requirements

The remediation must be non-breaking for existing users.

Existing interfaces that must continue to work:

- direct Python CLI arguments;
- Docker `-e` flags using current lowercase variable names;
- Docker Compose `env_file` usage with current lowercase keys;
- Helm/Kubernetes `envFrom` usage with current lowercase ConfigMap and Secret keys.

New uppercase environment variable names are additive only. Existing lowercase names remain supported.

Configuration precedence must be:

```text
CLI argument > modern uppercase env var > legacy lowercase env var > default/error
```

Required config values after fallback:

- `user`
- `clientid`
- `clientsecret`

Optional config values:

- `timer`
- `quality`
- `gamelist`
- `slackid`
- `telegrambottoken`
- `telegramchatid`
- `oauthtoken`

## Design

### 1. Twitch token refresh logging

`TwitchManager.app_refresh()` currently logs the refreshed token value. Replace that with a non-sensitive message.

Desired behavior:

```python
logger.info("Twitch app token refreshed")
```

The token value must not appear in logs.

### 2. Notification error logging

Slack and Telegram notifiers currently log raw exception strings. `requests.exceptions.HTTPError` may include the request URL, and both Slack and Telegram URLs can contain secrets.

Update notifier error handling to log safe diagnostic fields only:

- service name;
- HTTP status code;
- HTTP reason, if available;
- exception type for unexpected failures.

Do not log:

- full request URLs;
- raw exception strings that may include URLs;
- Slack webhook path values;
- Telegram bot tokens;
- request or response bodies.

A shared helper should be used so Slack and Telegram follow the same redaction behavior.

Example desired log shape:

```text
Telegram notification failed with HTTP 401 Unauthorized
Slack notification failed with HTTP 403 Forbidden
Unexpected error occurred while sending message to Slack: Timeout
```

### 3. Environment fallback configuration

`streamlink-recorder.py` should continue accepting the existing CLI flags. The flags should no longer be required at parser definition time if an environment fallback can satisfy them.

Environment mapping:

| Config | CLI | Modern env | Legacy env |
|---|---|---|---|
| user | `-user` | `TWITCH_USER` | `user` |
| timer | `-timer` | `TIMER` | `timer` |
| quality | `-quality` | `STREAM_QUALITY` | `quality` |
| client id | `-clientid` | `TWITCH_CLIENT_ID` | `clientid` |
| client secret | `-clientsecret` | `TWITCH_CLIENT_SECRET` | `clientsecret` |
| auth token | `-oauthtoken` | `TWITCH_AUTH_TOKEN`, `TWITCH_OAUTH_TOKEN` | `oauthtoken` |
| Slack | `-slackid` | `SLACK_ID` | `slackid` |
| Telegram bot | `-telegrambottoken` | `TELEGRAM_BOT_TOKEN` | `telegrambottoken` |
| Telegram chat | `-telegramchatid` | `TELEGRAM_CHAT_ID` | `telegramchatid` |
| game list | `-gamelist` | `GAME_LIST` | `gamelist` |

Missing required values should produce a clear argparse-style error and non-zero exit.

`timer` should remain an integer after fallback. Invalid env values for `timer` should produce a clear config error.

### 4. Docker entrypoint

Change the Dockerfile entrypoint from shell form that expands secrets into command-line arguments to exec form with no expanded config arguments:

```dockerfile
ENTRYPOINT ["python", "./streamlink-recorder.py"]
```

Because the Python app will read the existing lowercase env vars, current Docker, Compose, and Helm deployments should continue to work without chart or compose changes.

## Testing Strategy

Add focused unit tests for the high-severity fixes:

1. `TwitchManager.app_refresh()` logs no token value.
2. Slack HTTP failure logs status/reason but not webhook secret material.
3. Telegram HTTP failure logs status/reason but not bot token.
4. CLI arguments still populate config.
5. CLI arguments override environment variables.
6. Modern uppercase env fallback works.
7. Legacy lowercase env fallback works.
8. Missing required config fails clearly.
9. Invalid env `timer` fails clearly.

Existing `streamlink_manager.py` tests should continue to pass.

## Release Notes

Suggested release note:

```text
Security: container startup no longer expands secrets into process arguments. Existing CLI arguments and existing lowercase Docker/Kubernetes environment keys remain supported. Uppercase environment variable names are now also supported.
```

## Risks and Mitigations

### Risk: existing Docker or Helm deployments fail to start

Mitigation: preserve lowercase env var support and add tests for legacy fallback.

### Risk: CLI users are broken by making parser args optional

Mitigation: keep all existing CLI flag names and validate required values after fallback.

### Risk: logs become less useful for notification failures

Mitigation: keep service name, status code, reason, and exception type while removing token-bearing values.

### Risk: environment parsing changes timer behavior

Mitigation: convert timer explicitly and test invalid values.

## Implementation Handoff

Implement this in a focused branch. Keep the PR limited to high-severity secret leak remediation, plus tests. Defer docs-heavy auth lifecycle guidance and Kubernetes hardening to follow-up issues/PRs.
