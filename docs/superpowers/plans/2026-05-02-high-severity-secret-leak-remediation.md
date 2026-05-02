# High-Severity Secret Leak Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove high-severity secret leak paths while preserving existing CLI, Docker, Compose, and Helm/Kubernetes deployment compatibility.

**Architecture:** Keep the current small-module structure. Add focused tests first, then make minimal changes in `twitch_manager.py`, `notification_manager.py`, `streamlink-recorder.py`, and `Dockerfile`. Configuration resolution stays inside `streamlink-recorder.py` so existing consumers of `AppConfig` do not need to change.

**Tech Stack:** Python 3.14, `unittest`, `unittest.mock`, Dockerfile, existing `requests`, `twitchAPI`, and `streamlink` dependencies.

---

## File Structure

- Modify: `twitch_manager.py`
  - Responsibility: Twitch Helix polling and Twitch app token refresh callback.
  - Change: log token refresh without logging token value.

- Modify: `notification_manager.py`
  - Responsibility: Slack/Telegram notification delivery.
  - Change: add safe notification error logging shared by notifiers.

- Modify: `streamlink-recorder.py`
  - Responsibility: CLI parsing, config construction, main recorder loop.
  - Change: add env fallback while preserving existing CLI flags and `AppConfig` attributes.

- Modify: `Dockerfile`
  - Responsibility: container image runtime startup.
  - Change: use exec-form entrypoint without expanding secrets into process args.

- Create: `test_twitch_manager.py`
  - Tests Twitch token refresh callback does not log token value.

- Create: `test_notification_manager.py`
  - Tests Slack and Telegram HTTP failure logs do not contain token-bearing secret material.

- Create: `test_config.py`
  - Tests CLI/env precedence, legacy env compatibility, missing required values, and invalid env timer handling.

Existing tests in `test_streamlink_manager.py` must continue to pass.

---

### Task 1: Stop logging Twitch app refresh token

**Files:**
- Create: `test_twitch_manager.py`
- Modify: `twitch_manager.py:20-21`

- [ ] **Step 1: Write the failing test**

Create `test_twitch_manager.py` with:

```python
import asyncio
import unittest
from unittest.mock import MagicMock

from twitch_manager import TwitchManager


class TestTwitchManagerSecurity(unittest.TestCase):
    def test_app_refresh_does_not_log_token_value(self):
        manager = TwitchManager(MagicMock())
        secret_token = "secret-refresh-token-value"

        with self.assertLogs("twitch_manager", level="INFO") as captured:
            asyncio.run(manager.app_refresh(secret_token))

        logs = "\n".join(captured.output)
        self.assertIn("Twitch app token refreshed", logs)
        self.assertNotIn(secret_token, logs)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
python -m unittest test_twitch_manager.py -v
```

Expected: FAIL because the current log contains `secret-refresh-token-value` and does not contain `Twitch app token refreshed`.

- [ ] **Step 3: Implement the minimal fix**

In `twitch_manager.py`, replace:

```python
    async def app_refresh(self, token: str):
        logger.info(f'my new app token is: {token}')
```

with:

```python
    async def app_refresh(self, token: str):
        logger.info("Twitch app token refreshed")
```

Do not log `token` anywhere.

- [ ] **Step 4: Run the focused test**

Run:

```bash
python -m unittest test_twitch_manager.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add twitch_manager.py test_twitch_manager.py
git commit -m "fix: avoid logging twitch app token"
```

---

### Task 2: Redact notifier HTTP failure logs

**Files:**
- Create: `test_notification_manager.py`
- Modify: `notification_manager.py:1-99`

- [ ] **Step 1: Write failing tests for Slack and Telegram HTTP failures**

Create `test_notification_manager.py` with:

