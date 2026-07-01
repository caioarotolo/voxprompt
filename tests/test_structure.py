import os
import subprocess
import unittest
from unittest import mock

from voxprompt.config import Config, load_config
from voxprompt import structure


def make_config(timeout: int = 300) -> Config:
    return Config(
        stt_backend="local",
        openai_stt_model="gpt-4o-transcribe",
        local_stt_url="http://localhost:8000/v1",
        local_stt_model="parakeet",
        template="spec",
        db_path=":memory:",
        claude_bin="claude",
        claude_model="claude-sonnet-5",
        claude_timeout_sec=timeout,
        openai_api_key=None,
        anthropic_api_key_present=False,
    )


class ClaudeTimeoutTest(unittest.TestCase):
    def test_timeout_loaded_from_env(self):
        with mock.patch.dict(os.environ, {"VOXPROMPT_CLAUDE_TIMEOUT_SEC": "42"}):
            self.assertEqual(load_config().claude_timeout_sec, 42)

    def test_invalid_timeout_uses_default(self):
        with mock.patch.dict(os.environ, {"VOXPROMPT_CLAUDE_TIMEOUT_SEC": "nope"}):
            self.assertEqual(load_config().claude_timeout_sec, 300)

    def test_default_claude_model_is_sonnet_5(self):
        with mock.patch("voxprompt.config._load_dotenv"), mock.patch.dict(
            os.environ, {}, clear=True
        ):
            self.assertEqual(load_config().claude_model, "claude-sonnet-5")

    def test_structure_passes_configured_timeout_to_claude(self):
        completed = subprocess.CompletedProcess(
            args=["claude"], returncode=0, stdout="ok", stderr=""
        )
        with mock.patch("subprocess.run", return_value=completed) as run:
            self.assertEqual(structure.structure("texto curto", "spec", make_config(7)), "ok")
        self.assertEqual(run.call_args.args[0][:3], ["claude", "--model", "claude-sonnet-5"])
        self.assertEqual(run.call_args.kwargs["timeout"], 7)


class TextChunkingTest(unittest.TestCase):
    def test_split_text_chunks_respects_limit(self):
        chunks = structure.split_text_chunks("linha 1\nlinha 2\nlinha 3", max_chars=10)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 10 for chunk in chunks))

    def test_long_generic_text_uses_partial_calls_and_final_consolidation(self):
        calls = []

        def fake_run(text, instruction, _config):
            calls.append((text, instruction))
            return f"saida-{len(calls)}"

        with mock.patch.object(structure, "STRUCTURE_CHUNK_CHARS", 10), mock.patch.object(
            structure, "_run_claude", side_effect=fake_run
        ):
            result = structure.structure("0123456789\nabcdefghij\n", "prompt", make_config())

        self.assertEqual(result, "saida-3")
        self.assertEqual(len(calls), 3)
        self.assertIn("--- BLOCO ---", calls[-1][0])

    def test_long_reuniao_preserves_clean_transcript_before_consolidation(self):
        outputs = iter(["limpo-1", "limpo-2", "### Decisões tomadas\n- uma decisão"])

        with mock.patch.object(structure, "STRUCTURE_CHUNK_CHARS", 10), mock.patch.object(
            structure, "_run_claude", side_effect=lambda *_args: next(outputs)
        ):
            result = structure.structure("0123456789\nabcdefghij\n", "reuniao", make_config())

        self.assertIn("## Transcrição limpa", result)
        self.assertIn("limpo-1\n\nlimpo-2", result)
        self.assertIn("## Consolidado da reunião", result)
        self.assertIn("### Decisões tomadas", result)


if __name__ == "__main__":
    unittest.main()
