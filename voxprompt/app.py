import os
import threading
import time
from pathlib import Path

from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import DataTable, Footer, Static, TextArea

from voxprompt import audio, clipboard, dropfile, structure, transcribe
from voxprompt.config import TEMPLATES, Config, load_config
from voxprompt.history import HistoryEntry, HistoryStore
from voxprompt.widgets import StatusBar, VoxHeader

TEMPLATE_ORDER = TEMPLATES  # ordem do ciclo da tecla `t`; fonte única em config.TEMPLATES
BUSY_STATES = ("recording", "transcribing", "structuring")
PREVIEW_CHARS = 60
HISTORY_LIMIT = 100  # transcrições carregadas do SQLite ao abrir
OPENAI_MAX_BYTES = 25 * 1024 * 1024  # limite de upload da API de transcrição da OpenAI


class VoxPromptApp(App):
    CSS_PATH = "voxprompt.tcss"
    TITLE = "VoxPrompt"

    BINDINGS = [
        Binding("r", "toggle_record", "Gravar"),
        Binding("s", "toggle_stt", "STT"),
        Binding("t", "cycle_template", "Template"),
        Binding("c", "copy_result", "Copiar"),
        Binding("l", "restructure_last", "Reestruturar"),
        Binding("h", "toggle_history", "Histórico"),
        Binding("delete", "delete_history_row", "Apagar"),
        Binding("q", "quit", "Sair"),
    ]

    state: reactive[str] = reactive("idle")

    def __init__(self) -> None:
        super().__init__()
        self.config: Config = load_config()
        self.stt_backend: str = self.config.stt_backend
        self.template: str = self.config.template
        self.history = HistoryStore(self.config.db_path)
        self._stop_event = threading.Event()
        self._record_start = 0.0
        self._timer = None
        self._active_entry: HistoryEntry | None = None
        self._error_msg = ""
        self._temp_files: set[str] = set()

    # ---------- layout ----------

    def compose(self) -> ComposeResult:
        yield VoxHeader(id="header")
        if self.config.anthropic_api_key_present:
            yield Static(
                "⚠ ANTHROPIC_API_KEY detectada — `claude -p` pode cobrar via API "
                "(billing) em vez da assinatura. Remova-a para usar o plano.",
                id="anthropic-alert",
            )
        with Horizontal(id="panels"):
            yield TextArea("", id="raw", read_only=True)
            yield TextArea("", id="structured", read_only=True)
        yield DataTable(id="history", cursor_type="row", zebra_stripes=True)
        yield StatusBar("Pronto.", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#raw", TextArea).border_title = "Transcrição crua"
        self.query_one("#structured", TextArea).border_title = "Pedido estruturado"

        table = self.query_one("#history", DataTable)
        table.add_columns("#", "Hora", "STT", "Template", "Preview", "Chars")
        for entry in self.history.recent(HISTORY_LIMIT):
            self._add_history_row(entry)

        self._refresh_header()
        self.query_one("#status", StatusBar).set_status("Pronto.", "idle")

        if self.config.anthropic_api_key_present:
            self.notify(
                "ANTHROPIC_API_KEY presente: risco de billing via API.",
                severity="error",
                timeout=8,
            )

    # ---------- reactivity ----------

    def watch_state(self, state: str) -> None:
        if not self.is_mounted:
            return
        self._refresh_header()
        bar = self.query_one("#status", StatusBar)
        if state == "idle":
            bar.set_status("Pronto.", "idle")
        elif state == "transcribing":
            bar.set_status("Transcrevendo…", "busy")
        elif state == "structuring":
            bar.set_status("Estruturando com Claude…", "busy")
        elif state == "error":
            bar.set_status(f"Erro: {self._error_msg}", "error")
        # "recording" é dirigido pelo cronômetro (_tick).

    def _refresh_header(self) -> None:
        # "Claude:" reflete só o subprocess de estruturação; erros gerais (ex.: clipboard)
        # aparecem na StatusBar vermelha, não aqui.
        claude_status = "estruturando…" if self.state == "structuring" else "idle"
        self.query_one("#header", VoxHeader).update_info(
            self.stt_backend, self.template, claude_status
        )

    def _set_state(self, value: str) -> None:
        self.state = value

    # ---------- gravação ----------

    def action_toggle_record(self) -> None:
        if self.state == "recording":
            self._stop_recording()
        elif self.state in ("idle", "error"):
            self._start_recording()
        else:
            self.notify("Processando… aguarde terminar.", severity="warning")

    def _start_recording(self) -> None:
        self._stop_event.clear()
        self._record_start = time.monotonic()
        self.state = "recording"
        self.query_one("#status", StatusBar).set_status("● Gravando 00:00", "recording")
        self._timer = self.set_interval(1, self._tick)
        self._record_worker()

    def _stop_recording(self) -> None:
        self._stop_event.set()
        self._stop_timer()
        # Worker finaliza o WAV e dispara o processamento.
        self.state = "transcribing"

    def _tick(self) -> None:
        elapsed = int(time.monotonic() - self._record_start)
        mm, ss = divmod(elapsed, 60)
        self.query_one("#status", StatusBar).set_status(
            f"● Gravando {mm:02d}:{ss:02d}", "recording"
        )

    def _stop_timer(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    @work(thread=True, group="record")
    def _record_worker(self) -> None:
        try:
            path, duration = audio.record(self._stop_event)
        except Exception as exc:  # noqa: BLE001 — normalizado para a UI
            self.call_from_thread(self._on_error, f"Mic: {exc}")
            return
        self.call_from_thread(self._track_temp, path)
        self.call_from_thread(self._start_processing, path, duration)

    # ---------- arquivo solto (drag-and-drop) ----------

    def on_paste(self, event: events.Paste) -> None:
        """Arrastar um arquivo para o terminal cola o caminho dele (bracketed paste).

        Tratamos só quando o texto colado aponta para um arquivo existente; colagens de
        texto comum seguem o fluxo normal (os painéis são read-only e ignoram).
        """
        path = dropfile.parse_dropped_path(event.text)
        if path is None or not os.path.isfile(path):
            return
        event.stop()
        self._transcribe_file(path)

    def _transcribe_file(self, path: str) -> None:
        if self.state in BUSY_STATES:
            self.notify("Aguarde o processamento atual.", severity="warning")
            return
        if not dropfile.is_supported(path):
            ext = Path(path).suffix.lower() or "sem extensão"
            self._on_error(f"Formato de áudio não suportado: {ext}.")
            return
        if self.stt_backend == "openai":
            size = os.path.getsize(path)
            if size > OPENAI_MAX_BYTES:
                mb = size / (1024 * 1024)
                self._on_error(
                    f"Arquivo de {mb:.1f} MB excede o limite de 25 MB da API OpenAI. "
                    "Use o STT local (tecla s) ou reduza o arquivo."
                )
                return
        self.notify(f"Transcrevendo {os.path.basename(path)}…")
        self._start_processing(path, 0.0, cleanup=False)

    # ---------- processamento (STT + estruturação) ----------

    def _start_processing(self, path: str, duration: float, cleanup: bool = True) -> None:
        self.state = "transcribing"
        self._process_worker(path, duration, cleanup)

    @work(thread=True, group="process")
    def _process_worker(self, path: str, duration: float, cleanup: bool = True) -> None:
        backend = self.stt_backend
        template = self.template
        try:
            try:
                raw = transcribe.transcribe(path, backend, self.config)
            except Exception as exc:  # noqa: BLE001
                self.call_from_thread(self._on_error, f"STT: {exc}")
                return

            self.call_from_thread(self._update_panel, "raw", raw)

            if template == "raw":
                structured = raw
            else:
                self.call_from_thread(self._set_state, "structuring")
                try:
                    structured = structure.structure(raw, template, self.config)
                except Exception as exc:  # noqa: BLE001
                    self.call_from_thread(
                        self._commit_entry, raw, "", template, duration, backend
                    )
                    self.call_from_thread(self._on_error, f"Claude: {exc}")
                    return

            self.call_from_thread(
                self._commit_entry, raw, structured, template, duration, backend
            )
            self.call_from_thread(self._set_state, "idle")
        finally:
            if cleanup:
                self._safe_remove(path)  # WAV gravado é temporário; arquivo solto não.

    # ---------- reestruturar última transcrição ----------

    def action_restructure_last(self) -> None:
        if self.state in BUSY_STATES:
            self.notify("Aguarde o processamento atual.", severity="warning")
            return
        last = self.history.latest()
        if last is None or not last.raw_text:
            self.notify("Nenhuma transcrição para reestruturar.", severity="warning")
            return
        self.state = "structuring"
        self._restructure_worker(last.raw_text, self.template, last.duration_sec)

    @work(thread=True, group="process")
    def _restructure_worker(self, raw: str, template: str, duration: float) -> None:
        backend = self.stt_backend
        if template == "raw":
            structured = raw
        else:
            try:
                structured = structure.structure(raw, template, self.config)
            except Exception as exc:  # noqa: BLE001
                self.call_from_thread(self._on_error, f"Claude: {exc}")
                return
        self.call_from_thread(
            self._commit_entry, raw, structured, template, duration, backend
        )
        self.call_from_thread(self._set_state, "idle")

    # ---------- commit de entrada + UI ----------

    def _commit_entry(
        self,
        raw: str,
        structured: str,
        template: str,
        duration: float,
        backend: str,
    ) -> None:
        entry = self.history.add(backend, template, raw, structured, duration)
        self._active_entry = entry
        self._update_panel("raw", raw)
        self._update_panel("structured", structured)
        self._add_history_row(entry)

    def _add_history_row(self, entry: HistoryEntry) -> None:
        active = entry.structured_text or entry.raw_text
        preview = active.replace("\n", " ")[:PREVIEW_CHARS]
        self.query_one("#history", DataTable).add_row(
            str(entry.id),
            entry.timestamp.strftime("%H:%M:%S"),
            entry.stt_backend,
            entry.template,
            preview,
            str(len(active)),
            key=str(entry.id),
        )

    def _update_panel(self, which: str, text: str) -> None:
        self.query_one(f"#{which}", TextArea).text = text

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        key = event.row_key.value
        if key is None:
            return
        entry = self.history.get(int(key))
        if entry is None:
            return
        self._active_entry = entry
        self._update_panel("raw", entry.raw_text)
        self._update_panel("structured", entry.structured_text)

    # ---------- STT / template / clipboard / histórico ----------

    def action_toggle_stt(self) -> None:
        if self.state in BUSY_STATES:
            self.notify("Aguarde terminar antes de trocar o STT.", severity="warning")
            return
        self.stt_backend = "openai" if self.stt_backend == "local" else "local"
        if self.stt_backend == "openai" and not self.config.openai_api_key:
            self.notify(
                "STT openai selecionado, mas OPENAI_API_KEY está ausente.",
                severity="warning",
            )
        self._refresh_header()
        self.notify(f"STT: {self.stt_backend}")

    def action_cycle_template(self) -> None:
        if self.state in BUSY_STATES:
            self.notify("Aguarde terminar antes de trocar o template.", severity="warning")
            return
        idx = TEMPLATE_ORDER.index(self.template)
        self.template = TEMPLATE_ORDER[(idx + 1) % len(TEMPLATE_ORDER)]
        self._refresh_header()
        self.notify(f"Template: {self.template}")

    def action_copy_result(self) -> None:
        if self.state in BUSY_STATES:
            self.notify("Aguarde o processamento.", severity="warning")
            return
        if self._active_entry is None:
            self.notify("Nada para copiar ainda.", severity="warning")
            return
        text = self._active_entry.structured_text or self._active_entry.raw_text
        if not text:
            self.notify("Resultado vazio.", severity="warning")
            return
        try:
            tool = clipboard.copy(text)
        except Exception as exc:  # noqa: BLE001
            self._on_error(f"Clipboard: {exc}")
            return
        self.query_one("#status", StatusBar).set_status(
            f"Copiado para o clipboard ({tool}) ✓", "ok"
        )
        self.notify("Copiado ✓")

    def action_toggle_history(self) -> None:
        table = self.query_one("#history", DataTable)
        table.display = not table.display

    def action_delete_history_row(self) -> None:
        table = self.query_one("#history", DataTable)
        if table.row_count == 0:
            self.notify("Histórico vazio.", severity="warning")
            return
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        entry_id = int(row_key.value)
        self.history.delete(entry_id)
        table.remove_row(row_key)
        if self._active_entry is not None and self._active_entry.id == entry_id:
            self._active_entry = None
            self._update_panel("raw", "")
            self._update_panel("structured", "")
        self.notify(f"Transcrição #{entry_id} apagada.")

    # ---------- erros / temporários / saída ----------

    def _on_error(self, message: str) -> None:
        self._stop_timer()
        self._stop_event.set()
        self._error_msg = message
        self.state = "error"
        self.bell()

    def _track_temp(self, path: str) -> None:
        self._temp_files.add(path)

    def _safe_remove(self, path: str) -> None:
        self._temp_files.discard(path)
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except OSError:
            pass

    def action_quit(self) -> None:
        self._stop_event.set()
        self._stop_timer()
        self.exit()

    def on_unmount(self) -> None:
        self._stop_event.set()
        for path in list(self._temp_files):
            self._safe_remove(path)
        self.history.close()


def main() -> None:
    VoxPromptApp().run()


if __name__ == "__main__":
    main()
