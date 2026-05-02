# Twitch auth-token validation investigation

Date: 2026-05-02  
Related issue: [#116 Detect invalid Twitch auth-token before a stream starts](https://github.com/liofal/streamlink/issues/116)  
Streamlink version inspected: `8.3.0`

## Question

Can this recorder detect an invalid Twitch browser playback `auth-token` before the monitored streamer goes live?

The target failure from #116 is:

```text
Unauthorized: The "Authorization" token is invalid.
```

This failure comes from Streamlink playback authentication, not from this app's Twitch Helix polling credentials.

## Findings

### 1. The current Streamlink API option works for browser auth-token headers

The recorder currently sets:

```python
session.set_option("http-headers", f"Authorization=OAuth {self.config.oauth_token}")
```

In Streamlink 8.3.0, setting `http-headers` this way updates the session HTTP headers with:

```text
Authorization: OAuth <token>
```

A local probe with a deliberately fake token against a non-existent/offline Twitch channel produced the target error before any stream was live:

```text
PluginError Unauthorized: The "Authorization" token is invalid.
```

This means the currently used `http-headers` path is effective for detecting obviously invalid Twitch browser auth tokens during Streamlink's Twitch GraphQL playback access-token request.

### 2. Streamlink's Twitch plugin also exposes a CLI-level `api-header` option

The Streamlink Twitch plugin source defines a plugin argument named `api-header`, which corresponds to the CLI option often documented as:

```text
--twitch-api-header=Authorization=OAuth <token>
```

Internally, Streamlink passes this option into `TwitchAPI(api_header=...)`, and those headers are applied to Twitch GraphQL API requests.

However, this application uses the Python API directly, not the Streamlink CLI. In the Python API, the current `http-headers` option is demonstrably effective for the invalid-token case. A future implementation can keep `http-headers` for minimal compatibility, or switch to a small helper that is easy to adapt if Streamlink's Python plugin option handling is clarified further.

### 3. Offline validation appears feasible as a best-effort Streamlink probe

The important observation is that a fake token fails even when probing a non-existent/offline Twitch channel. With no token, the same probe returned no streams instead of an auth error.

Observed behavior:

| Probe | Result |
| --- | --- |
| no auth token + non-existent Twitch channel | empty stream list |
| fake auth token via `http-headers` + non-existent Twitch channel | `PluginError Unauthorized: The "Authorization" token is invalid.` |

This suggests a best-effort validation method can call Streamlink's Twitch stream discovery for the configured channel while the channel is offline. If Twitch rejects the browser auth token, Streamlink surfaces the invalid-token error before the next recording attempt.

### 4. Validation should be classified, not boolean-only

The implementation should avoid treating every Streamlink exception as an invalid auth token. Suggested statuses:

- `VALID_OR_NOT_REJECTED`: no invalid-token error was observed. This includes an offline stream returning no streams.
- `INVALID`: Streamlink/Twitch explicitly reports invalid/unauthorized `Authorization` token.
- `UNKNOWN`: network failure, Twitch API shape change, Streamlink plugin error unrelated to invalid auth, or other unexpected validation failure.
- `NOT_CONFIGURED`: no playback auth token is configured.

Only `INVALID` should produce an invalid-token operator alert. `UNKNOWN` should log a warning without claiming the token is invalid.

### 5. Recording errors still need loop-level handling

Even with startup/periodic validation, the token can become invalid between checks. The recording path should catch Streamlink/recording exceptions, log a redacted failure, notify operators, and continue the polling loop instead of allowing the recorder process to crash.

### 6. Unauthenticated fallback should be explicit and opt-in

Automatically retrying unauthenticated can change behavior: it may record a different quality set, fail for restricted streams, or hide the fact that authenticated access is broken. If implemented, fallback should require an explicit config flag such as:

```text
TWITCH_AUTH_FALLBACK_UNAUTHENTICATED=true
```

The app should notify when fallback is used.

## Recommended implementation shape

### StreamlinkManager

Add small, testable methods:

```python
class AuthValidationStatus(Enum):
    NOT_CONFIGURED = auto()
    VALID_OR_NOT_REJECTED = auto()
    INVALID = auto()
    UNKNOWN = auto()
```

```python
def configure_session_auth(self, session, oauth_token=None):
    token = oauth_token if oauth_token is not None else self.config.oauth_token
    if token:
        session.set_option("http-headers", f"Authorization=OAuth {token}")
```

```python
def validate_oauth_token(self, user):
    if not self.config.oauth_token:
        return AuthValidationStatus.NOT_CONFIGURED

    session = self.create_session()
    self.configure_session_auth(session)
    try:
        session.streams(f"twitch.tv/{user}")
        return AuthValidationStatus.VALID_OR_NOT_REJECTED
    except Exception as error:
        if is_invalid_twitch_auth_error(error):
            return AuthValidationStatus.INVALID
        logger.warning("Unable to validate Twitch auth token: %s", type(error).__name__)
        return AuthValidationStatus.UNKNOWN
```

`is_invalid_twitch_auth_error()` should inspect exception type/message without logging the token.

### Recorder loop

At startup, validate a configured token once. During the loop, periodically revalidate based on a config interval, or validate each offline cycle with throttled notification to avoid spam.

For the first implementation, prefer:

- validate at startup if `oauth_token` is configured;
- validate periodically while the streamer is offline, with a default interval significantly longer than `timer`;
- notify only on status transition into `INVALID`.

### Recording error handling

Wrap `streamlink_manager.run_streamlink(...)` in `try/except`:

- log a redacted error with exception type and safe message;
- notify all configured notifiers;
- continue the polling loop;
- do not print tokens.

### Optional fallback

Add an explicit config flag for unauthenticated fallback. Suggested env/CLI compatibility:

| Purpose | CLI | Env |
| --- | --- | --- |
| retry unauthenticated after auth failure | `-authfallback` | `TWITCH_AUTH_FALLBACK_UNAUTHENTICATED` / `authfallback` |
| validation interval seconds | `-authvalidationinterval` | `TWITCH_AUTH_VALIDATION_INTERVAL` / `authvalidationinterval` |

Fallback can be implemented after the validation/error-handling core if scope needs to stay smaller.

## Suggested acceptance criteria for implementation

- Invalid configured browser auth token is detected with a Streamlink probe before a stream starts when Twitch returns the invalid-token error.
- Startup/periodic validation logs and notifies invalid-token status without printing the token.
- Unknown validation errors are not mislabeled as invalid credentials.
- Recording exceptions are caught so the polling loop continues.
- Optional unauthenticated fallback is behind an explicit config flag and is documented.
- Unit tests mock Streamlink sessions and cover valid/not rejected, invalid, unknown, not configured, recording error handling, and fallback behavior if included.

## Open questions before implementation

1. Should the first implementation include unauthenticated fallback, or should it land as a follow-up after validation and crash-loop handling?
2. What default validation interval is acceptable? A conservative default such as 1 hour avoids extra Twitch calls while still surfacing stale tokens ahead of most streams.
3. Should invalid-token validation failure affect process readiness/exit behavior? Current recommendation: do not exit; notify and keep polling so config can be corrected without causing crash loops.
