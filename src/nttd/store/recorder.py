"""Session recorder: ingests game data and writes to Parquet via background flush.

All record_* methods append to in-memory buffers (non-blocking).
A background task flushes buffers to per-type Parquet fragment files.
On session stop, fragments are merged into final consolidated files.

Storage layout per session (under logs/sessions/<session_id>/):
  snapshots.parquet     -- full game state time-series (via ParquetWriter)
  actions.parquet       -- all actions with embedded parameters as JSON
  events.parquet        -- lifecycle + game events

During a session, fragments are written to _fragments/<type>_NNN.parquet
to avoid re-reading the full file on every flush. On stop, all fragments
are merged into the final file.
"""

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from nttd.schemas.action_envelope import ActionEnvelope
from nttd.schemas.action_result import ActionResult, ActionStatus
from nttd.schemas.snapshot import StateSnapshot
from nttd.store import session_paths
from nttd.store.parquet_writer import ParquetWriter

logger = logging.getLogger(__name__)

_FLUSH_INTERVAL_SECONDS: float = 1.0
_MAX_BUFFER_SIZE: int = 5000

# -- Parquet schemas for each record type --

_ACTIONS_SCHEMA = pa.schema([
    ("action_id", pa.string()),
    ("agent_id", pa.string()),
    ("company_id", pa.int16()),
    ("game_date", pa.int32()),
    ("action_type", pa.string()),
    ("status", pa.string()),
    ("error", pa.string()),
    # The stable name and number behind the message. The message now carries a worked out
    # reason that names tiles and rail types, which is what an agent needs and what makes
    # it useless as a grouping key: every refusal reads as unique. Reports group on the
    # name and show the message.
    ("error_name", pa.string()),
    ("error_code", pa.int32()),
    ("parameters_json", pa.string()),
    ("submitted_at", pa.timestamp("us")),
    # How the action reached the game. "api" is a submission through nttd; "client"
    # is a command issued in the OpenTTD window by a person. Without this column the
    # log records only API traffic, and a run played by hand looks like a run that
    # did nothing.
    ("source", pa.string()),
    # Which connected OpenTTD client issued it, for client commands only.
    ("client_id", pa.int32()),
])

SOURCE_API = "api"
SOURCE_CLIENT = "client"

_EVENTS_SCHEMA = pa.schema([
    ("game_date", pa.int32()),
    ("event_type", pa.string()),
    ("company_id", pa.int16()),
    ("detail", pa.string()),
    ("timestamp", pa.timestamp("us")),
])

_SCHEMAS: dict[str, pa.Schema] = {
    "actions": _ACTIONS_SCHEMA,
    "events": _EVENTS_SCHEMA,
}


