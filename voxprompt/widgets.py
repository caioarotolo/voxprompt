from textual.widgets import Static

_STATUS_KINDS = ("idle", "recording", "busy", "error", "ok")


class VoxHeader(Static):
    """Cabeçalho custom: título + backend STT + template + status do Claude."""

    def update_info(self, stt_backend: str, template: str, claude_status: str) -> None:
        self.update(
            f"[b]VoxPrompt[/b]   "
            f"STT: [cyan]{stt_backend}[/cyan]   "
            f"Template: [magenta]{template}[/magenta]   "
            f"Claude: {claude_status}"
        )


class StatusBar(Static):
    """Barra de status: idle / gravação / transcrevendo / estruturando / erro."""

    def set_status(self, text: str, kind: str = "idle") -> None:
        for k in _STATUS_KINDS:
            self.remove_class(f"s-{k}")
        if kind not in _STATUS_KINDS:
            kind = "idle"
        self.add_class(f"s-{kind}")
        self.update(text)
