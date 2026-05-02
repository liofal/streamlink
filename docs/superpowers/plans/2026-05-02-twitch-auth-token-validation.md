# Twitch Auth Token Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect confirmed-invalid Twitch playback auth tokens, notify operators, and apply a configurable invalid-token policy with `exit` as the default.

**Architecture:** Keep validation and Streamlink error classification in `streamlink_manager.py`; keep runtime policy/state handling in `streamlink-recorder.py`. Reuse existing notification plumbing and add focused `unittest` coverage with Streamlink sessions mocked.

**Tech Stack:** Python 3.14, `unittest`, `unittest.mock`, Streamlink 8.3.0, existing Docker/Kubernetes env configuration style.

---

## File Structure

- Modify: `streamlink_manager.py`
  - Add `AuthValidationStatus` enum.
  - Add `create_session()`, `configure_session_auth()`, `is_invalid_twitch_auth_error()`, and `validate_oauth_token()`.
  - Refactor `run_streamlink()` to use the shared session/auth helpers.

- Modify: `streamlink-recorder.py`
  - Add config parsing for `auth_invalid_policy` and `auth_validation_interval`.
  - Add invalid-token policy handling.
  - Add startup validation, periodic validation, recording exception handling, and notify-mode invalid state suppression.

- Modify: `test_streamlink_manager.py`
  - Add tests for auth validation statuses and invalid-token classification.

- Modify: `test_config.py`
  - Add tests for new policy/interval config parsing.

- Create: `test_recorder_auth_validation.py`
  - Add recorder-loop tests for startup invalid exit, notify mode, unknown validation, invalid recording error, non-auth recording error, and notify-mode skip behavior.

- Modify: `README.md`
  - Document validation behavior, default `exit` policy, optional `notify` policy, and validation interval.

---

## Task 1: Streamlink auth validation primitives

**Files:**
- Modify: `streamlink_manager.py`
- Modify: `test_streamlink_manager.py`

- [ ] **Step 1: Write failing tests for classification and validation statuses**

Append these tests to `test_streamlink_manager.py` before `if __name__ == '__main__':`:

```python
    def test_is_invalid_twitch_auth_error_detects_authorization_token_error(self):
        error = Exception('Unauthorized: The "Authorization" token is invalid.')

        self.assertTrue(self.manager.is_invalid_twitch_auth_error(error))

    def test_is_invalid_twitch_auth_error_ignores_unrelated_errors(self):
        error = Exception("Network timeout while opening stream")

        self.assertFalse(self.manager.is_invalid_twitch_auth_error(error))

    def test_validate_oauth_token_not_configured(self):
        self.config.oauth_token = None

        status = self.manager.validate_oauth_token("testuser")

        self.assertEqual(status, AuthValidationStatus.NOT_CONFIGURED)
```

Also update imports at the top:

```python
from streamlink_manager import AuthValidationStatus, StreamlinkManager
```

- [ ] **Step 2: Add tests for mocked Streamlink validation outcomes**

Append:

```python
    @patch('streamlink_manager.streamlink.Streamlink')
    def test_validate_oauth_token_valid_or_not_rejected(self, mock_streamlink_cls):
        mock_session = mock_streamlink_cls.return_value
        mock_session.streams.return_value = {}

        status = self.manager.validate_oauth_token("testuser")

        self.assertEqual(status, AuthValidationStatus.VALID_OR_NOT_REJECTED)
        mock_session.streams.assert_called_once_with("twitch.tv/testuser")

    @patch('streamlink_manager.streamlink.Streamlink')
    def test_validate_oauth_token_invalid(self, mock_streamlink_cls):
        mock_session = mock_streamlink_cls.return_value
        mock_session.streams.side_effect = Exception('Unauthorized: The "Authorization" token is invalid.')

        status = self.manager.validate_oauth_token("testuser")

        self.assertEqual(status, AuthValidationStatus.INVALID)

    @patch('streamlink_manager.streamlink.Streamlink')
    def test_validate_oauth_token_unknown(self, mock_streamlink_cls):
        mock_session = mock_streamlink_cls.return_value
        mock_session.streams.side_effect = RuntimeError("temporary network failure")

        status = self.manager.validate_oauth_token("testuser")

        self.assertEqual(status, AuthValidationStatus.UNKNOWN)
```

