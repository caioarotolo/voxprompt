import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime
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
LONG_AUDIO_SECONDS = 30 * 60
LONG_AUDIO_BYTES = 100 * 1024 * 1024
STT_PROGRESS_INTERVAL_SEC = 1.0


@dataclass
class BatchTranscriptSegment:
    index: int
    total: int
    path: str
    timestamp: datetime | None
    text: str


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
        self._stt_progress_stop: threading.Event | None = None
        self._stt_progress_thread: threading.Thread | None = None

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
        paths = dropfile.parse_dropped_paths(event.text)
        if not paths or not all(os.path.isfile(path) for path in paths):
            return
        event.stop()
        if len(paths) == 1:
            self._transcribe_file(paths[0])
        else:
            self._transcribe_files(paths)

    def _transcribe_file(self, path: str) -> None:
        if self.state in BUSY_STATES:
            self.notify("Aguarde o processamento atual.", severity="warning")
            return
        if not self._validate_audio_path(path):
            return
        self.notify(f"Transcrevendo {os.path.basename(path)}…")
        self._start_processing(path, 0.0, cleanup=False)

    def _transcribe_files(self, paths: list[str]) -> None:
        if self.state in BUSY_STATES:
            self.notify("Aguarde o processamento atual.", severity="warning")
            return
        ordered_paths = dropfile.sort_for_conversation(paths)
        for path in ordered_paths:
            if not self._validate_audio_path(path):
                return
        self.notify(f"Transcrevendo {len(ordered_paths)} áudios em ordem…")
        self._start_batch_processing(ordered_paths)

    def _validate_audio_path(self, path: str) -> bool:
        if not dropfile.is_supported(path):
            ext = Path(path).suffix.lower() or "sem extensão"
            self._on_error(f"Formato de áudio não suportado: {ext}.")
            return False
        if self.stt_backend == "openai":
            size = os.path.getsize(path)
            if size > OPENAI_MAX_BYTES:
                mb = size / (1024 * 1024)
                self._on_error(
                    f"Arquivo de {mb:.1f} MB excede o limite de 25 MB da API OpenAI. "
                    "Use o STT local (tecla s) ou reduza o arquivo."
                )
                return False
        return True

    # ---------- processamento (STT + estruturação) ----------

    def _start_processing(self, path: str, duration: float, cleanup: bool = True) -> None:
        self.state = "transcribing"
        self._process_worker(path, duration, cleanup)

    def _start_batch_processing(self, paths: list[str]) -> None:
        self.state = "transcribing"
        self._process_batch_worker(paths)

    @work(thread=True, group="process")
    def _process_worker(self, path: str, duration: float, cleanup: bool = True) -> None:
        try:
            self._process_file_sync(path, duration, checkpoint_raw=not cleanup)
        finally:
            self._stop_local_stt_progress()
            if cleanup:
                self._safe_remove(path)  # WAV gravado é temporário; arquivo solto não.

    @work(thread=True, group="process")
    def _process_batch_worker(self, paths: list[str]) -> None:
        try:
            self._process_batch_files_sync(paths)
        finally:
            self._stop_local_stt_progress()

    def _process_file_sync(
        self, path: str, duration: float, checkpoint_raw: bool = False
    ) -> None:
        backend = self.stt_backend
        template = self.template
        raw_entry_id: int | None = None

        if backend == "local":
            if not self._check_local_stt_available():
                return
            self._start_local_stt_progress()

        try:
            raw = transcribe.transcribe(path, backend, self.config)
        except Exception as exc:  # noqa: BLE001
            self.call_from_thread(self._on_error, f"STT: {exc}")
            return

        self._stop_local_stt_progress()
        self.call_from_thread(self._update_panel, "raw", raw)

        if template == "raw":
            self.call_from_thread(
                self._commit_entry, raw, raw, template, duration, backend
            )
            self.call_from_thread(self._set_state, "idle")
            return

        if checkpoint_raw or self._is_long_audio(path, duration):
            entry = self.call_from_thread(
                self._commit_entry,
                raw,
                "",
                template,
                duration,
                backend,
                "raw_saved",
            )
            raw_entry_id = entry.id if entry is not None else None

        self.call_from_thread(self._set_state, "structuring")
        try:
            structured = structure.structure(raw, template, self.config)
        except Exception as exc:  # noqa: BLE001
            if raw_entry_id is None:
                self.call_from_thread(
                    self._commit_entry,
                    raw,
                    "",
                    template,
                    duration,
                    backend,
                    "structure_failed",
                )
            else:
                self.call_from_thread(
                    self._update_entry_structured,
                    raw_entry_id,
                    "",
                    "structure_failed",
                )
            self.call_from_thread(self._on_error, f"Claude: {exc}")
            return

        if raw_entry_id is None:
            self.call_from_thread(
                self._commit_entry, raw, structured, template, duration, backend
            )
        else:
            self.call_from_thread(
                self._update_entry_structured, raw_entry_id, structured, "complete"
            )
        self.call_from_thread(self._set_state, "idle")

    def _process_batch_files_sync(self, paths: list[str]) -> None:
        paths = dropfile.sort_for_conversation(paths)
        backend = self.stt_backend
        template = self.template
        segments: list[BatchTranscriptSegment] = []
        raw_entry_id: int | None = None

        if backend == "local" and not self._check_local_stt_available():
            return

        total = len(paths)
        for index, path in enumerate(paths, start=1):
            self.call_from_thread(
                self._set_transcription_status,
                f"Transcrevendo áudio {index}/{total}: {os.path.basename(path)}",
            )
            if backend == "local":
                self._start_local_stt_progress()
            try:
                text = transcribe.transcribe(path, backend, self.config)
            except Exception as exc:  # noqa: BLE001
                partial_raw = self._format_batch_transcript(segments)
                if partial_raw:
                    self.call_from_thread(
                        self._commit_entry,
                        partial_raw,
                        "",
                        template,
                        0.0,
                        backend,
                        "stt_failed",
                    )
                self.call_from_thread(
                    self._on_error,
                    f"STT no áudio {index}/{total} ({os.path.basename(path)}): {exc}",
                )
                return
            finally:
                if backend == "local":
                    self._stop_local_stt_progress()

            segments.append(
                BatchTranscriptSegment(
                    index=index,
                    total=total,
                    path=path,
                    timestamp=dropfile.whatsapp_timestamp(path),
                    text=text,
                )
            )
            self.call_from_thread(
                self._update_panel, "raw", self._format_batch_transcript(segments)
            )

        raw = self._format_batch_transcript(segments)

        if template == "raw":
            self.call_from_thread(self._commit_entry, raw, raw, template, 0.0, backend)
            self.call_from_thread(self._set_state, "idle")
            return

        entry = self.call_from_thread(
            self._commit_entry,
            raw,
            "",
            template,
            0.0,
            backend,
            "raw_saved",
        )
        raw_entry_id = entry.id if entry is not None else None

        self.call_from_thread(self._set_state, "structuring")
        try:
            structured = structure.structure(raw, template, self.config)
        except Exception as exc:  # noqa: BLE001
            if raw_entry_id is None:
                self.call_from_thread(
                    self._commit_entry,
                    raw,
                    "",
                    template,
                    0.0,
                    backend,
                    "structure_failed",
                )
            else:
                self.call_from_thread(
                    self._update_entry_structured,
                    raw_entry_id,
                    "",
                    "structure_failed",
                )
            self.call_from_thread(self._on_error, f"Claude: {exc}")
            return

        if raw_entry_id is None:
            self.call_from_thread(
                self._commit_entry, raw, structured, template, 0.0, backend
            )
        else:
            self.call_from_thread(
                self._update_entry_structured, raw_entry_id, structured, "complete"
            )
        self.call_from_thread(self._set_state, "idle")

    def _format_batch_transcript(
        self, segments: list[BatchTranscriptSegment]
    ) -> str:
        if not segments:
            return ""

        total = segments[0].total
        lines = [
            "# Conversa transcrita em ordem",
            "",
            (
                "Observação: os arquivos do WhatsApp indicam horário, mas não trazem "
                "o remetente. Cada áudio abaixo é mantido como uma fala separada; "
                "ajuste o rótulo do falante para Eu/Cliente quando souber."
            ),
            "",
        ]
        for segment in segments:
            timestamp = (
                segment.timestamp.strftime("%Y-%m-%d %H:%M:%S")
                if segment.timestamp is not None
                else "horário não identificado"
            )
            basename = os.path.basename(segment.path)
            lines.extend(
                [
                    f"## Áudio {segment.index:02d}/{total} - {timestamp}",
                    f"Arquivo: {basename}",
                    "Falante: não identificado pelo arquivo",
                    "",
                    segment.text.strip() or "[sem texto transcrito]",
                    "",
                ]
            )
        return "\n".join(lines).strip()

    # ---------- STT local: bloqueio e progresso ----------

    def _check_local_stt_available(self) -> bool:
        status = transcribe.fetch_local_status(self.config)
        if status.error:
            self.call_from_thread(
                self._notify_warning,
                "Não foi possível consultar /status do STT local; continuando.",
            )
            return True
        if transcribe.local_status_is_processing(status.data):
            self.call_from_thread(
                self._on_error,
                "STT local já está processando outro áudio; tente novamente ao terminar.",
            )
            return False
        return True

    def _start_local_stt_progress(self) -> None:
        self._stop_local_stt_progress()
        stop_event = threading.Event()
        self._stt_progress_stop = stop_event
        self._stt_progress_thread = threading.Thread(
            target=self._poll_local_stt_progress,
            args=(stop_event,),
            name="voxprompt-local-stt-progress",
            daemon=True,
        )
        self._stt_progress_thread.start()

    def _stop_local_stt_progress(self) -> None:
        stop_event = self._stt_progress_stop
        if stop_event is not None:
            stop_event.set()
        thread = self._stt_progress_thread
        if (
            thread is not None
            and thread.is_alive()
            and thread is not threading.current_thread()
        ):
            thread.join(timeout=0.2)
        self._stt_progress_thread = None
        self._stt_progress_stop = None

    def _poll_local_stt_progress(self, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            status = transcribe.fetch_local_status(self.config)
            metrics = transcribe.fetch_local_metrics(self.config)
            message = transcribe.format_local_progress(
                status.data, metrics.data if metrics.error is None else None
            )
            if message and not stop_event.is_set():
                self.call_from_thread(self._set_transcription_status, message)
            stop_event.wait(STT_PROGRESS_INTERVAL_SEC)

    def _set_transcription_status(self, message: str) -> None:
        if self.is_mounted and self.state == "transcribing":
            self.query_one("#status", StatusBar).set_status(message, "busy")

    def _notify_warning(self, message: str) -> None:
        self.notify(message, severity="warning")

    def _is_long_audio(self, path: str, duration: float) -> bool:
        if duration >= LONG_AUDIO_SECONDS:
            return True
        try:
            return os.path.getsize(path) >= LONG_AUDIO_BYTES
        except OSError:
            return False

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
        status: str = "complete",
    ) -> HistoryEntry:
        entry = self.history.add(backend, template, raw, structured, duration, status)
        self._active_entry = entry
        if self.is_mounted:
            self._update_panel("raw", raw)
            self._update_panel("structured", structured)
            self._add_history_row(entry)
        return entry

    def _update_entry_structured(
        self, entry_id: int, structured: str, status: str = "complete"
    ) -> HistoryEntry | None:
        entry = self.history.update_structured(entry_id, structured, status)
        if entry is None:
            return None
        self._active_entry = entry
        if self.is_mounted:
            self._update_panel("raw", entry.raw_text)
            self._update_panel("structured", entry.structured_text)
            self._replace_history_row(entry)
        return entry

    def _add_history_row(self, entry: HistoryEntry) -> None:
        active = entry.structured_text or entry.raw_text
        preview = active.replace("\n", " ")[:PREVIEW_CHARS]
        if entry.status != "complete":
            preview = f"[{entry.status}] {preview}"[:PREVIEW_CHARS]
        self.query_one("#history", DataTable).add_row(
            str(entry.id),
            entry.timestamp.strftime("%H:%M:%S"),
            entry.stt_backend,
            entry.template,
            preview,
            str(len(active)),
            key=str(entry.id),
        )

    def _replace_history_row(self, entry: HistoryEntry) -> None:
        table = self.query_one("#history", DataTable)
        try:
            table.remove_row(str(entry.id))
        except Exception:  # noqa: BLE001 - a linha pode não existir na UI atual.
            pass
        self._add_history_row(entry)

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
        self._stop_local_stt_progress()
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
        self._stop_local_stt_progress()
        self.exit()

    def on_unmount(self) -> None:
        self._stop_event.set()
        self._stop_local_stt_progress()
        for path in list(self._temp_files):
            self._safe_remove(path)
        self.history.close()


def main() -> None:
    VoxPromptApp().run()


if __name__ == "__main__":
    main()
