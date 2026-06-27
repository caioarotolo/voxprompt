from voxprompt.config import Config


class TranscriptionError(RuntimeError):
    """Falha de STT (rede, servidor local offline, credencial ausente, etc.)."""


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