```python
import unittest
from unittest.mock import MagicMock, patch

import requests

from notification_manager import SlackNotifier, TelegramNotifier


class TestNotificationManagerSecurity(unittest.TestCase):
    def _mock_http_error_response(self, status_code, reason):
        response = MagicMock()
        response.status_code = status_code
        response.reason = reason
        response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            f"{status_code} Client Error: {reason} for url: https://example.invalid/secret-token",
            response=response,
        )
        return response

    @patch("notification_manager.requests.post")
    def test_slack_http_error_does_not_log_webhook_secret(self, mock_post):
        webhook_secret = "T00000000/B00000000/super-secret-slack-token"
        mock_post.return_value = self._mock_http_error_response(403, "Forbidden")

        notifier = SlackNotifier(webhook_secret)

        with self.assertLogs("notification_manager", level="ERROR") as captured:
            notifier.notify("hello")

        logs = "\n".join(captured.output)
        self.assertIn("Slack notification failed with HTTP 403 Forbidden", logs)
        self.assertNotIn(webhook_secret, logs)
        self.assertNotIn("super-secret-slack-token", logs)
        self.assertNotIn("hooks.slack.com", logs)

    @patch("notification_manager.requests.post")
    def test_telegram_http_error_does_not_log_bot_token(self, mock_post):
        bot_token = "123456789:super-secret-telegram-token"
        mock_post.return_value = self._mock_http_error_response(401, "Unauthorized")

        notifier = TelegramNotifier(bot_token, "123456")

        with self.assertLogs("notification_manager", level="ERROR") as captured:
            notifier.notify("hello")

        logs = "\n".join(captured.output)
        self.assertIn("Telegram notification failed with HTTP 401 Unauthorized", logs)
        self.assertNotIn(bot_token, logs)
        self.assertNotIn("super-secret-telegram-token", logs)
        self.assertNotIn("api.telegram.org", logs)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m unittest test_notification_manager.py -v
```

Expected: FAIL because current logs include raw HTTP exception strings instead of the safe `Slack notification failed...` and `Telegram notification failed...` messages.

- [ ] **Step 3: Add safe shared logging helpers**

In `notification_manager.py`, after `class Notifier(ABC): ...`, add:

```python

def _log_notification_http_error(service_name, error):
    response = getattr(error, "response", None)
    if response is None:
        logger.error("%s notification failed with an HTTP error", service_name)
        return

    status_code = getattr(response, "status_code", "unknown")
    reason = getattr(response, "reason", "")
    if reason:
        logger.error("%s notification failed with HTTP %s %s", service_name, status_code, reason)
    else:
        logger.error("%s notification failed with HTTP %s", service_name, status_code)


def _log_notification_unexpected_error(service_name, error):
    logger.error(
        "Unexpected error occurred while sending message to %s: %s",
        service_name,
        type(error).__name__,
    )
```

These helpers intentionally do not log URLs, raw exception strings, request objects, response bodies, or secret values.

- [ ] **Step 4: Update Slack notifier exception handling**

In `SlackNotifier.notify`, replace:

```python
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error occurred: {e}")
        except Exception as e:
            logger.error(f"Unexpected error occurred while sending message to Slack: {e}")
```

with:

```python
        except requests.exceptions.HTTPError as error:
            _log_notification_http_error("Slack", error)
        except Exception as error:
            _log_notification_unexpected_error("Slack", error)
```

- [ ] **Step 5: Update Telegram notifier exception handling**

In `TelegramNotifier.notify`, replace:

```python
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error occurred: {e}")
        except Exception as exc:
            logger.error(f"Unexpected error occurred while sending message to Telegram: {exc}")
```

with:

```python
        except requests.exceptions.HTTPError as error:
            _log_notification_http_error("Telegram", error)
        except Exception as error:
            _log_notification_unexpected_error("Telegram", error)
```

- [ ] **Step 6: Run focused notifier tests**

Run:

```bash
python -m unittest test_notification_manager.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add notification_manager.py test_notification_manager.py
git commit -m "fix: redact notification secrets from logs"
```

---

### Task 3: Add non-breaking environment fallback configuration

**Files:**
- Create: `test_config.py`
- Modify: `streamlink-recorder.py:20-68`

- [ ] **Step 1: Write failing config tests**

Create `test_config.py` with:

