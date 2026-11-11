import datetime
import importlib.util
import unicodedata
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("streamlink-recorder.py")
spec = importlib.util.spec_from_file_location("streamlink_recorder", MODULE_PATH)
streamlink_recorder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(streamlink_recorder)

NOW = datetime.datetime(2026, 11, 4, 12, 0, 0)


def build(user, title):
    return streamlink_recorder.build_recording_basename(user, title, NOW)


def fits(name):
    b = len(name.encode("utf-8"))
    return b + len(".part") <= 255 and b + len(".mp4") <= 255 and b + len(".ts") <= 255


class TestBuildRecordingBasename(unittest.TestCase):
    def test_normal_format(self):
        self.assertEqual(build("user", "Hello World"), "user - 2026-11-04 12-00-00 - Hello World")

    def test_long_cjk_title_fits(self):
        name = build("user", "漢" * 200)
        self.assertTrue(fits(name))
        self.assertNotIn("�", name)
        name.encode("utf-8")

    def test_long_ascii_title_fits(self):
        self.assertTrue(fits(build("user", "x" * 1000)))

    def test_multibyte_truncation_on_char_boundary(self):
        # 2-byte "e acute" + 3-byte CJK are kept by sanitization; vary the user
        # length so the title budget lands on and between character boundaries.
        title = "\u00e9\u6f22" * 100
        mid_char = 0
        for n in range(1, 26):
            name = build("u" * n, title)
            self.assertTrue(fits(name))
            self.assertNotIn("\ufffd", name)
            name.encode("utf-8")
            kept = name.split(" - ", 2)[2]
            self.assertTrue(kept)
            self.assertTrue(title.startswith(kept))
            prefix_bytes = len(f"{'u' * n} - 2026-11-04 12-00-00 - ".encode())
            if (239 - prefix_bytes) % 5 not in (0, 2):
                mid_char += 1
        self.assertGreater(mid_char, 0)

    def test_control_chars_and_newlines(self):
        name = build("user", "a\nb\r\tc\x00d\x1be")
        self.assertEqual(name, "user - 2026-11-04 12-00-00 - a b cde")
        self.assertFalse(any(unicodedata.category(c).startswith("C") for c in name))

    def test_empty_title(self):
        for t in ("", "   ", "\n", "...", None, "<>"):
            name = build("user", t)
            if t == "<>":
                self.assertEqual(name, "user - 2026-11-04 12-00-00 - __")
            else:
                self.assertEqual(name, "user - 2026-11-04 12-00-00")

    def test_trailing_dots_spaces_after_truncation(self):
        title = "a" * 150 + "... " + "b" * 200
        name = build("user", title)
        self.assertTrue(fits(name))
        self.assertFalse(name.endswith((".", " ")))

    def test_path_separators_in_user(self):
        for u in ("../evil/x", "a\\b", "..", "/", ""):
            name = build(u, "t")
            self.assertNotIn("/", name)
            self.assertNotIn("\\", name)
            self.assertFalse(name.startswith((".", "_")))
        self.assertEqual(build("../evil/x", "t"), "evil_x - 2026-11-04 12-00-00 - t")
        self.assertEqual(build("..", "t"), "unknown - 2026-11-04 12-00-00 - t")

    def test_user_twitch_login_charset(self):
        self.assertEqual(build("Some User-Name", "t"), "Some_User_Name - 2026-11-04 12-00-00 - t")
        self.assertEqual(build("caf\u00e9\u6f22", "t"), "caf - 2026-11-04 12-00-00 - t")
        self.assertEqual(build("\u6f22\u5b57", "t"), "unknown - 2026-11-04 12-00-00 - t")
        self.assertEqual(build("a__b", "t"), "a_b - 2026-11-04 12-00-00 - t")
        self.assertEqual(build("_ok_", "t"), "ok - 2026-11-04 12-00-00 - t")

    def test_very_long_user(self):
        name = build("u" * 300, "title")
        self.assertTrue(fits(name))
        self.assertTrue(name.startswith("u" * 25 + " - 2026"))

    def test_reserved_chars_replaced_then_legacy_removal(self):
        # reserved chars -> "_" first, then [^\w\s._-] removed (so "!" vanishes, "_" stays)
        self.assertEqual(build("user", "a/b:c"), "user - 2026-11-04 12-00-00 - a_b_c")
        self.assertEqual(build("user", 'a|b?c*d"e<f>g\\h!'), "user - 2026-11-04 12-00-00 - a_b_c_d_e_f_g_h")


if __name__ == "__main__":
    unittest.main()
