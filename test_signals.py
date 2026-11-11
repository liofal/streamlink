import asyncio
import importlib.util
import os
import signal
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import streamlink_manager
from streamlink_manager import StreamlinkManager

MODULE_PATH = Path(__file__).with_name("streamlink-recorder.py")
spec = importlib.util.spec_from_file_location("streamlink_recorder", MODULE_PATH)
streamlink_recorder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(streamlink_recorder)

# The fix adds these; on the original code the tests below fail on the missing
# behavior rather than at import.
StopRequested = getattr(streamlink_manager, "StopRequested", type("StopRequested", (BaseException,), {}))
install_signal_handlers = getattr(streamlink_manager, "install_signal_handlers", lambda: None)

real_open = open


def reset_stop_state():
    state = getattr(streamlink_manager, "_state", None)
    if state is not None:
        state.update(signum=None, shield=0, pending=False)


class SignalTestCase(unittest.TestCase):
    def setUp(self):
        for sig in (signal.SIGTERM, signal.SIGINT):
            self.addCleanup(signal.signal, sig, signal.getsignal(sig))
        self.addCleanup(reset_stop_state)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        self.base = os.path.join(self.dir, "rec")
        config = MagicMock(oauth_token=None, quality="best")
        self.manager = StreamlinkManager(config)
        self.fd = MagicMock()
        stream = MagicMock(url="http://example.com/playlist.m3u8")
        stream.open.return_value = self.fd
        patcher = patch("streamlink_manager.streamlink.Streamlink")
        self.addCleanup(patcher.stop)
        patcher.start().return_value.streams.return_value = {"best": stream}

    def files(self):
        return sorted(os.listdir(self.dir))

    def content(self, name):
        with real_open(os.path.join(self.dir, name), "rb") as f:
            return f.read()


class TestRecordingShutdown(SignalTestCase):
    def test_sigterm_during_recording_finalizes_file_and_stops(self):
        install_signal_handlers()
        calls = []

        def read(size):
            calls.append(1)
            if len(calls) == 1:
                return b"one"
            if len(calls) == 2:
                os.kill(os.getpid(), signal.SIGTERM)
                return b"two"
            return b"more" if len(calls) < 50 else b""

        self.fd.read.side_effect = read
        with self.assertRaises(StopRequested):
            self.manager.run_streamlink("u", self.base)
        self.assertEqual(self.files(), ["rec.ts"])
        self.assertTrue(self.content("rec.ts").startswith(b"one"))
        self.fd.close.assert_called()
        self.assertLess(len(calls), 5)

    def test_output_file_is_closed_before_rename(self):
        opened = []

        def recording_open(*args, **kwargs):
            f = real_open(*args, **kwargs)
            opened.append(f)
            return f

        states = []
        real_move = streamlink_manager.shutil.move

        def move(src, dst):
            states.append(opened[0].closed)
            return real_move(src, dst)

        self.fd.read.side_effect = [b"data", b""]
        with patch("builtins.open", recording_open), patch("streamlink_manager.shutil.move", move):
            self.manager.run_streamlink("u", self.base)
        self.assertEqual(states, [True])
        self.assertEqual(self.files(), ["rec.ts"])

    def test_signal_during_finalization_still_finalizes_then_stops(self):
        install_signal_handlers()
        real_move = streamlink_manager.shutil.move

        def move(src, dst):
            os.kill(os.getpid(), signal.SIGTERM)
            return real_move(src, dst)

        self.fd.read.side_effect = [b"data", b""]
        with patch("streamlink_manager.shutil.move", move), self.assertRaises(StopRequested):
            self.manager.run_streamlink("u", self.base)
        self.assertEqual(self.files(), ["rec.ts"])

    def test_signal_before_finalize_shield_is_retried(self):
        real_finalize = self.manager.finalize
        calls = []

        def finalize(*args):
            calls.append(1)
            if len(calls) == 1:
                raise StopRequested()  # signal landed before finalize's shield
            return real_finalize(*args)

        self.manager.finalize = finalize
        self.fd.read.side_effect = [b"data", b""]
        with self.assertRaises(StopRequested):
            self.manager.run_streamlink("u", self.base)
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.files(), ["rec.ts"])

    def test_normal_eof_is_finalized(self):
        self.fd.read.side_effect = [b"a", b"b", b""]
        self.manager.run_streamlink("u", self.base)
        self.assertEqual(self.files(), ["rec.ts"])
        self.assertEqual(self.content("rec.ts"), b"ab")


class TestRecordingErrors(SignalTestCase):
    def test_read_error_leaves_incomplete_marker_not_final_file(self):
        self.fd.read.side_effect = [b"partial", OSError("stall")]
        with self.assertRaises(OSError):
            self.manager.run_streamlink("u", self.base)
        self.assertEqual(self.files(), ["rec.ts.incomplete"])
        self.assertEqual(self.content("rec.ts.incomplete"), b"partial")
        self.fd.close.assert_called()

    def test_write_error_leaves_incomplete_marker(self):
        self.fd.read.side_effect = [b"partial", b"more", b""]

        class FailingFile:
            def __init__(self, f):
                self.f, self.n = f, 0

            def write(self, data):
                self.n += 1
                if self.n == 2:
                    raise OSError("ENOSPC")
                return self.f.write(data)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self.f.close()

        with patch("builtins.open", lambda *a, **k: FailingFile(real_open(*a, **k))):
            with self.assertRaises(OSError):
                self.manager.run_streamlink("u", self.base)
        self.assertEqual(self.files(), ["rec.ts.incomplete"])

    def test_error_before_any_data_leaves_no_file(self):
        self.fd.read.side_effect = OSError("boom")
        with self.assertRaises(OSError):
            self.manager.run_streamlink("u", self.base)
        self.assertEqual(self.files(), [])


