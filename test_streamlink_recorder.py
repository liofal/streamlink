import unittest
from unittest.mock import patch
import streamlink_recorder


class TestStreamlinkRecorder(unittest.TestCase):
    @patch("streamlink_recorder.post_to_slack")
    @patch("streamlink_recorder.get_from_twitch")
    def test_check_user_online(self, mock_get_from_twitch, mock_post_to_slack):
        # Example test to check if a user is online
        mock_get_from_twitch.return_value = {"data": [{"type": "live"}]}
        status, title = streamlink_recorder.check_user("test_user")
        self.assertEqual(status, 0)  # 0 indicates online

    # Add more tests here...


if __name__ == "__main__":
    unittest.main()