```python
import importlib.util
import io
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).with_name("streamlink-recorder.py")
spec = importlib.util.spec_from_file_location("streamlink_recorder", MODULE_PATH)
streamlink_recorder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(streamlink_recorder)


class TestConfigParsing(unittest.TestCase):
    def parse_with_env(self, argv, env):
        with patch.dict(os.environ, env, clear=True):
            return streamlink_recorder.parse_arguments(argv)

    def test_cli_arguments_populate_config(self):
        config = self.parse_with_env(
            [
                "-user", "cli-user",
                "-timer", "123",
                "-quality", "best",
                "-clientid", "cli-client-id",
                "-clientsecret", "cli-client-secret",
                "-slackid", "cli-slack",
                "-gamelist", "game-a,game-b",
                "-telegrambottoken", "cli-telegram-token",
                "-telegramchatid", "cli-chat",
                "-oauthtoken", "cli-oauth",
            ],
            {},
        )

        self.assertEqual(config.user, "cli-user")
        self.assertEqual(config.timer, 123)
        self.assertEqual(config.quality, "best")
        self.assertEqual(config.client_id, "cli-client-id")
        self.assertEqual(config.client_secret, "cli-client-secret")
        self.assertEqual(config.slack_id, "cli-slack")
        self.assertEqual(config.game_list, "game-a,game-b")
        self.assertEqual(config.telegram_bot_token, "cli-telegram-token")
        self.assertEqual(config.telegram_chat_id, "cli-chat")
        self.assertEqual(config.oauth_token, "cli-oauth")

    def test_cli_arguments_override_environment_values(self):
        config = self.parse_with_env(
            [
                "-user", "cli-user",
                "-timer", "321",
                "-quality", "cli-quality",
                "-clientid", "cli-client-id",
                "-clientsecret", "cli-client-secret",
                "-oauthtoken", "cli-oauth",
            ],
            {
                "TWITCH_USER": "env-user",
                "TIMER": "123",
                "STREAM_QUALITY": "env-quality",
                "TWITCH_CLIENT_ID": "env-client-id",
                "TWITCH_CLIENT_SECRET": "env-client-secret",
                "TWITCH_AUTH_TOKEN": "env-oauth",
            },
        )

        self.assertEqual(config.user, "cli-user")
        self.assertEqual(config.timer, 321)
        self.assertEqual(config.quality, "cli-quality")
        self.assertEqual(config.client_id, "cli-client-id")
        self.assertEqual(config.client_secret, "cli-client-secret")
        self.assertEqual(config.oauth_token, "cli-oauth")

    def test_modern_environment_fallback_populates_config(self):
        config = self.parse_with_env(
            [],
            {
                "TWITCH_USER": "env-user",
                "TIMER": "456",
                "STREAM_QUALITY": "1080p60",
                "TWITCH_CLIENT_ID": "env-client-id",
                "TWITCH_CLIENT_SECRET": "env-client-secret",
                "SLACK_ID": "env-slack",
                "GAME_LIST": "game-1",
                "TELEGRAM_BOT_TOKEN": "env-telegram-token",
                "TELEGRAM_CHAT_ID": "env-chat",
                "TWITCH_AUTH_TOKEN": "env-oauth",
            },
        )

        self.assertEqual(config.user, "env-user")
        self.assertEqual(config.timer, 456)
        self.assertEqual(config.quality, "1080p60")
        self.assertEqual(config.client_id, "env-client-id")
        self.assertEqual(config.client_secret, "env-client-secret")
        self.assertEqual(config.slack_id, "env-slack")
        self.assertEqual(config.game_list, "game-1")
        self.assertEqual(config.telegram_bot_token, "env-telegram-token")
        self.assertEqual(config.telegram_chat_id, "env-chat")
        self.assertEqual(config.oauth_token, "env-oauth")

    def test_legacy_lowercase_environment_fallback_populates_config(self):
        config = self.parse_with_env(
            [],
            {
                "user": "legacy-user",
                "timer": "789",
                "quality": "720p",
                "clientid": "legacy-client-id",
                "clientsecret": "legacy-client-secret",
                "slackid": "legacy-slack",
                "gamelist": "legacy-game",
                "telegrambottoken": "legacy-telegram-token",
                "telegramchatid": "legacy-chat",
                "oauthtoken": "legacy-oauth",
            },
        )

        self.assertEqual(config.user, "legacy-user")
        self.assertEqual(config.timer, 789)
        self.assertEqual(config.quality, "720p")
        self.assertEqual(config.client_id, "legacy-client-id")
        self.assertEqual(config.client_secret, "legacy-client-secret")
        self.assertEqual(config.slack_id, "legacy-slack")
        self.assertEqual(config.game_list, "legacy-game")
        self.assertEqual(config.telegram_bot_token, "legacy-telegram-token")
        self.assertEqual(config.telegram_chat_id, "legacy-chat")
        self.assertEqual(config.oauth_token, "legacy-oauth")

    def test_twitch_oauth_token_env_alias_is_supported(self):
        config = self.parse_with_env(
            [],
            {
                "TWITCH_USER": "env-user",
                "TWITCH_CLIENT_ID": "env-client-id",
                "TWITCH_CLIENT_SECRET": "env-client-secret",
                "TWITCH_OAUTH_TOKEN": "env-oauth-alias",
            },
        )

        self.assertEqual(config.oauth_token, "env-oauth-alias")

    def test_missing_required_config_fails_clearly(self):
        stderr = io.StringIO()
        with patch.dict(os.environ, {}, clear=True), patch.object(sys, "stderr", stderr):
            with self.assertRaises(SystemExit) as raised:
                streamlink_recorder.parse_arguments([])

        self.assertNotEqual(raised.exception.code, 0)
        self.assertIn("Missing required configuration: user", stderr.getvalue())
        self.assertIn("TWITCH_USER", stderr.getvalue())

    def test_invalid_environment_timer_fails_clearly(self):
        stderr = io.StringIO()
        env = {
            "TWITCH_USER": "env-user",
            "TIMER": "not-an-int",
            "TWITCH_CLIENT_ID": "env-client-id",
            "TWITCH_CLIENT_SECRET": "env-client-secret",
        }
        with patch.dict(os.environ, env, clear=True), patch.object(sys, "stderr", stderr):
            with self.assertRaises(SystemExit) as raised:
                streamlink_recorder.parse_arguments([])

        self.assertNotEqual(raised.exception.code, 0)
        self.assertIn("Invalid integer for timer", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run config tests to verify they fail**

Run:

```bash
python -m unittest test_config.py -v
```

Expected: FAIL because `parse_arguments()` currently accepts no `argv` parameter and required parser args do not use env fallback.

- [ ] **Step 3: Update `AppConfig` to hold resolved values**

In `streamlink-recorder.py`, replace the current `AppConfig` class:

```python
class AppConfig:
    def __init__(self, args):
        self.timer = args.timer
        self.user = args.user
        self.quality = args.quality
        self.client_id = args.clientid
        self.client_secret = args.clientsecret
        self.game_list = args.gamelist
        self.slack_id = args.slackid
        self.telegram_bot_token = args.telegrambottoken
        self.telegram_chat_id = args.telegramchatid
        self.oauth_token = args.oauthtoken
