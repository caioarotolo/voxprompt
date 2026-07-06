import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STT_BACKENDS = ("local", "openai")
TEMPLATES = (
    "spec",
    "commit",
    "prompt",
    "financeiro",
    "marketing",
    "formal",
    "whatsapp",
    "conversa",
    "reuniao",
    "raw",
)


def _load_dotenv() -> None:
    """Carrega o .env na raiz do projeto. Vars já exportadas no shell têm precedência
    (override=False). python-dotenv é opcional: sem ele, seguimos só com o ambiente."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(PROJECT_ROOT / ".env")


@dataclass
class Config:
    stt_backend: str
    openai_stt_model: str
    local_stt_url: str
    local_stt_model: str
    template: str
    db_path: str
    claude_bin: str
    claude_model: str  # modelo passado em `claude --model`; vazio = herda o default do CLI
    claude_timeout_sec: int
    openai_api_key: str | None
    anthropic_api_key_present: bool


def _env_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, "").strip())
    except ValueError:
        return default
    return value if value > 0 else default


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
        db_path=os.getenv("VOXPROMPT_DB", "").strip() or str(PROJECT_ROOT / "voxprompt.db"),
        claude_bin=os.getenv("CLAUDE_BIN", "claude"),
        claude_model=os.getenv("CLAUDE_MODEL", "claude-sonnet-5").strip(),
        claude_timeout_sec=_env_int("VOXPROMPT_CLAUDE_TIMEOUT_SEC", 300),
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        anthropic_api_key_present=bool(os.getenv("ANTHROPIC_API_KEY")),
    )
