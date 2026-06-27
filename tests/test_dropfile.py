import unittest

from voxprompt.dropfile import is_supported, parse_dropped_path


class ParseDroppedPathTest(unittest.TestCase):
    def test_plain_path(self):
        self.assertEqual(parse_dropped_path("/home/me/reuniao.m4a"), "/home/me/reuniao.m4a")

    def test_strips_single_quotes(self):
        # GNOME Terminal/Konsole envolvem o caminho em aspas ao arrastar.
        self.assertEqual(
            parse_dropped_path("'/home/me/áudio do whatsapp.ogg'"),
            "/home/me/áudio do whatsapp.ogg",
        )

    def test_strips_double_quotes(self):
        self.assertEqual(parse_dropped_path('"/tmp/call.wav"'), "/tmp/call.wav")

    def test_unescapes_backslash_spaces_when_unquoted(self):
        # Drag-and-drop estilo bash escapa espaços com barra invertida.
        self.assertEqual(
            parse_dropped_path("/home/me/my\\ meeting.mp3"), "/home/me/my meeting.mp3"
        )

    def test_keeps_backslash_space_inside_quotes(self):
        # Caminho entre aspas é literal: não desfazemos escape.
        self.assertEqual(parse_dropped_path("'/tmp/a\\ b.wav'"), "/tmp/a\\ b.wav")

    def test_file_uri_is_decoded(self):
        self.assertEqual(
            parse_dropped_path("file:///home/me/audio%20call.opus"),
            "/home/me/audio call.opus",
        )

    def test_surrounding_whitespace_trimmed(self):
        self.assertEqual(parse_dropped_path("  /tmp/x.wav  "), "/tmp/x.wav")

    def test_multiline_paste_ignored(self):
        # Colagem de texto comum (várias linhas) não é um drop de arquivo.
        self.assertIsNone(parse_dropped_path("linha 1\nlinha 2"))

    def test_empty_ignored(self):
        self.assertIsNone(parse_dropped_path("   "))


class IsSupportedTest(unittest.TestCase):
    def test_supported_extensions(self):
        for path in ("a.mp3", "b.MP4", "c.m4a", "d.wav", "e.ogg", "f.webm", "g.opus"):
            self.assertTrue(is_supported(path), path)

    def test_unsupported_extensions(self):
        for path in ("notes.txt", "image.png", "archive.zip", "noext"):
            self.assertFalse(is_supported(path), path)


if __name__ == "__main__":
    unittest.main()
