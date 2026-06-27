import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from voxprompt.config import Config

LOCAL_STATUS_TIMEOUT_SEC = 2.0


class TranscriptionError(RuntimeError):
    """Falha de STT (rede, servidor local offline, credencial ausente, etc.)."""


@dataclass
class LocalEndpointResult:
    data: dict[str, Any] | None = None
    error: str | None = None


def local_server_root(local_stt_url: str) -> str:
    root = local_stt_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3]
    return root + "/"


def fetch_local_status(config: Config) -> LocalEndpointResult:
    return _fetch_local_json(config, "status")


def fetch_local_metrics(config: Config) -> LocalEndpointResult:
    return _fetch_local_json(config, "metrics")


def local_status_is_processing(status: dict[str, Any] | None) -> bool:
    if not status:
        return False

    for key in ("processing", "busy", "active", "is_processing", "transcribing"):
        value = status.get(key)
        if isinstance(value, bool) and value:
            return True

    state = str(status.get("state") or status.get("status") or "").strip().lower()
    if state in {"processing", "transcribing", "running", "busy", "active"}:
        return True
    if state in {"idle", "ready", "done", "complete", "completed", "finished"}:
        return False

    current, total = _chunk_numbers(status)
    if total is not None and current is not None:
        return 0 < current < total
    return False


def format_local_progress(
    status: dict[str, Any] | None, metrics: dict[str, Any] | None = None
) -> str | None:
    if not status:
        return None

    parts = ["Transcrevendo..."]
    current, total = _chunk_numbers(status)
    percent = _first_number(status, ("percent", "percentage", "progress_percent"))
    progress = _first_number(status, ("progress",))
    if percent is None and progress is not None:
        percent = progress * 100 if 0 <= progress <= 1 else progress
    if percent is None and current is not None and total:
        percent = current / total * 100

    if current is not None and total:
        parts.append(f"chunk {int(current)}/{int(total)}")
    if percent is not None:
        parts.append(f"{percent:.0f}%")

    resource_parts = _resource_parts(status, metrics)
    if resource_parts:
        parts.append(" ".join(resource_parts))

    return " | ".join(parts) if len(parts) > 1 else None


def transcribe(path: str, backend: str, config: Config) -> str:
    """Transcreve um WAV usando o cliente `openai` para ambos os backends.

    - openai: base padrão, modelo OPENAI_STT_MODEL, exige OPENAI_API_KEY.
    - local:  base_url=LOCAL_STT_URL, api_key dummy, modelo LOCAL_STT_MODEL
              (Parakeet OpenAI-compatible em localhost:8000/v1).
    """
    from openai import OpenAI  # lazy: só carrega quando há transcrição

    if backend == "openai":
        if not config.openai_api_key:
            raise TranscriptionError(
                "OPENAI_API_KEY ausente — exigida no backend 'openai'."
            )
        client = OpenAI(api_key=config.openai_api_key)
        model = config.openai_stt_model
    else:
        client = OpenAI(base_url=config.local_stt_url, api_key="local-no-auth")
        model = config.local_stt_model

    try:
        with open(path, "rb") as audio_file:
            result = client.audio.transcriptions.create(
                model=model,
                file=audio_file,
                response_format="text",
            )
    except Exception as exc:
        hint = ""
        if backend == "local":
            hint = f" (servidor local em {config.local_stt_url} acessível?)"
        raise TranscriptionError(f"{exc}{hint}") from exc

    # response_format="text" retorna str; mas defendemos contra objeto com .text.
    text = result if isinstance(result, str) else getattr(result, "text", str(result))
    return text.strip()


def _fetch_local_json(config: Config, path: str) -> LocalEndpointResult:
    url = urljoin(local_server_root(config.local_stt_url), path)
    try:
        request = Request(url, headers={"Accept": "application/json"})
        with urlopen(request, timeout=LOCAL_STATUS_TIMEOUT_SEC) as response:
            payload = response.read().decode("utf-8")
    except (OSError, TimeoutError) as exc:
        return LocalEndpointResult(error=str(exc))

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        return LocalEndpointResult(error=f"resposta inválida de {url}: {exc}")
    if not isinstance(data, dict):
        return LocalEndpointResult(error=f"resposta inesperada de {url}")
    return LocalEndpointResult(data=data)


def _chunk_numbers(status: dict[str, Any]) -> tuple[float | None, float | None]:
    current = _first_number(
        status,
        (
            "current_chunk",
            "chunk_current",
            "chunk_index",
            "processed_chunks",
            "chunks_done",
        ),
    )
    total = _first_number(
        status, ("total_chunks", "chunk_total", "chunks_total", "num_chunks")
    )
    if current is not None and total is not None and "chunk_index" in status:
        current += 1
    return current, total


def _first_number(data: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                pass
    return None


def _resource_parts(
    status: dict[str, Any], metrics: dict[str, Any] | None
) -> list[str]:
    source = metrics or status
    parts: list[str] = []
    cpu = _first_number(source, ("cpu_percent", "cpu", "cpu_usage"))
    ram = _first_number(source, ("ram_percent", "memory_percent", "mem_percent"))
    memory_mb = _first_number(source, ("memory_mb", "ram_mb", "rss_mb"))
    if cpu is not None:
        parts.append(f"CPU {cpu:.0f}%")
    if ram is not None:
        parts.append(f"RAM {ram:.0f}%")
    elif memory_mb is not None:
        parts.append(f"RAM {memory_mb:.0f} MB")
    return parts
