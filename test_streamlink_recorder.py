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
import unittest
import requests
from unittest.mock import patch, MagicMock
import streamlink_recorder


class TestStreamlinkRecorder(unittest.TestCase):
    @patch("streamlink_recorder.requests.post")
    def test_post_to_slack_success(self, mock_post):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        streamlink_recorder.post_to_slack("Test message")

        mock_post.assert_called_once()
        mock_response.raise_for_status.assert_called_once()

    @patch("streamlink_recorder.requests.post")
    def test_post_to_slack_failure(self, mock_post):
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError
        mock_post.return_value = mock_response

        with self.assertRaises(ValueError):
            streamlink_recorder.post_to_slack("Test message")

        mock_post.assert_called_once()
        mock_response.raise_for_status.assert_called_once()


# Add more tests here...

if __name__ == "__main__":
    unittest.main()
