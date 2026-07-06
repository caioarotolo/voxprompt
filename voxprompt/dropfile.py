from pathlib import Path
import re
import shlex
from datetime import datetime
from urllib.parse import unquote, urlparse

# Extensões de áudio aceitas no drag-and-drop: o mínimo pedido
# (mp3/mp4/m4a/wav/ogg/webm/opus) mais os demais formatos que a API de
# transcrição da OpenAI aceita. O backend local decide o que consegue decodificar.
SUPPORTED_EXTENSIONS = frozenset(
    {
        ".mp3",
        ".mp4",
        ".m4a",
        ".wav",
        ".ogg",
        ".oga",
        ".opus",
        ".webm",
        ".flac",
        ".mpeg",
        ".mpga",
        ".aac",
    }
)

WHATSAPP_PTT_RE = re.compile(
    r"WhatsApp Ptt (?P<date>\d{4}-\d{2}-\d{2}) at "
    r"(?P<hour>\d{2})\.(?P<minute>\d{2})\.(?P<second>\d{2})",
    re.IGNORECASE,
)


def parse_dropped_path(pasted: str) -> str | None:
    """Extrai um caminho de arquivo do texto que o terminal entrega ao soltar um arquivo.

    Num terminal não existe "drop zone": arrastar um arquivo para a janela faz o emulador
    colar o caminho (bracketed paste), que o Textual entrega como evento `Paste`. Cada
    terminal formata diferente — caminho cru, entre aspas, com espaços escapados (`\\ `)
    ou como URI `file://`. Retorna o caminho normalizado, ou None quando o texto não parece
    um único caminho (colagem de texto comum ou múltiplos arquivos), para não sequestrar
    colagens normais.
    """
    paths = parse_dropped_paths(pasted)
    return paths[0] if len(paths) == 1 else None


def parse_dropped_paths(pasted: str) -> list[str]:
    """Extrai um ou mais caminhos colados pelo terminal.

    Aceita o caso antigo de caminho único e também listas como:
    `'/tmp/a.ogg' '/tmp/b.ogg'` ou `/tmp/a\\ b.ogg /tmp/c.ogg`.
    Quando o texto parece ser uma colagem comum, retorna lista vazia.
    """
    text = pasted.strip()
    if not text:
        return []

    try:
        paths = shlex.split(text)
    except ValueError:
        return []
    if (
        len(paths) != 1
        and _looks_like_single_path(text)
        and not all(is_supported(path) for path in paths)
    ):
        paths = [text.replace("\\ ", " ")]

    normalized_paths = []
    for path in paths:
        normalized = _normalize_path(path)
        if normalized:
            normalized_paths.append(normalized)
    return normalized_paths


def is_supported(path: str) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_EXTENSIONS


def whatsapp_timestamp(path: str) -> datetime | None:
    match = WHATSAPP_PTT_RE.search(Path(path).name)
    if match is None:
        return None
    parts = match.groupdict()
    value = (
        f"{parts['date']} "
        f"{parts['hour']}:{parts['minute']}:{parts['second']}"
    )
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def sort_for_conversation(paths: list[str]) -> list[str]:
    """Ordena áudios de conversa.

    Se todos tiverem timestamp do padrão `WhatsApp Ptt ...`, usa ordem cronológica.
    Caso contrário, preserva a ordem colada pelo usuário.
    """
    timestamps = [whatsapp_timestamp(path) for path in paths]
    if paths and all(timestamp is not None for timestamp in timestamps):
        return [
            path
            for timestamp, path in sorted(
                zip(timestamps, paths, strict=True), key=lambda item: item[0]
            )
        ]
    return list(paths)


def _normalize_path(path: str) -> str:
    value = path.strip()
    if value.startswith("file://"):
        value = unquote(urlparse(value).path)
    return value.strip()


def _looks_like_single_path(text: str) -> bool:
    normalized = text.replace("\\ ", " ").strip()
    return normalized.startswith(("/", "~", ".")) and is_supported(normalized)