```

with:

```python
class AppConfig:
    def __init__(
        self,
        timer,
        user,
        quality,
        client_id,
        client_secret,
        game_list,
        slack_id,
        telegram_bot_token,
        telegram_chat_id,
        oauth_token,
    ):
        self.timer = timer
        self.user = user
        self.quality = quality
        self.client_id = client_id
        self.client_secret = client_secret
        self.game_list = game_list
        self.slack_id = slack_id
        self.telegram_bot_token = telegram_bot_token
        self.telegram_chat_id = telegram_chat_id
        self.oauth_token = oauth_token
```

- [ ] **Step 4: Add config resolution helpers**

In `streamlink-recorder.py`, after `AppConfig`, add:

```python

def first_config_value(cli_value, env_names, default=None):
    if cli_value not in (None, ""):
        return cli_value

    for env_name in env_names:
        env_value = os.environ.get(env_name)
        if env_value not in (None, ""):
            return env_value

    return default


def require_config(parser, value, field_name, cli_arg, env_names):
    if value not in (None, ""):
        return value

    env_hint = ", ".join(env_names)
    parser.error(f"Missing required configuration: {field_name} (set {cli_arg}, {env_hint})")


def parse_timer_value(parser, value):
    try:
        return int(value)
    except (TypeError, ValueError):
        parser.error(f"Invalid integer for timer: {value}")