class TestStopInsideAsyncio(unittest.TestCase):
    def setUp(self):
        for sig in (signal.SIGTERM, signal.SIGINT):
            self.addCleanup(signal.signal, sig, signal.getsignal(sig))
        self.addCleanup(reset_stop_state)
        install_signal_handlers()

    def make_manager(self):
        from twitch_manager import TwitchManager
        manager = TwitchManager(MagicMock(game_list=""))
        manager.twitch = object()

        async def call(operation, **kwargs):
            # SIGTERM lands inside an event-loop callback, where asyncio would
            # log and swallow a plain BaseException.
            asyncio.get_running_loop().call_soon(os.kill, os.getpid(), signal.SIGTERM)
            await asyncio.sleep(0.2)
            return None

        manager._call_twitch = call
        return manager

    def test_stop_in_asyncio_callback_propagates_from_get_from_twitch(self):
        manager = self.make_manager()
        with self.assertRaises(StopRequested):
            manager.get_from_twitch("get_users", logins="u")
        self.assertIsNone(manager.twitch)  # client reset path re-raised it

    def test_stop_in_asyncio_callback_propagates_from_check_user(self):
        manager = self.make_manager()
        with self.assertRaises(StopRequested):
            manager.check_user("u")

    def test_loop_exits_on_swallowed_stop(self):
        config = MagicMock(user="u", twitch_error_threshold=5, timer=240, oauth_token=None)
        streamlink_manager._state["signum"] = signal.SIGTERM
        with patch.object(streamlink_recorder, "TwitchManager") as tm, \
                patch.object(streamlink_recorder, "StreamlinkManager"), \
                patch.object(streamlink_recorder, "NotificationManager"), \
                patch.object(streamlink_recorder, "validate_auth_or_apply_policy", return_value=streamlink_recorder.RecorderState()):
            with self.assertRaises(StopRequested):
                streamlink_recorder.loop_check(config)
            tm.return_value.check_user.assert_not_called()


class TestRecorderLoopStop(unittest.TestCase):
    def setUp(self):
        for sig in (signal.SIGTERM, signal.SIGINT):
            self.addCleanup(signal.signal, sig, signal.getsignal(sig))
        self.addCleanup(reset_stop_state)

    def test_stop_during_recording_exits_loop_without_notifications(self):
        status = streamlink_recorder.StreamStatus
        config = MagicMock(user="u", twitch_error_threshold=5, timer=240, oauth_token=None, game_list="", record_retries=5)
        notifier = MagicMock()
        with patch.object(streamlink_recorder, "TwitchManager") as tm, \
                patch.object(streamlink_recorder, "StreamlinkManager") as sm, \
                patch.object(streamlink_recorder, "NotificationManager", return_value=notifier), \
                patch.object(streamlink_recorder, "validate_auth_or_apply_policy", return_value=streamlink_recorder.RecorderState()), \
                patch.object(streamlink_recorder, "should_attempt_recording", return_value=True), \
                patch.object(streamlink_recorder.time, "sleep") as sleep:
            tm.return_value.check_user.return_value = (status.ONLINE, "t")
            sm.return_value.run_streamlink.side_effect = StopRequested(signal.SIGTERM)
            with self.assertRaises(StopRequested):
                streamlink_recorder.loop_check(config)
        messages = [c.args[0] for c in notifier.notify_all.call_args_list]
        self.assertEqual(messages, [])  # "Recording" is sent from on_start, which never ran
        sleep.assert_not_called()

    def test_real_sigterm_while_sleeping_exits_loop(self):
        status = streamlink_recorder.StreamStatus
        config = MagicMock(user="u", twitch_error_threshold=5, timer=240, oauth_token=None)
        install_signal_handlers()

        def sleep(seconds):
            os.kill(os.getpid(), signal.SIGTERM)

        with patch.object(streamlink_recorder, "TwitchManager") as tm, \
                patch.object(streamlink_recorder, "StreamlinkManager"), \
                patch.object(streamlink_recorder, "NotificationManager"), \
                patch.object(streamlink_recorder, "validate_auth_or_apply_policy", return_value=streamlink_recorder.RecorderState()), \
                patch.object(streamlink_recorder.time, "sleep", sleep):
            tm.return_value.check_user.return_value = (status.OFFLINE, "")
            with self.assertRaises(StopRequested):
                streamlink_recorder.loop_check(config)

    def test_main_returns_cleanly_on_stop(self):
        if not hasattr(streamlink_recorder, "install_signal_handlers"):
            self.fail("main() does not install signal handlers")
        with patch.object(streamlink_recorder, "parse_arguments", return_value=MagicMock(user="u", timer=1, quality="best")), \
                patch.object(streamlink_recorder, "install_signal_handlers") as install, \
                patch.object(streamlink_recorder, "loop_check", side_effect=StopRequested(signal.SIGTERM)):
            streamlink_recorder.main()
        install.assert_called_once()


if __name__ == "__main__":
    unittest.main()