class SessionRecorder:
    """Buffers game data and flushes to Parquet fragment files.

    Each flush writes a small numbered fragment (O(new_rows) per flush).
    On stop(), fragments are merged into consolidated .parquet files.
    """

    def __init__(
        self, session_id: str, flush_interval: float = _FLUSH_INTERVAL_SECONDS,
        data_dir: str | None = None,
    ) -> None:
        self.session_id: str = session_id
        self._flush_interval: float = flush_interval
        root = Path(data_dir) if data_dir else session_paths.sessions_dir()
        self._session_dir: Path = root.resolve() / session_id
        self._fragments_dir: Path = self._session_dir / "_fragments"

        # Per-type buffers
        self._action_buffer: list[dict[str, Any]] = []
        # Running per-company action tally, keyed by company_id. Survives the
        # buffer being flushed, so it covers the whole session rather than
        # whatever happens to be unflushed at the end.
        self._action_counts: dict[int, dict[str, int]] = {}
        self._event_buffer: list[dict[str, Any]] = []

        self._buffer_lock: asyncio.Lock = asyncio.Lock()
        # Per-type fragment counters (monotonic, used for unique filenames)
        self._fragment_seq: dict[str, int] = {"actions": 0, "events": 0}

        self._flush_task: asyncio.Task[None] | None = None
        self._running: bool = False
        self._snapshot_count: int = 0
        self._total_rows_flushed: int = 0
        self._flush_count: int = 0
        self._parquet: ParquetWriter = ParquetWriter(session_id, data_dir)

    @property
    def session_dir(self) -> Path:
        return self._session_dir

    async def start(self) -> None:
        self._session_dir.mkdir(parents=True, exist_ok=True)
        self._fragments_dir.mkdir(parents=True, exist_ok=True)
        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop())
        logger.info("SessionRecorder started for session %s (dir=%s)", self.session_id, self._session_dir)

    async def stop(self) -> None:
        self._running = False
        if self._flush_task is not None:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        # Final flush of any remaining buffered data
        await self._flush_once()
        self._parquet.finalize()

        # Merge all fragments into consolidated files
        await asyncio.to_thread(self._merge_all_fragments)

        logger.info(
            "SessionRecorder stopped: %d snapshots (%d parquet), %d rows flushed in %d batches",
            self._snapshot_count,
            self._parquet.total_written,
            self._total_rows_flushed,
            self._flush_count,
        )

    async def _flush_loop(self) -> None:
        while self._running:
            await asyncio.sleep(self._flush_interval)
            try:
                await self._flush_once()
            except Exception:
                logger.exception("Flush failed")

    async def _flush_once(self) -> None:
        async with self._buffer_lock:
            actions = self._action_buffer
            events = self._event_buffer
            self._action_buffer = []
            self._event_buffer = []

        t0 = time.monotonic()

        # Write each buffer type as a new fragment file in parallel threads.
        # Each fragment is a standalone file -- no read-modify-write needed.
        tasks: list[asyncio.Task[int]] = []
        if actions:
            tasks.append(asyncio.ensure_future(asyncio.to_thread(
                self._write_fragment, "actions", actions,
            )))
        if events:
            tasks.append(asyncio.ensure_future(asyncio.to_thread(
                self._write_fragment, "events", events,
            )))

        # Also flush snapshot ParquetWriter buffer if it has data
        if self._parquet._buffer:
            tasks.append(asyncio.ensure_future(asyncio.to_thread(self._parquet.flush)))

        if not tasks:
            return

        results = await asyncio.gather(*tasks, return_exceptions=True)
        total_rows = 0
        for r in results:
            if isinstance(r, Exception):
                logger.error("Parquet fragment write failed: %s", r)
            elif isinstance(r, int):
                total_rows += r

        elapsed_ms = (time.monotonic() - t0) * 1000
        self._total_rows_flushed += total_rows
        self._flush_count += 1
        if total_rows > 0:
            logger.debug("Flushed %d rows to fragments in %.1fms", total_rows, elapsed_ms)

    def _write_fragment(self, file_key: str, rows: list[dict[str, Any]]) -> int:
        """Write rows as a new numbered fragment file. O(n_new_rows) per call."""
        schema = _SCHEMAS[file_key]
        seq = self._fragment_seq[file_key]
        self._fragment_seq[file_key] = seq + 1

        fragment_path = self._fragments_dir / f"{file_key}_{seq:04d}.parquet"
        table = pa.Table.from_pylist(rows, schema=schema)
        pq.write_table(table, fragment_path, compression="zstd")
        return len(rows)

    def _merge_all_fragments(self) -> None:
        """Merge all fragment files into consolidated Parquet files.

        Called once on session stop. Reads all fragments for each type,
        concatenates them, writes the final file, and removes the fragments.
        """
        for file_key, schema in _SCHEMAS.items():
            self._merge_fragments(file_key, schema)

        # Remove fragments directory if empty
        if self._fragments_dir.exists():
            remaining = list(self._fragments_dir.iterdir())
            if not remaining:
                self._fragments_dir.rmdir()

    def _merge_fragments(self, file_key: str, schema: pa.Schema) -> None:
        """Merge all fragment files for a given type into one consolidated file."""
        pattern = f"{file_key}_*.parquet"
        fragments = sorted(self._fragments_dir.glob(pattern))
        if not fragments:
            return

        tables: list[pa.Table] = []
        for frag_path in fragments:
            try:
                tables.append(pq.read_table(frag_path, schema=schema))
            except Exception:
                logger.warning("Failed to read fragment %s, skipping", frag_path.name)

        if not tables:
            return

        merged = pa.concat_tables(tables)
        output_path = self._session_dir / f"{file_key}.parquet"
        pq.write_table(merged, output_path, compression="zstd")

        # Clean up fragment files
        for frag_path in fragments:
            frag_path.unlink(missing_ok=True)

        logger.info(
            "Merged %d %s fragments (%d rows) into %s",
            len(fragments), file_key, merged.num_rows, output_path.name,
        )

    # ------------------------------------------------------------------
    # Snapshot recording
    # ------------------------------------------------------------------

    def record_snapshot(self, snapshot: StateSnapshot) -> None:
        """Record snapshot to Parquet."""
        self._snapshot_count += 1
        self._parquet.append(snapshot)

        buf_size = len(self._action_buffer) + len(self._event_buffer)
        if buf_size >= _MAX_BUFFER_SIZE:
            asyncio.create_task(self._flush_once())

    # ------------------------------------------------------------------
    # Action recording
    # ------------------------------------------------------------------

    def record_action(self, envelope: ActionEnvelope, result: ActionResult) -> None:
        submitted_str = envelope.metadata.get("submitted_at")
        submitted_at = None
        if submitted_str:
            try:
                submitted_at = datetime.fromisoformat(submitted_str)
            except (ValueError, TypeError):
                submitted_at = datetime.now(timezone.utc)

        # Tally as we write, so the result record's action counts come from nttd's
        # own log rather than the contestant's word. Counted here rather than read
        # back from actions.parquet at session end because the buffer may not have
        # flushed yet, and a count that silently omits the last few seconds of a run
        # is worse than no count.
        self._tally_action(envelope.company_id, str(result.status))

        self._action_buffer.append({
            "action_id": envelope.action_id,
            "agent_id": envelope.metadata.get("participant_id", ""),
            "company_id": envelope.company_id,
            "game_date": envelope.metadata.get("game_date", 0),
            "action_type": envelope.action_type,
            "status": str(result.status),
            "error": result.error or "",
            "error_name": result.error_name or "",
            "error_code": result.error_code if result.error_code is not None else 0,
            "parameters_json": json.dumps(envelope.parameters, default=str),
            "submitted_at": submitted_at or datetime.now(timezone.utc),
            "source": SOURCE_API,
            "client_id": 0,
        })

    def record_client_command(self, command: dict[str, Any], game_date: int) -> None:
        """Record a command issued from the OpenTTD game window.

        Recorded in the same table as API actions rather than a separate one, so any
        reader asking "what did this company do" gets the whole answer. The `source`
        column is what separates them.

        Status is always "success": OpenTTD logs a command after accepting it, so a
        refusal never reaches us. Parameters are absent because the payload is raw
        command serialisation, which is version-specific to decode.
        """
        company_id = int(command.get("company_id", 0))
        self._tally_action(company_id, ActionStatus.SUCCESS.value)

        self._action_buffer.append({
            "action_id": f"cmd_{uuid.uuid4().hex[:12]}",
            "agent_id": "",
            "company_id": company_id,
            "game_date": game_date,
            "action_type": str(command.get("command", "unknown")),
            "status": ActionStatus.SUCCESS.value,
            "error": "",
            "error_name": "",
            "error_code": 0,
            "parameters_json": "",
            "submitted_at": datetime.now(timezone.utc),
            "source": SOURCE_CLIENT,
            "client_id": int(command.get("client_id", 0)),
        })

    def _tally_action(self, company_id: int, status: str) -> None:
        """Count an action against its company.

        Companies below 0 are skipped: operator-tier refusals are logged against -1
        and belong in the run's attestation, not in any contestant's action count.
        """
        if company_id is None or company_id < 0:
            return
        counts = self._action_counts.setdefault(
            int(company_id), {"total_actions": 0, "successful_actions": 0},
        )
        counts["total_actions"] += 1
        if status == ActionStatus.SUCCESS.value:
            counts["successful_actions"] += 1

    def action_counts(self) -> dict[int, dict[str, int]]:
        """Observed action counts per company, for the result record."""
        return {cid: dict(counts) for cid, counts in self._action_counts.items()}

    # ------------------------------------------------------------------
    # Event recording
    # ------------------------------------------------------------------

    def record_event(
        self,
        game_date: int,
        event_type: str,
        company_id: int | None = None,
        entity_type: str | None = None,
        entity_id: int | None = None,
        detail: str | None = None,
    ) -> None:
        self._event_buffer.append({
            "game_date": game_date,
            "event_type": event_type,
            "company_id": company_id or 0,
            "detail": detail or "",
            "timestamp": datetime.now(timezone.utc),
        })

    # ------------------------------------------------------------------
    # Agent tracking
    # ------------------------------------------------------------------

