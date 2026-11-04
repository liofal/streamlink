import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import streamlink_manager
from streamlink_manager import StreamlinkManager
from test_recording_retries import LoopHarness, Status, rec


class TestBeat(unittest.TestCase):
    def test_beat_creates_and_refreshes_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "hb")
            with patch.object(streamlink_manager, "HEARTBEAT_FILE", path):
                streamlink_manager.beat()
                self.assertTrue(os.path.exists(path))
                os.utime(path, (0, 0))
                streamlink_manager.beat()
            self.assertGreater(os.stat(path).st_mtime, 0)

    def test_beat_ignores_unwritable_path(self):
        with patch.object(streamlink_manager, "HEARTBEAT_FILE", "/nonexistent-dir/hb"):
            streamlink_manager.beat()  # must not raise


class TestRecordingBeats(unittest.TestCase):
    @patch("streamlink_manager.streamlink.Streamlink")
    def test_long_recording_keeps_beating(self, mock_streamlink_cls):
        stream = MagicMock()
        stream.url = "https://example.com/stream.ts"
        mock_streamlink_cls.return_value.streams.return_value = {"best": stream}
        fd = MagicMock()
        fd.read.side_effect = [b"a", b"b", b"c", b""]
        stream.open.return_value = fd
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(streamlink_manager, "HEARTBEAT_INTERVAL_SECONDS", 0), \
                patch.object(streamlink_manager, "beat") as beat:
            StreamlinkManager(MagicMock(quality="best", oauth_token=None)).run_streamlink(
                "u", str(Path(tmp) / "f"))
        self.assertEqual(beat.call_count, 3)  # once per chunk with a zero interval


class TestLoopBeats(unittest.TestCase):
    def test_loop_beats_at_start_and_every_iteration(self):
        h = LoopHarness([Status.OFFLINE] * 3, [])
        with patch.object(rec, "beat") as beat:
            h.run()
        # one before auth validation, then one per iteration (3 offline + the one that stops)
        self.assertEqual(beat.call_count, 5)


if __name__ == "__main__":
    unittest.main()