- [ ] **Step 3: Run tests to verify failure**

Run:

```bash
python -m unittest test_streamlink_manager.py -v
```

Expected: FAIL because `AuthValidationStatus`, `validate_oauth_token`, and `is_invalid_twitch_auth_error` do not exist yet.

- [ ] **Step 4: Implement validation primitives**

In `streamlink_manager.py`, add imports:

```python
import logging
from enum import Enum, auto
```

Add after imports:

```python
logger = logging.getLogger(__name__)


class AuthValidationStatus(Enum):
    NOT_CONFIGURED = auto()
    VALID_OR_NOT_REJECTED = auto()
    INVALID = auto()
    UNKNOWN = auto()
```

Inside `StreamlinkManager`, add:

```python
    def create_session(self):
        session = streamlink.Streamlink()
        session.set_option("retry-max", 5)
        session.set_option("retry-streams", 60)
        return session

    def configure_session_auth(self, session, oauth_token=None):
        token = self.config.oauth_token if oauth_token is None else oauth_token
        if token:
            session.set_option("http-headers", f"Authorization=OAuth {token}")

    def is_invalid_twitch_auth_error(self, error):
        message = str(error)
        return (
            "Authorization" in message
            and "token" in message.lower()
            and any(fragment in message.lower() for fragment in ("invalid", "unauthorized"))
        )

    def validate_oauth_token(self, user):
        if not self.config.oauth_token:
            return AuthValidationStatus.NOT_CONFIGURED

        session = self.create_session()
        self.configure_session_auth(session)
        try:
            session.streams(f"twitch.tv/{user}")
            return AuthValidationStatus.VALID_OR_NOT_REJECTED
        except Exception as error:
            if self.is_invalid_twitch_auth_error(error):
                return AuthValidationStatus.INVALID
            logger.warning("Unable to validate Twitch auth token: %s", type(error).__name__)
            return AuthValidationStatus.UNKNOWN
```

Refactor the beginning of `run_streamlink()` from:

```python
        session = streamlink.Streamlink()
        session.set_option("retry-max", 5)
        session.set_option("retry-streams", 60)

        if self.config.oauth_token:
            session.set_option("http-headers", f"Authorization=OAuth {self.config.oauth_token}")
```

into:

```python
        session = self.create_session()
        self.configure_session_auth(session)
```

- [ ] **Step 5: Run tests**

Run:

```bash
python -m unittest test_streamlink_manager.py -v
```

Expected: PASS.

- [ ] **Step 6: Run all tests and commit**

Run:

```bash
python -m unittest discover -v
```

Expected: PASS.

Commit:

```bash
git add streamlink_manager.py test_streamlink_manager.py
git commit -m "feat: add twitch auth token validation"
```

---

## Task 2: Config parsing for invalid-token policy and validation interval

**Files:**
- Modify: `streamlink-recorder.py`
- Modify: `test_config.py`

- [ ] **Step 1: Write failing config tests**

Append to `test_config.py` before `if __name__ == "__main__":`:

