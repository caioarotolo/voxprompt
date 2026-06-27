from pathlib import Path
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


def parse_dropped_path(pasted: str) -> str | None:
    """Extrai um caminho de arquivo do texto que o terminal entrega ao soltar um arquivo.

    Num terminal não existe "drop zone": arrastar um arquivo para a janela faz o emulador
    colar o caminho (bracketed paste), que o Textual entrega como evento `Paste`. Cada
    terminal formata diferente — caminho cru, entre aspas, com espaços escapados (`\\ `)
    ou como URI `file://`. Retorna o caminho normalizado, ou None quando o texto não parece
    um único caminho (colagem de texto comum ou múltiplos arquivos), para não sequestrar
    colagens normais.
    """
    text = pasted.strip()
    if not text or "\n" in text:
        return None

    quoted = len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"')
    if quoted:
        text = text[1:-1]

    if text.startswith("file://"):
        text = unquote(urlparse(text).path)
    elif not quoted:
        # Espaços escapados com barra invertida (drag-and-drop estilo bash).
        text = text.replace("\\ ", " ")

    text = text.strip()
    return text or None


def is_supported(path: str) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_EXTENSIONS
