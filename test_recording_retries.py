import errno
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import streamlink_manager

MODULE_PATH = Path(__file__).with_name("streamlink-recorder.py")
spec = importlib.util.spec_from_file_location("streamlink_recorder", MODULE_PATH)
rec = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rec)

Status = rec.StreamStatus


class Stop(KeyboardInterrupt):
    pass


class LoopHarness:
    """Runs loop_check against scripted Helix statuses and run_streamlink outcomes."""

    def __init__(self, statuses, outcomes, retries=5, timer=240):
        self.config = MagicMock(user="u", twitch_error_threshold=5, timer=timer, oauth_token=None,
                                game_list="", record_retries=retries)
        self.statuses = list(statuses)
        self.outcomes = list(outcomes)
        self.sleeps = []
        self.notifier = MagicMock()
        self.state = rec.RecorderState()

    def run(self):
        def fake_sleep(seconds):
            self.sleeps.append(seconds)

        def check_user(_user):
            if not self.statuses:
                raise Stop
            return self.statuses.pop(0), "title"

        def run_streamlink(user, filename, on_start=None):
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, tuple):  # ("started", error): stream opens, then the recording fails
                on_start()
                raise outcome[1]
            if isinstance(outcome, BaseException):
                raise outcome
            on_start()

        with patch.object(rec, "TwitchManager") as tm, \
                patch.object(rec, "StreamlinkManager") as sm, \
                patch.object(rec, "NotificationManager", return_value=self.notifier), \
                patch.object(rec, "validate_auth_or_apply_policy", return_value=self.state), \
                patch.object(rec.time, "sleep", fake_sleep):
            tm.return_value.check_user.side_effect = check_user
            sm.return_value.run_streamlink.side_effect = run_streamlink
            sm.return_value.is_invalid_twitch_auth_error.return_value = False
            with self.assertRaisesStop():
                rec.loop_check(self.config)

    @staticmethod
    def assertRaisesStop():
        return unittest.TestCase().assertRaises(Stop)

    def messages(self):
        return [c.args[0] for c in self.notifier.notify_all.call_args_list]


class TestRetries(unittest.TestCase):
    def test_retry_delay_sequence(self):
        self.assertEqual([rec.retry_delay(n) for n in range(6)], [5, 10, 20, 40, 60, 60])

    def test_empty_streams_retry_quietly_with_backoff(self):
        h = LoopHarness([Status.ONLINE] * 3, [streamlink_manager.NoStreamsAvailable()] * 3)
        h.run()
        self.assertEqual(h.sleeps, [5, 10, 20])
        self.assertEqual(h.messages(), [])

    def test_falls_back_to_timer_after_retries_and_resets_when_offline(self):
        h = LoopHarness([Status.ONLINE] * 4 + [Status.OFFLINE, Status.ONLINE],
                        [streamlink_manager.NoStreamsAvailable()] * 5, retries=2)
        h.run()
        self.assertEqual(h.sleeps, [5, 10, 240, 240, 240, 5])
        self.assertEqual(h.state.start_failures, 1)

    def test_zero_retries_always_uses_timer(self):
        h = LoopHarness([Status.ONLINE], [streamlink_manager.NoStreamsAvailable()], retries=0)
        h.run()
        self.assertEqual(h.sleeps, [240])

    def test_success_rechecks_soon_and_resets(self):
        h = LoopHarness([Status.ONLINE, Status.ONLINE], [streamlink_manager.NoStreamsAvailable(), None])
        h.run()
        self.assertEqual(h.sleeps, [5, rec.RECHECK_DELAY_SECONDS])
        self.assertEqual(h.state.start_failures, 0)
        self.assertEqual(h.messages()[0], "Recording u ...")
        self.assertTrue(h.messages()[1].startswith("Stream u is done"))

    def test_offline_still_sleeps_timer(self):
        h = LoopHarness([Status.OFFLINE], [])
        h.run()
        self.assertEqual(h.sleeps, [240])