```python
    def test_auth_validation_config_defaults(self):
        config = self.parse_with_env(
            [],
            {
                "TWITCH_USER": "env-user",
                "TWITCH_CLIENT_ID": "env-client-id",
                "TWITCH_CLIENT_SECRET": "env-client-secret",
            },
        )

        self.assertEqual(config.auth_invalid_policy, "exit")
        self.assertEqual(config.auth_validation_interval, 3600)

    def test_auth_validation_config_from_modern_env(self):
        config = self.parse_with_env(
            [],
            {
                "TWITCH_USER": "env-user",
                "TWITCH_CLIENT_ID": "env-client-id",
                "TWITCH_CLIENT_SECRET": "env-client-secret",
                "TWITCH_AUTH_INVALID_TOKEN_POLICY": "notify",
                "TWITCH_AUTH_VALIDATION_INTERVAL": "120",
            },
        )

        self.assertEqual(config.auth_invalid_policy, "notify")
        self.assertEqual(config.auth_validation_interval, 120)

    def test_auth_validation_config_from_legacy_env(self):
        config = self.parse_with_env(
            [],
            {
                "user": "legacy-user",
                "clientid": "legacy-client-id",
                "clientsecret": "legacy-client-secret",
                "authinvalidpolicy": "notify",
                "authvalidationinterval": "300",
            },
        )

        self.assertEqual(config.auth_invalid_policy, "notify")
        self.assertEqual(config.auth_validation_interval, 300)

    def test_invalid_auth_policy_fails_clearly(self):
        stderr = io.StringIO()
        env = {
            "TWITCH_USER": "env-user",
            "TWITCH_CLIENT_ID": "env-client-id",
            "TWITCH_CLIENT_SECRET": "env-client-secret",
            "TWITCH_AUTH_INVALID_TOKEN_POLICY": "restart",
        }
        with patch.dict(os.environ, env, clear=True), patch.object(sys, "stderr", stderr):
            with self.assertRaises(SystemExit) as raised:
                streamlink_recorder.parse_arguments([])

        self.assertNotEqual(raised.exception.code, 0)
        self.assertIn("Invalid auth invalid token policy", stderr.getvalue())

    def test_invalid_auth_validation_interval_fails_clearly(self):
        stderr = io.StringIO()
        env = {
            "TWITCH_USER": "env-user",
            "TWITCH_CLIENT_ID": "env-client-id",
            "TWITCH_CLIENT_SECRET": "env-client-secret",
            "TWITCH_AUTH_VALIDATION_INTERVAL": "not-an-int",
        }
        with patch.dict(os.environ, env, clear=True), patch.object(sys, "stderr", stderr):
            with self.assertRaises(SystemExit) as raised:
                streamlink_recorder.parse_arguments([])

        self.assertNotEqual(raised.exception.code, 0)
        self.assertIn("Invalid integer for auth validation interval", stderr.getvalue())
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
python -m unittest test_config.py -v
```

Expected: FAIL because the new config fields do not exist.

- [ ] **Step 3: Implement config parsing**

Update `AppConfig.__init__` signature in `streamlink-recorder.py` to include:

```python
        auth_invalid_policy,
        auth_validation_interval,
```

Set attributes:

```python
        self.auth_invalid_policy = auth_invalid_policy
        self.auth_validation_interval = auth_validation_interval
```

Add helper after `parse_timer_value`:

```python
def parse_auth_validation_interval(parser, value):
    try:
        return int(value)
    except (TypeError, ValueError):
        parser.error("Invalid integer for auth validation interval; set -authvalidationinterval/TWITCH_AUTH_VALIDATION_INTERVAL to a whole number")


def parse_auth_invalid_policy(parser, value):
    policy = str(value).lower()
    if policy not in ("exit", "notify"):
        parser.error("Invalid auth invalid token policy; expected exit or notify")
    return policy
```

Add parser args in `parse_arguments()`:

```python
    parser.add_argument("-authinvalidpolicy", help="What to do when Twitch playback auth token is invalid: exit or notify")
    parser.add_argument("-authvalidationinterval", help="Seconds between Twitch playback auth token validation checks")
```

Before `return AppConfig(...)`, add:

```python
    auth_invalid_policy = parse_auth_invalid_policy(
        parser,
        first_config_value(args.authinvalidpolicy, ("TWITCH_AUTH_INVALID_TOKEN_POLICY", "authinvalidpolicy"), "exit"),
    )
    auth_validation_interval = parse_auth_validation_interval(
        parser,
        first_config_value(args.authvalidationinterval, ("TWITCH_AUTH_VALIDATION_INTERVAL", "authvalidationinterval"), 3600),
    )
```

Add to `AppConfig(...)` call:

```python
        auth_invalid_policy=auth_invalid_policy,
        auth_validation_interval=auth_validation_interval,
```

