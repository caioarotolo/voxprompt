import os
from dataclasses import dataclass
from pathlib import Path

STT_BACKENDS = ("local", "openai")
TEMPLATES = ("spec", "commit", "prompt", "financeiro", "marketing", "formal", "whatsapp", "raw")


def _load_dotenv() -> None:
    """Carrega o .env na raiz do projeto. Vars já exportadas no shell têm precedência
    (override=False). python-dotenv é opcional: sem ele, seguimos só com o ambiente."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(env_path)


@dataclass
class Config:
    stt_backend: str
    openai_stt_model: str
    local_stt_url: str
    local_stt_model: str
    template: str
    claude_bin: str
    claude_model: str  # alias passado em `claude --model`; vazio = herda o default do CLI
    openai_api_key: str | None
    anthropic_api_key_present: bool


def load_config() -> Config:
    """Lê env vars com defaults. Valores inválidos caem no default (sem crashar o boot)."""
    _load_dotenv()
    backend = os.getenv("STT_BACKEND", "local").strip().lower()
    if backend not in STT_BACKENDS:
        backend = "local"  # suposição: valor desconhecido -> default seguro

    template = os.getenv("VOXPROMPT_TEMPLATE", "spec").strip().lower()
    if template not in TEMPLATES:
        template = "spec"

    return Config(
        stt_backend=backend,
        openai_stt_model=os.getenv("OPENAI_STT_MODEL", "gpt-4o-transcribe"),
        local_stt_url=os.getenv("LOCAL_STT_URL", "http://localhost:8000/v1"),
        local_stt_model=os.getenv("LOCAL_STT_MODEL", "parakeet-tdt-0.6b-v3"),
        template=template,
        claude_bin=os.getenv("CLAUDE_BIN", "claude"),
        claude_model=os.getenv("CLAUDE_MODEL", "sonnet").strip(),
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        anthropic_api_key_present=bool(os.getenv("ANTHROPIC_API_KEY")),
    )
