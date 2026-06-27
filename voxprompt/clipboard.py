import os
import shutil
import subprocess
import tempfile


class ClipboardError(RuntimeError):
    """Nenhuma ferramenta de clipboard disponível ou falha ao copiar."""


# (nome, comando). A ordem de preferência é decidida em runtime pela sessão gráfica.
_WL_COPY = ("wl-copy", ["wl-copy"])
_XCLIP = ("xclip", ["xclip", "-selection", "clipboard"])


def _ordered_tools() -> list[tuple[str, list[str]]]:
    """Prefere a ferramenta que casa com o servidor gráfico ativo, com fallback p/ a outra.

    wl-copy só funciona sob Wayland; xclip só sob X11. Escolher pelo binário instalado
    (e não pela sessão) quebra quando os dois estão presentes ou a sessão é a "errada".
    """
    if os.environ.get("WAYLAND_DISPLAY"):
        order = [_WL_COPY, _XCLIP]
    elif os.environ.get("DISPLAY"):
        order = [_XCLIP, _WL_COPY]
    else:
        order = [_WL_COPY, _XCLIP]
    return [(name, cmd) for name, cmd in order if shutil.which(name)]


def copy(text: str) -> str:
    """Copia `text` para o clipboard. Retorna o nome da ferramenta usada."""
    tools = _ordered_tools()
    if not tools:
        raise ClipboardError(
            "Sem wl-copy nem xclip. Em X11 instale: sudo apt install -y xclip "
            "(ou wl-clipboard sob Wayland)."
        )

    errors: list[str] = []
    for name, cmd in tools:
        # wl-copy/xclip forkam um processo de fundo pra servir a seleção, que herda
        # os fds passados. Capturar stdout/stderr via PIPE faria o run() bloquear lendo
        # o pipe que esse filho mantém aberto. Então: stdout -> DEVNULL e stderr -> arquivo
        # temporário (fd de arquivo não bloqueia o run); start_new_session destaca o filho.
        with tempfile.TemporaryFile() as errf:
            try:
                subprocess.run(
                    cmd,
                    input=text.encode("utf-8"),
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=errf,
                    start_new_session=True,
                    timeout=5,
                )
                return name
            except subprocess.CalledProcessError as exc:
                errf.seek(0)
                detail = errf.read().decode("utf-8", "replace").strip()
                errors.append(f"{name}: {detail or exc}")
            except subprocess.TimeoutExpired:
                errors.append(f"{name}: sem resposta do servidor gráfico (timeout)")
            except Exception as exc:  # binário sumiu, permissão, etc.
                errors.append(f"{name}: {exc}")

    raise ClipboardError("; ".join(errors))