- [ ] **Step 4: Run config tests and commit**

Run:

```bash
python -m unittest test_config.py -v
python -m unittest discover -v
```

Expected: PASS.

Commit:

```bash
git add streamlink-recorder.py test_config.py
git commit -m "feat: configure twitch auth validation policy"
```

---

## Task 3: Recorder invalid-token policy and recording failure handling

**Files:**
- Create: `test_recorder_auth_validation.py`
- Modify: `streamlink-recorder.py`

- [ ] **Step 1: Write recorder behavior tests**

Create `test_recorder_auth_validation.py` with:

```python
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from streamlink_manager import AuthValidationStatus

MODULE_PATH = Path(__file__).with_name("streamlink-recorder.py")
spec = importlib.util.spec_from_file_location("streamlink_recorder", MODULE_PATH)
streamlink_recorder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(streamlink_recorder)


class TestRecorderAuthValidation(unittest.TestCase):
    def make_config(self, policy="exit", interval=3600, oauth_token="token"):
        return streamlink_recorder.AppConfig(
            timer=1,
            user="testuser",
            quality="best",
            client_id="client-id",
            client_secret="client-secret",
            game_list="",
            slack_id=None,
            telegram_bot_token=None,
            telegram_chat_id=None,
            oauth_token=oauth_token,
            auth_invalid_policy=policy,
            auth_validation_interval=interval,
        )

    def test_startup_invalid_token_exits_by_default(self):
        config = self.make_config(policy="exit")
        notifier = MagicMock()
        streamlink_manager = MagicMock()
        streamlink_manager.validate_oauth_token.return_value = AuthValidationStatus.INVALID

        with self.assertRaises(SystemExit) as raised:
            streamlink_recorder.validate_auth_or_apply_policy(config, streamlink_manager, notifier, force_notify=True)

        self.assertEqual(raised.exception.code, 1)
        notifier.notify_all.assert_called_once()

    def test_startup_invalid_token_notify_policy_does_not_exit(self):
        config = self.make_config(policy="notify")
        notifier = MagicMock()
        streamlink_manager = MagicMock()
        streamlink_manager.validate_oauth_token.return_value = AuthValidationStatus.INVALID

        state = streamlink_recorder.validate_auth_or_apply_policy(config, streamlink_manager, notifier, force_notify=True)

        self.assertEqual(state.auth_status, AuthValidationStatus.INVALID)
        notifier.notify_all.assert_called_once()

    def test_unknown_validation_does_not_exit_or_notify(self):
        config = self.make_config(policy="exit")
        notifier = MagicMock()
        streamlink_manager = MagicMock()
        streamlink_manager.validate_oauth_token.return_value = AuthValidationStatus.UNKNOWN

        state = streamlink_recorder.validate_auth_or_apply_policy(config, streamlink_manager, notifier, force_notify=True)

        self.assertEqual(state.auth_status, AuthValidationStatus.UNKNOWN)
        notifier.notify_all.assert_not_called()

    def test_handle_recording_error_invalid_token_exits(self):
        config = self.make_config(policy="exit")
        notifier = MagicMock()
        streamlink_manager = MagicMock()
        streamlink_manager.is_invalid_twitch_auth_error.return_value = True

        with self.assertRaises(SystemExit) as raised:
            streamlink_recorder.handle_recording_error(config, streamlink_manager, notifier, Exception('Unauthorized: The "Authorization" token is invalid.'))

        self.assertEqual(raised.exception.code, 1)
        notifier.notify_all.assert_called_once()

    def test_handle_recording_error_non_auth_continues(self):
        config = self.make_config(policy="exit")
        notifier = MagicMock()
        streamlink_manager = MagicMock()
        streamlink_manager.is_invalid_twitch_auth_error.return_value = False

        streamlink_recorder.handle_recording_error(config, streamlink_manager, notifier, RuntimeError("network failure"))

        notifier.notify_all.assert_called_once()

    def test_notify_mode_skips_recording_when_auth_invalid(self):
        state = streamlink_recorder.RecorderState(auth_status=AuthValidationStatus.INVALID)

        self.assertFalse(streamlink_recorder.should_attempt_recording(self.make_config(policy="notify"), state))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
python -m unittest test_recorder_auth_validation.py -v
```

