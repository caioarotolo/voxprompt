import os
import tempfile
import unittest
from unittest import mock

try:
    from voxprompt.app import LONG_AUDIO_SECONDS, VoxPromptApp
except ModuleNotFoundError as exc:
    if exc.name != "textual":
        raise
    raise unittest.SkipTest("textual is not installed") from exc


class RawPersistenceTest(unittest.TestCase):
    def test_long_audio_raw_is_persisted_when_structure_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "history.db")
            audio_path = os.path.join(tmpdir, "audio.wav")
            with open(audio_path, "wb") as audio_file:
                audio_file.write(b"audio")

            with mock.patch.dict(
                os.environ,
                {
                    "VOXPROMPT_DB": db_path,
                    "STT_BACKEND": "openai",
                    "OPENAI_API_KEY": "test-key",
                    "VOXPROMPT_TEMPLATE": "spec",
                },
            ):
                app = VoxPromptApp()

            app.call_from_thread = lambda callback, *args: callback(*args)
            app._update_panel = lambda *_args: None
            app._add_history_row = lambda *_args: None
            app._replace_history_row = lambda *_args: None
            app._set_state = lambda value: setattr(app, "_test_state", value)
            app._on_error = lambda message: setattr(app, "_error_msg", message)

            with mock.patch(
                "voxprompt.app.transcribe.transcribe", return_value="transcrição bruta"
            ), mock.patch(
                "voxprompt.app.structure.structure", side_effect=RuntimeError("timeout")
            ):
                app._process_file_sync(audio_path, float(LONG_AUDIO_SECONDS))

            entry = app.history.latest()
            self.assertIsNotNone(entry)
            self.assertEqual(entry.raw_text, "transcrição bruta")
            self.assertEqual(entry.structured_text, "")
            self.assertEqual(entry.status, "structure_failed")
            app.history.close()

    def test_batch_audio_is_saved_as_one_ordered_conversation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "history.db")
            older = os.path.join(
                tmpdir, "WhatsApp Ptt 2026-07-06 at 16.47.08.ogg"
            )
            newer = os.path.join(
                tmpdir, "WhatsApp Ptt 2026-07-06 at 17.44.40.ogg"
            )
            for audio_path in (older, newer):
                with open(audio_path, "wb") as audio_file:
                    audio_file.write(b"audio")

            with mock.patch.dict(
                os.environ,
                {
                    "VOXPROMPT_DB": db_path,
                    "STT_BACKEND": "openai",
                    "OPENAI_API_KEY": "test-key",
                    "VOXPROMPT_TEMPLATE": "conversa",
                },
            ):
                app = VoxPromptApp()

            app.call_from_thread = lambda callback, *args: callback(*args)
            app._update_panel = lambda *_args: None
            app._add_history_row = lambda *_args: None
            app._replace_history_row = lambda *_args: None
            app._set_state = lambda value: setattr(app, "_test_state", value)
            app._set_transcription_status = lambda *_args: None
            app._on_error = lambda message: setattr(app, "_error_msg", message)

            def fake_transcribe(path, _backend, _config):
                if path == older:
                    return "texto do áudio mais antigo"
                if path == newer:
                    return "texto do áudio mais novo"
                raise AssertionError(path)

            with mock.patch(
                "voxprompt.app.transcribe.transcribe", side_effect=fake_transcribe
            ), mock.patch(
                "voxprompt.app.structure.structure", return_value="conversa limpa"
            ):
                app._process_batch_files_sync([newer, older])

            entry = app.history.latest()
            self.assertIsNotNone(entry)
            self.assertEqual(entry.template, "conversa")
            self.assertEqual(entry.structured_text, "conversa limpa")
            self.assertIn("## Áudio 01/2 - 2026-07-06 16:47:08", entry.raw_text)
            self.assertIn("## Áudio 02/2 - 2026-07-06 17:44:40", entry.raw_text)
            self.assertLess(
                entry.raw_text.index("texto do áudio mais antigo"),
                entry.raw_text.index("texto do áudio mais novo"),
            )
            app.history.close()

    def test_dropped_file_checkpoints_raw_before_structure_even_when_size_is_small(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "history.db")
            audio_path = os.path.join(tmpdir, "meeting.m4a")
            with open(audio_path, "wb") as audio_file:
                audio_file.write(b"small-audio")

            with mock.patch.dict(
                os.environ,
                {
                    "VOXPROMPT_DB": db_path,
                    "STT_BACKEND": "openai",
                    "OPENAI_API_KEY": "test-key",
                    "VOXPROMPT_TEMPLATE": "spec",
                },
            ):
                app = VoxPromptApp()

            app.call_from_thread = lambda callback, *args: callback(*args)
            app._update_panel = lambda *_args: None
            app._add_history_row = lambda *_args: None
            app._replace_history_row = lambda *_args: None
            app._set_state = lambda value: setattr(app, "_test_state", value)
            app._on_error = lambda message: setattr(app, "_error_msg", message)

            def fail_after_checkpoint(_raw, _template, _config):
                entry = app.history.latest()
                self.assertIsNotNone(entry)
                self.assertEqual(entry.raw_text, "transcrição de reunião")
                self.assertEqual(entry.structured_text, "")
                self.assertEqual(entry.status, "raw_saved")
                raise RuntimeError("timeout")

            with mock.patch(
                "voxprompt.app.transcribe.transcribe",
                return_value="transcrição de reunião",
            ), mock.patch(
                "voxprompt.app.structure.structure", side_effect=fail_after_checkpoint
            ), mock.patch.object(app, "_is_long_audio", return_value=False):
                app._process_file_sync(audio_path, 0.0, checkpoint_raw=True)

            entry = app.history.latest()
            self.assertIsNotNone(entry)
            self.assertEqual(entry.raw_text, "transcrição de reunião")
            self.assertEqual(entry.structured_text, "")
            self.assertEqual(entry.status, "structure_failed")
            app.history.close()


if __name__ == "__main__":
    unittest.main()
