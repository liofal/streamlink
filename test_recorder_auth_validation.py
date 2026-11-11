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

    def test_unknown_validation_preserves_prior_invalid_state(self):
        config = self.make_config(policy="notify")
        notifier = MagicMock()
        streamlink_manager = MagicMock()
        streamlink_manager.validate_oauth_token.return_value = AuthValidationStatus.UNKNOWN

        state = streamlink_recorder.RecorderState(
            auth_status=AuthValidationStatus.INVALID,
            invalid_auth_notified=True,
        )

        result = streamlink_recorder.validate_auth_or_apply_policy(
            config, streamlink_manager, notifier, state=state
        )

        self.assertEqual(result.auth_status, AuthValidationStatus.INVALID)
        self.assertFalse(streamlink_recorder.should_attempt_recording(config, result))
        notifier.notify_all.assert_not_called()


class TestTwitchErrorTracking(unittest.TestCase):
    def setUp(self):
        self.config = MagicMock(user="testuser", twitch_error_threshold=3, timer=240)
        self.notifier = MagicMock()
        self.state = streamlink_recorder.RecorderState()
        self.status = streamlink_recorder.StreamStatus

    def track(self, status):
        return streamlink_recorder.track_twitch_status(self.config, self.notifier, status, self.state)

    def test_notifies_once_when_threshold_reached(self):
        for _ in range(2):
            self.track(self.status.ERROR)
        self.notifier.notify_all.assert_not_called()
        for _ in range(4):
            self.track(self.status.ERROR)
        self.notifier.notify_all.assert_called_once()
        message = self.notifier.notify_all.call_args[0][0]
        self.assertIn("testuser", message)
        self.assertIn("3 times", message)

    def test_recovery_notifies_once_and_resets(self):
        for _ in range(3):
            self.track(self.status.ERROR)
        self.track(self.status.OFFLINE)
        self.track(self.status.OFFLINE)
        self.assertEqual(self.notifier.notify_all.call_count, 2)
        self.assertIn("recovered", self.notifier.notify_all.call_args[0][0])
        self.assertEqual(self.state.consecutive_twitch_errors, 0)
        self.assertFalse(self.state.twitch_errors_notified)

    def test_blip_below_threshold_is_silent_and_resets_count(self):
        self.track(self.status.ERROR)
        self.track(self.status.ONLINE)
        self.notifier.notify_all.assert_not_called()
        self.assertEqual(self.state.consecutive_twitch_errors, 0)

    def test_backoff_doubles_and_caps(self):
        backoff = streamlink_recorder.error_backoff_seconds
        self.assertEqual([backoff(240, n) for n in (1, 2, 3, 4)], [240, 480, 600, 600])
        self.assertEqual(backoff(900, 5), 900)
        self.assertEqual(backoff(15, 1), 15)

    def test_loop_sleeps_with_backoff_on_error_only(self):
        config = MagicMock(user="testuser", twitch_error_threshold=5, timer=240, oauth_token=None)
        statuses = [self.status.ERROR, self.status.ERROR, self.status.OFFLINE]
        sleeps = []

        def fake_sleep(seconds):
            sleeps.append(seconds)
            if len(sleeps) == 3:
                raise KeyboardInterrupt

        with patch.object(streamlink_recorder, "TwitchManager") as tm, \
                patch.object(streamlink_recorder, "StreamlinkManager"), \
                patch.object(streamlink_recorder, "NotificationManager"), \
                patch.object(streamlink_recorder, "validate_auth_or_apply_policy", return_value=streamlink_recorder.RecorderState()), \
                patch.object(streamlink_recorder.time, "sleep", fake_sleep):
            tm.return_value.check_user.side_effect = [(s, "") for s in statuses]
            with self.assertRaises(KeyboardInterrupt):
                streamlink_recorder.loop_check(config)
        self.assertEqual(sleeps, [240, 480, 240])

    def test_threshold_option_parsing(self):
        base = ["-user", "u", "-clientid", "c", "-clientsecret", "s"]
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(streamlink_recorder.parse_arguments(base).twitch_error_threshold, 5)
            self.assertEqual(streamlink_recorder.parse_arguments(base + ["-twitcherrorthreshold", "2"]).twitch_error_threshold, 2)
        with patch.dict("os.environ", {"TWITCH_ERROR_NOTIFY_THRESHOLD": "7"}, clear=True):
            self.assertEqual(streamlink_recorder.parse_arguments(base).twitch_error_threshold, 7)
        with patch.dict("os.environ", {}, clear=True), self.assertRaises(SystemExit):
            streamlink_recorder.parse_arguments(base + ["-twitcherrorthreshold", "x"])


if __name__ == "__main__":
    unittest.main()
