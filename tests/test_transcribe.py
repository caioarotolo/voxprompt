import unittest

from voxprompt import transcribe


class LocalStatusTest(unittest.TestCase):
    def test_local_server_root_removes_v1_suffix(self):
        self.assertEqual(
            transcribe.local_server_root("http://localhost:5092/v1"),
            "http://localhost:5092/",
        )

    def test_processing_detection_from_boolean_or_state(self):
        self.assertTrue(transcribe.local_status_is_processing({"processing": True}))
        self.assertTrue(transcribe.local_status_is_processing({"status": "transcribing"}))
        self.assertFalse(transcribe.local_status_is_processing({"status": "idle"}))

    def test_format_progress_uses_chunks_percent_and_resources(self):
        message = transcribe.format_local_progress(
            {"current_chunk": 2, "total_chunks": 8},
            {"cpu_percent": 50, "memory_percent": 61},
        )
        self.assertEqual(message, "Transcrevendo... | chunk 2/8 | 25% | CPU 50% RAM 61%")


if __name__ == "__main__":
    unittest.main()