class TestFailureReporting(unittest.TestCase):
    def handle(self, error, state=None):
        notifier = MagicMock()
        sm = MagicMock()
        sm.is_invalid_twitch_auth_error.return_value = False
        state = rec.handle_recording_error(MagicMock(user="u"), sm, notifier, error, state=state or rec.RecorderState())
        return notifier, state

    def test_oserror_includes_errno_and_strerror(self):
        notifier, _ = self.handle(OSError(errno.ENOSPC, "whatever https://x?client_secret=abc"))
        message = notifier.notify_all.call_args.args[0]
        self.assertIn(f"errno {errno.ENOSPC}", message)
        self.assertIn("No space left on device", message)
        self.assertNotIn("client_secret", message)

    def test_other_exceptions_never_leak_text(self):
        notifier, _ = self.handle(Exception("https://x?client_secret=abc"))
        message = notifier.notify_all.call_args.args[0]
        self.assertEqual(message, "Recording u failed: Exception. Recorder will continue checking.")

    def test_oserror_without_errno_has_no_text(self):
        notifier, _ = self.handle(OSError("https://x?client_secret=abc"))
        self.assertNotIn("client_secret", notifier.notify_all.call_args.args[0])

    def test_repeated_failure_notifies_once_and_new_key_notifies(self):
        notifier = MagicMock()
        sm = MagicMock()
        sm.is_invalid_twitch_auth_error.return_value = False
        state = rec.RecorderState()
        for error in (OSError(errno.ENOSPC, ""), OSError(errno.ENOSPC, ""), OSError(errno.EIO, ""), OSError(errno.EIO, "")):
            rec.handle_recording_error(MagicMock(user="u"), sm, notifier, error, state=state)
        self.assertEqual(notifier.notify_all.call_count, 2)

    def test_loop_dedups_and_resets_after_success(self):
        err = lambda: OSError(errno.ENOSPC, "")
        h = LoopHarness([Status.ONLINE] * 4, [err(), err(), None, err()])
        h.run()
        failures = [m for m in h.messages() if "failed" in m]
        self.assertEqual(len(failures), 2)  # first, then again after a success reset
        self.assertEqual(h.messages().count("Recording u ..."), 1)

    def test_failure_after_start_repeats_silently_until_success(self):
        def disk_full():
            return ("started", OSError(errno.ENOSPC, ""))
        # 8 attempts with record_retries=3: well past the retries into the timer fallback
        h = LoopHarness([Status.ONLINE] * 10, [disk_full() for _ in range(8)] + [None, disk_full()], retries=3)
        h.run()
        self.assertEqual(h.sleeps, [5, 10, 20] + [240] * 5 + [rec.RECHECK_DELAY_SECONDS, 5])
        failed = "Recording u failed: OSError (errno 28: No space left on device). Recorder will continue checking."
        msgs = h.messages()
        self.assertEqual(msgs[:2], ["Recording u ...", failed])
        self.assertTrue(msgs[2].startswith("Stream u is done"))
        self.assertEqual(msgs[3:], ["Recording u ...", failed])  # new episode after the success


class TestOption(unittest.TestCase):
    def test_option_parsing(self):
        base = ["-user", "u", "-clientid", "c", "-clientsecret", "s"]
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(rec.parse_arguments(base).record_retries, 5)
            self.assertEqual(rec.parse_arguments(base + ["-recordretries", "0"]).record_retries, 0)
        with patch.dict("os.environ", {"RECORD_RETRIES": "7"}, clear=True):
            self.assertEqual(rec.parse_arguments(base).record_retries, 7)
        for bad in ("x", "-1"):
            with patch.dict("os.environ", {}, clear=True), self.assertRaises(SystemExit):
                rec.parse_arguments(base + ["-recordretries", bad])


class TestStopDuringBackoff(unittest.TestCase):
    def test_stop_in_backoff_sleep_propagates(self):
        config = MagicMock(user="u", twitch_error_threshold=5, timer=240, oauth_token=None, game_list="", record_retries=5)
        with patch.object(rec, "TwitchManager") as tm, patch.object(rec, "StreamlinkManager") as sm, \
                patch.object(rec, "NotificationManager"), \
                patch.object(rec, "validate_auth_or_apply_policy", return_value=rec.RecorderState()), \
                patch.object(rec.time, "sleep", side_effect=streamlink_manager.StopRequested(15)):
            tm.return_value.check_user.return_value = (Status.ONLINE, "t")
            sm.return_value.run_streamlink.side_effect = streamlink_manager.NoStreamsAvailable()
            with self.assertRaises(streamlink_manager.StopRequested):
                rec.loop_check(config)


class TestFlushOnExit(unittest.TestCase):
    def run_loop(self, check_user_effect, validate_effect=None):
        config = MagicMock(user="u", twitch_error_threshold=5, timer=240, oauth_token=None, game_list="", record_retries=5)
        notifier = MagicMock()
        with patch.object(rec, "TwitchManager") as tm, patch.object(rec, "StreamlinkManager"), \
                patch.object(rec, "NotificationManager", return_value=notifier), \
                patch.object(rec, "validate_auth_or_apply_policy", return_value=rec.RecorderState(), side_effect=validate_effect):
            tm.return_value.check_user.side_effect = check_user_effect
            try:
                rec.loop_check(config)
            except BaseException as error:
                return notifier, error
        return notifier, None

    def test_flush_called_on_stop(self):
        notifier, error = self.run_loop(streamlink_manager.StopRequested(15))
        self.assertIsInstance(error, streamlink_manager.StopRequested)
        notifier.flush.assert_called_once()

    def test_flush_called_on_invalid_auth_exit(self):
        notifier, error = self.run_loop(None, validate_effect=SystemExit(1))
        self.assertIsInstance(error, SystemExit)
        notifier.flush.assert_called_once()


if __name__ == "__main__":
    unittest.main()