```

- [ ] **Step 5: Update parser arguments and fallback logic**

Replace the full `parse_arguments()` function in `streamlink-recorder.py` with:

```python
def parse_arguments(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("-timer", type=int, help="Stream check interval (less than 15s are not recommended)")
    parser.add_argument("-user", help="Twitch user that we are checking")
    parser.add_argument("-quality", help="Recording quality")
    parser.add_argument("-clientid", help="Your Twitch app client id")
    parser.add_argument("-clientsecret", help="Your Twitch app client secret")
    parser.add_argument("-slackid", help="Your slack app client id")
    parser.add_argument("-gamelist", help="The game list to be recorded")
    parser.add_argument("-telegrambottoken", help="Your Telegram bot token")
    parser.add_argument("-telegramchatid", help="Your Telegram chat ID where the bot will send messages")
    parser.add_argument("-oauthtoken", help="Your OAuth token for Twitch API")
    args = parser.parse_args(argv)

    user = require_config(
        parser,
        first_config_value(args.user, ("TWITCH_USER", "user")),
        "user",
        "-user",
        ("TWITCH_USER", "user"),
    )
    client_id = require_config(
        parser,
        first_config_value(args.clientid, ("TWITCH_CLIENT_ID", "clientid")),
        "clientid",
        "-clientid",
        ("TWITCH_CLIENT_ID", "clientid"),
    )
    client_secret = require_config(
        parser,
        first_config_value(args.clientsecret, ("TWITCH_CLIENT_SECRET", "clientsecret")),
        "clientsecret",
        "-clientsecret",
        ("TWITCH_CLIENT_SECRET", "clientsecret"),
    )

    timer = parse_timer_value(parser, first_config_value(args.timer, ("TIMER", "timer"), 240))

    return AppConfig(
        timer=timer,
        user=user,
        quality=first_config_value(args.quality, ("STREAM_QUALITY", "quality"), "720p60,720p,best"),
        client_id=client_id,
        client_secret=client_secret,
        game_list=first_config_value(args.gamelist, ("GAME_LIST", "gamelist"), ""),
        slack_id=first_config_value(args.slackid, ("SLACK_ID", "slackid")),
        telegram_bot_token=first_config_value(args.telegrambottoken, ("TELEGRAM_BOT_TOKEN", "telegrambottoken")),
        telegram_chat_id=first_config_value(args.telegramchatid, ("TELEGRAM_CHAT_ID", "telegramchatid")),
        oauth_token=first_config_value(args.oauthtoken, ("TWITCH_AUTH_TOKEN", "TWITCH_OAUTH_TOKEN", "oauthtoken")),
    )
```

- [ ] **Step 6: Run config tests**

Run:

```bash
python -m unittest test_config.py -v
```

Expected: PASS.

- [ ] **Step 7: Run existing streamlink manager tests**

Run:

```bash
python -m unittest test_streamlink_manager.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add streamlink-recorder.py test_config.py
git commit -m "feat: support env fallback for recorder config"
```

---

### Task 4: Stop Docker entrypoint from expanding secrets into argv

**Files:**
- Modify: `Dockerfile:24-25`

- [ ] **Step 1: Verify current Dockerfile contains secret-expanding entrypoint**

Run:

```bash
grep -n "ENTRYPOINT python ./streamlink-recorder.py" Dockerfile
```

Expected: output includes the current shell-form entrypoint with `-clientsecret=${clientsecret}` and `-oauthtoken=${oauthtoken}`.

- [ ] **Step 2: Update Dockerfile entrypoint**

In `Dockerfile`, replace:

```dockerfile
# Set the entrypoint
ENTRYPOINT python ./streamlink-recorder.py -user=${user} -timer=${timer} -quality=${quality} -clientid=${clientid} -clientsecret=${clientsecret} -slackid=${slackid} -gamelist="${gamelist}" -telegramchatid=${telegramchatid} -telegrambottoken=${telegrambottoken} -oauthtoken=${oauthtoken}
```

with:

```dockerfile
# Set the entrypoint without expanding secrets into process arguments.
ENTRYPOINT ["python", "./streamlink-recorder.py"]
```

- [ ] **Step 3: Verify secret-expanding entrypoint is gone**

Run:

```bash
! grep -n "clientsecret=.*oauthtoken" Dockerfile
```

Expected: command exits 0 with no output.

Run:

```bash
grep -n 'ENTRYPOINT \["python", "./streamlink-recorder.py"\]' Dockerfile
```

Expected: output contains the exec-form entrypoint.

- [ ] **Step 4: Run config compatibility tests again**

Run:

```bash
python -m unittest test_config.py -v
```

Expected: PASS, proving existing lowercase Docker/Kubernetes env keys are read by the Python app.

- [ ] **Step 5: Commit**

```bash
git add Dockerfile
git commit -m "fix: avoid exposing secrets in container args"
```

---

### Task 5: Full verification and report update

**Files:**
- Modify: `security_best_practices_report.md` if the team wants the report to reflect remediated status.

- [ ] **Step 1: Run all unit tests**

Run:

```bash
python -m unittest discover -v
```

Expected: PASS for all tests, including:

- `test_config.py`
- `test_notification_manager.py`
- `test_streamlink_manager.py`
- `test_twitch_manager.py`

- [ ] **Step 2: Run targeted secret-leak greps**

Run:

```bash
rg -n "my new app token is|HTTP error occurred: \{e\}|HTTP error occurred: \{exc\}|ENTRYPOINT python ./streamlink-recorder.py|clientsecret=\$\{clientsecret\}|oauthtoken=\$\{oauthtoken\}" twitch_manager.py notification_manager.py Dockerfile streamlink-recorder.py
```

Expected: no matches.

- [ ] **Step 3: Verify legacy env compatibility manually**

Run:

```bash
user=legacy-user \
timer=240 \
quality=best \
clientid=legacy-client-id \
clientsecret=legacy-client-secret \
python - <<'PY'
import importlib.util
from pathlib import Path
spec = importlib.util.spec_from_file_location('streamlink_recorder', Path('streamlink-recorder.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
config = module.parse_arguments([])
print(config.user)
print(config.timer)
print(config.quality)
print(config.client_id)
print(config.client_secret)
PY
```

Expected output:

```text
legacy-user
240
best
legacy-client-id
legacy-client-secret
```

- [ ] **Step 4: Verify modern env compatibility manually**

Run:

```bash
TWITCH_USER=modern-user \
TIMER=360 \
STREAM_QUALITY=1080p60 \
TWITCH_CLIENT_ID=modern-client-id \
TWITCH_CLIENT_SECRET=modern-client-secret \
python - <<'PY'
import importlib.util
from pathlib import Path
spec = importlib.util.spec_from_file_location('streamlink_recorder', Path('streamlink-recorder.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
config = module.parse_arguments([])
print(config.user)
print(config.timer)
print(config.quality)
print(config.client_id)
print(config.client_secret)
PY
```

Expected output:

```text
modern-user
360
1080p60
modern-client-id
modern-client-secret
```

- [ ] **Step 5: Optionally update `security_best_practices_report.md`**

If committing the report with remediation status, add a short status note under SEC-001, SEC-002, and SEC-003:

```markdown
**Remediation status:** Addressed in this branch by changing config fallback, Docker entrypoint behavior, notifier logging, and Twitch refresh logging. Verify before closing related issues.
```

If the report is intended as an initial assessment artifact only, leave it uncommitted and do not edit it.

- [ ] **Step 6: Commit report update only if edited**

If `security_best_practices_report.md` was edited intentionally:

```bash
git add security_best_practices_report.md
git commit -m "docs: update security review remediation status"
```

- [ ] **Step 7: Final status check**

Run:

```bash
git status --short --branch
```

Expected: clean working tree except for intentionally uncommitted local files, if any.

---

## Self-Review Against Spec

Spec coverage:

- SEC-003 Twitch app token logging: Task 1.
- SEC-002 / #115 notification secret log redaction: Task 2.
- SEC-001 / #114 env fallback and Docker argv protection: Tasks 3 and 4.
- Non-breaking CLI/Docker/Compose/Helm compatibility: Task 3 tests legacy lowercase env, modern env, and CLI precedence; Task 4 keeps deployment manifests unchanged.
- Release-note text is documented in the design spec and can be used in PR/release notes.

No out-of-scope items are included: README auth lifecycle docs, #116 validation, #119 VOD backfill, Kubernetes security contexts, path safety, and dependency scanning are deferred.