Expected: FAIL because recorder helper functions/state do not exist.

- [ ] **Step 3: Implement recorder state and policy helpers**

In `streamlink-recorder.py`, add imports:

```python
from dataclasses import dataclass
from streamlink_manager import AuthValidationStatus
```

Replace existing `from streamlink_manager import StreamlinkManager` with:

```python
from streamlink_manager import AuthValidationStatus, StreamlinkManager
```

Add after `parse_auth_invalid_policy`:

```python
@dataclass
class RecorderState:
    auth_status: AuthValidationStatus = AuthValidationStatus.NOT_CONFIGURED
    last_auth_validation_time: float = 0
    invalid_auth_notified: bool = False


def invalid_auth_message(config):
    return f"Twitch playback auth token is invalid for {config.user}. Renew oauthtoken/TWITCH_AUTH_TOKEN and restart the recorder."


def apply_invalid_auth_policy(config, notifier_manager, state):
    message = invalid_auth_message(config)
    logger.error(message)
    if not state.invalid_auth_notified:
        notifier_manager.notify_all(message)
        state.invalid_auth_notified = True
    state.auth_status = AuthValidationStatus.INVALID
    if config.auth_invalid_policy == "exit":
        raise SystemExit(1)
    return state


def validate_auth_or_apply_policy(config, streamlink_manager, notifier_manager, state=None, force_notify=False):
    state = state or RecorderState()
    status = streamlink_manager.validate_oauth_token(config.user)
    state.auth_status = status
    state.last_auth_validation_time = time.time()

    if status == AuthValidationStatus.INVALID:
        if force_notify:
            state.invalid_auth_notified = False
        return apply_invalid_auth_policy(config, notifier_manager, state)

    if status == AuthValidationStatus.VALID_OR_NOT_REJECTED:
        if state.invalid_auth_notified:
            notifier_manager.notify_all(f"Twitch playback auth token validation recovered for {config.user}. Recording is enabled again.")
        state.invalid_auth_notified = False

    if status == AuthValidationStatus.UNKNOWN:
        logger.warning("Unable to validate Twitch playback auth token for %s; will retry later", config.user)

    return state


def should_validate_auth(config, state):
    if not config.oauth_token:
        return False
    return time.time() - state.last_auth_validation_time >= config.auth_validation_interval


def should_attempt_recording(config, state):
    return not (config.auth_invalid_policy == "notify" and state.auth_status == AuthValidationStatus.INVALID)


def handle_recording_error(config, streamlink_manager, notifier_manager, error, state=None):
    state = state or RecorderState()
    if streamlink_manager.is_invalid_twitch_auth_error(error):
        return apply_invalid_auth_policy(config, notifier_manager, state)

    message = f"Recording {config.user} failed: {type(error).__name__}. Recorder will continue checking."
    logger.error(message)
    notifier_manager.notify_all(message)
    return state
```

- [ ] **Step 4: Integrate helpers into `loop_check()`**

In `loop_check(config)`, after managers are created, add:

```python
    state = validate_auth_or_apply_policy(config, streamlink_manager, notifier_manager, force_notify=True)
```

At the top of the `while True:` body, before `check_user`, add:

```python
        if should_validate_auth(config, state):
            state = validate_auth_or_apply_policy(config, streamlink_manager, notifier_manager, state=state)
```

Inside the `ONLINE` branch, before building filename, add:

```python
            if not should_attempt_recording(config, state):
                logger.error("Skipping recording for %s because Twitch playback auth token is invalid", config.user)
                time.sleep(config.timer)
                continue
```

Wrap `run_streamlink()`:

```python
            try:
                streamlink_manager.run_streamlink(config.user, recorded_filename)
            except Exception as error:
                state = handle_recording_error(config, streamlink_manager, notifier_manager, error, state=state)
                time.sleep(config.timer)
                continue
```

