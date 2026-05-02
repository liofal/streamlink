# Twitch Auth Token Validation Design

Date: 2026-05-02  
Related issue: [#116 Detect invalid Twitch auth-token before a stream starts](https://github.com/liofal/streamlink/issues/116)  
Investigation: `docs/investigations/twitch-auth-token-validation.md`

## Goal

Detect confirmed-invalid Twitch browser playback auth tokens before or during recording, make the failure visible to operators, and avoid quiet failure loops.

## Problem

The recorder can appear healthy while a streamer is offline because Twitch Helix polling still works with `clientid` / `clientsecret`. If the configured Streamlink playback token (`oauthtoken` / `TWITCH_AUTH_TOKEN`) is expired or invalid, the app may only discover this when a stream starts, causing a missed recording.

## Key Decision

Invalid-token handling is configurable, with default behavior optimized for Kubernetes/monitored deployments.

| Policy | Behavior for confirmed invalid token |
| --- | --- |
| `exit` | Default. Log, notify, then exit non-zero. |
| `notify` | Log and notify, keep process alive, skip recording while token remains known invalid. |

Confirmed invalid token errors are different from unknown/transient validation failures. Unknown validation failures must not exit by default.

## Configuration

Add two config values while preserving the existing CLI/env compatibility style:

| Purpose | CLI | Modern env | Legacy env | Default |
| --- | --- | --- | --- | --- |
| invalid token policy | `-authinvalidpolicy` | `TWITCH_AUTH_INVALID_TOKEN_POLICY` | `authinvalidpolicy` | `exit` |
| validation interval seconds | `-authvalidationinterval` | `TWITCH_AUTH_VALIDATION_INTERVAL` | `authvalidationinterval` | `3600` |

Accepted policy values:

- `exit`
- `notify`

Invalid policy values should fail clearly at startup.

## Auth Validation Statuses

Add an explicit status enum in `streamlink_manager.py`:

```python
class AuthValidationStatus(Enum):
    NOT_CONFIGURED = auto()
    VALID_OR_NOT_REJECTED = auto()
    INVALID = auto()
    UNKNOWN = auto()
```

Status meanings:

- `NOT_CONFIGURED`: no playback auth token is configured; app is in unauthenticated/public recording mode.
- `VALID_OR_NOT_REJECTED`: validation did not see Twitch reject the token. This includes an offline channel returning no streams.
- `INVALID`: Streamlink/Twitch explicitly reports the `Authorization` token is invalid or unauthorized.
- `UNKNOWN`: network error, timeout, unexpected plugin error, or anything that cannot safely be classified as invalid.

## StreamlinkManager Design

Add helper methods:

- `create_session()`
  - creates Streamlink session and sets retry options.
- `configure_session_auth(session, oauth_token=None)`
  - applies `Authorization=OAuth <token>` via `http-headers` when token is present.
- `is_invalid_twitch_auth_error(error)`
  - classifies known invalid-token messages without logging token values.
- `validate_oauth_token(user)`
  - runs a best-effort Streamlink probe and returns `AuthValidationStatus`.

Keep current recording behavior otherwise unchanged, except `run_streamlink()` should use the shared session/auth helper so validation and recording use the same auth setup.

## Recorder Behavior

### Startup

When the app starts:

1. Create `TwitchManager`, `StreamlinkManager`, and `NotificationManager`.
2. If no playback token is configured, continue as today.
3. If a token is configured, validate it once.
4. If validation is `INVALID`, apply the configured invalid-token policy.
5. If validation is `UNKNOWN`, log a warning and continue.

### Periodic validation

While running:

- Revalidate configured token after `auth_validation_interval` seconds.
- In `exit` mode, a confirmed invalid token exits non-zero.
- In `notify` mode, a confirmed invalid token marks auth state invalid and suppresses recording attempts until validation no longer returns `INVALID`.
- Avoid notification spam by notifying only on transition into invalid state, plus optional recovery notification when status becomes valid/not rejected again.

### Recording failure handling

Wrap `streamlink_manager.run_streamlink(...)` in `try/except`:

- If error is confirmed invalid auth:
  - log clear message;
  - notify operator;
  - apply invalid-token policy.
- If error is not confirmed auth-invalid:
  - log safe error with exception type/message;
  - notify operator;
  - continue polling.

Do not print configured token values.

## Invalid-token policy behavior

### `exit` policy

For confirmed invalid token:

1. Log clear error.
2. Send Slack/Telegram notification if configured.
3. Exit non-zero with `SystemExit(1)` or equivalent.

This is the default because Kubernetes/Docker monitoring can detect the failed process.

### `notify` policy

For confirmed invalid token:

1. Log clear error.
2. Notify operator.
3. Keep polling Twitch live status.
4. Skip recording attempts while auth state is invalid.
5. Periodically revalidate.
6. Resume recording only after validation no longer reports `INVALID`.

This is for users who prefer process liveness over pod-level failure signaling.

## Notifications

Messages should be short and actionable:

- Invalid token:
  - `Twitch playback auth token is invalid for <user>. Renew oauthtoken/TWITCH_AUTH_TOKEN and restart the recorder.`
- Unknown validation failure:
  - log warning only by default; no operator notification unless repeated failures become noisy in practice.
- Recording failure:
  - `Recording <user> failed: <safe reason>. Recorder will continue checking.`
- Recovery in `notify` mode:
  - `Twitch playback auth token validation recovered for <user>. Recording is enabled again.`

## Tests

Add/extend unit tests for:

- invalid-token error classification;
- validation status when no token is configured;
- validation status when Streamlink returns no streams;
- validation status when Streamlink raises invalid-token error;
- validation status when Streamlink raises unknown error;
- config parsing for policy and interval;
- invalid policy value fails clearly;
- startup invalid token exits by default;
- startup invalid token does not exit in `notify` mode;
- recording invalid-token error applies policy;
- recording non-auth error logs/notifies and continues;
- `notify` mode skips recording while token is known invalid.

## Documentation

Update README to document:

- startup/periodic validation behavior;
- default `exit` invalid-token policy;
- optional `notify` policy;
- validation interval config;
- how Kubernetes users should interpret CrashLoopBackOff caused by confirmed invalid token.

## Non-Goals

This implementation does not add unauthenticated fallback recording. Retrying without the token should be a separate feature because it changes recording behavior and could hide authentication problems.

This implementation does not add a Kubernetes readiness/liveness endpoint. Pod-level failure signaling is done by exiting non-zero on confirmed invalid tokens when policy is `exit`.

## Open Risks

- Streamlink/Twitch error messages may change. Mitigation: classify narrowly and treat unrecognized errors as `UNKNOWN`.
- A token can become invalid between validation intervals. Mitigation: recording error handling also classifies invalid-token failures.
- `notify` mode can leave a pod healthy while recording is disabled. Mitigation: default is `exit`, and README documents the trade-off.
