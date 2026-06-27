import shutil
import subprocess


class ClipboardError(RuntimeError):
    """Nenhuma ferramenta de clipboard disponível ou falha ao copiar."""


def copy(text: str) -> str:
    """Copia `text` via wl-copy (Wayland) ou, em fallback, xclip (X11).

    Retorna o nome da ferramenta usada.
    """
    if shutil.which("wl-copy"):
        cmd = ["wl-copy"]
        tool = "wl-copy"
    elif shutil.which("xclip"):
        cmd = ["xclip", "-selection", "clipboard"]
        tool = "xclip"
    else:
        raise ClipboardError(
            "Sem wl-copy nem xclip. Instale: sudo apt install -y wl-clipboard (ou xclip)."
        )

    try:
        subprocess.run(cmd, input=text.encode("utf-8"), check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or b"").decode("utf-8", "replace").strip()
        raise ClipboardError(f"{tool} falhou: {detail or exc}") from exc

    return tool
