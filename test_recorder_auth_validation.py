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