- [ ] **Step 5: Run tests and commit**

Run:

```bash
python -m unittest test_recorder_auth_validation.py -v
python -m unittest discover -v
```

Expected: PASS.

Commit:

```bash
git add streamlink-recorder.py test_recorder_auth_validation.py
git commit -m "feat: apply twitch auth invalid token policy"
```

---

## Task 4: README documentation for #116 behavior

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README**

In `README.md`, after the Twitch auth-token renewal section, add:

```markdown
### Invalid playback auth-token behavior

When `oauthtoken`, `TWITCH_AUTH_TOKEN`, or `TWITCH_OAUTH_TOKEN` is configured, the recorder validates the Twitch playback token at startup and periodically while running.

The default invalid-token policy is `exit`:

```env
TWITCH_AUTH_INVALID_TOKEN_POLICY=exit
```

If Twitch confirms the playback token is invalid, the recorder logs a clear error, sends Slack/Telegram notification if configured, and exits non-zero. In Kubernetes this can surface as a restarting pod or `CrashLoopBackOff`; renew the token in the Secret and restart or roll out the deployment.

To keep the process alive instead, set:

```env
TWITCH_AUTH_INVALID_TOKEN_POLICY=notify
```

In `notify` mode, the recorder logs/notifies the invalid token, keeps checking stream status, and skips recording attempts while the token remains known invalid.

Validation interval defaults to one hour:

```env
TWITCH_AUTH_VALIDATION_INTERVAL=3600
```

Unknown validation failures, such as temporary network errors, do not cause the recorder to exit. Only confirmed invalid-token errors apply the invalid-token policy.
```

- [ ] **Step 2: Verify markdown diff and tests**

Run:

```bash
git diff --check -- README.md
python -m unittest discover -v
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document invalid twitch auth token behavior"
```

---

## Task 5: Final verification and issue handoff

**Files:**
- No code changes expected.

- [ ] **Step 1: Run full tests**

Run:

```bash
python -m unittest discover -v
```

Expected: PASS.

- [ ] **Step 2: Run targeted secret checks**

Run:

```bash
rg -n "Authorization=OAuth [A-Za-z0-9_-]{12,}|secret-refresh-token-value|super-secret|definitely-invalid-token" streamlink_manager.py streamlink-recorder.py test_streamlink_manager.py test_recorder_auth_validation.py README.md
```

Expected: no matches except intentionally fake test strings `secret-refresh-token-value` and `super-secret` in existing tests if included in the searched files. If those expected fake strings appear, confirm they are test constants only.

- [ ] **Step 3: Verify git status**

Run:

```bash
git status --short --branch
```

Expected: clean except local `security_best_practices_report.md`.

- [ ] **Step 4: Prepare issue comment**

Use this summary when pushing/closing #116:

```markdown
Implemented auth-token validation and invalid-token handling.

Summary:
- Added Streamlink-based playback auth-token validation.
- Confirmed invalid Twitch Authorization token errors are classified separately from unknown/transient validation failures.
- Added configurable invalid-token policy: `exit` default, `notify` optional.
- Startup/periodic validation now detects invalid configured playback tokens.
- Recording errors are caught; invalid-token failures apply policy, non-auth failures notify/log and continue.
- README documents Kubernetes/monitoring behavior and config.

Validation:
- `python -m unittest discover -v` passed.
```

---

## Self-Review Against Spec

Spec coverage:

- `AuthValidationStatus`: Task 1.
- Shared Streamlink session/auth setup: Task 1.
- Startup validation: Task 3.
- Periodic validation: Task 3.
- Default `exit` policy and optional `notify` policy: Tasks 2 and 3.
- Unknown validation does not exit: Task 3.
- Recording exception handling: Task 3.
- Notify-mode skip behavior: Task 3.
- README docs: Task 4.
- No unauthenticated fallback: maintained by all tasks.

The plan intentionally does not add Kubernetes readiness/liveness endpoints or unauthenticated fallback recording.
