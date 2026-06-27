import os
import tempfile
import threading
import time

import numpy as np

SAMPLE_RATE = 16000
CHANNELS = 1


class AudioError(RuntimeError):
    """Falha de captura de áudio (mic ausente, PortAudio indisponível, etc.)."""


def record(stop_event: threading.Event, samplerate: int = SAMPLE_RATE) -> tuple[str, float]:
    """Grava do microfone até `stop_event` ser setado. Retorna (caminho_wav, duracao_seg).

    `sounddevice`/`soundfile` são importados aqui (lazy) para que a TUI abra mesmo
    sem `libportaudio2` instalado — o erro só aparece ao tentar gravar.
    """
    try:
        import sounddevice as sd  # noqa: PLC0415
        import soundfile as sf  # noqa: PLC0415
    except (ImportError, OSError) as exc:
        raise AudioError(
            f"Backend de áudio indisponível ({exc}). Instale libportaudio2/libsndfile."
        ) from exc

    frames: list[np.ndarray] = []

    def callback(indata, _frames, _time, status):  # noqa: ANN001
        if status:
            # underflow/overflow não devem derrubar a gravação; ignoramos o flag.
            pass
        frames.append(indata.copy())

    try:
        with sd.InputStream(
            samplerate=samplerate,
            channels=CHANNELS,
            dtype="int16",
            callback=callback,
        ):
            while not stop_event.is_set():
                time.sleep(0.05)
    except Exception as exc:  # PortAudio levanta tipos variados; normalizamos.
        raise AudioError(str(exc)) from exc

    if not frames:
        raise AudioError("Nenhum áudio capturado (verifique o microfone).")

    data = np.concatenate(frames, axis=0)
    duration = len(data) / samplerate

    fd, path = tempfile.mkstemp(prefix="voxprompt_", suffix=".wav")
    os.close(fd)
    try:
        sf.write(path, data, samplerate, subtype="PCM_16")
    except Exception as exc:
        try:
            os.remove(path)
        except OSError:
            pass
        raise AudioError(f"Falha ao gravar WAV: {exc}") from exc

    return path, duration
