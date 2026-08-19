"""SQLite state store for the harvester.

Records which emails were accessed, which files were downloaded, and whether a
download was later processed by the downstream sync. The live DB
(state/harvest.db) is gitignored; it is auto-created from the committed
state/schema.sql on first use. See state/schema.sql.
"""
import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

# Harvester project root = two levels up from this file
# (.../email_attachment_downloader/store.py -> project root).
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "state" / "harvest.db"
SCHEMA_PATH = PROJECT_ROOT / "state" / "schema.sql"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class HarvestStore:
    def __init__(self, db_path: Optional[Path] = None, schema_path: Optional[Path] = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.schema_path = Path(schema_path) if schema_path else SCHEMA_PATH

    def initialize(self) -> None:
        """Create the DB (and its parent dir) from schema.sql if needed. Idempotent."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        schema_sql = self.schema_path.read_text(encoding="utf-8")
        with self._connect() as conn:
            conn.executescript(schema_sql)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    # ---- writes -------------------------------------------------------------

    def record_email(
        self,
        message_id: str,
        subject: str,
        sender: str,
        recipient: str,
        email_date: str,
        mailbox: str,
        was_unread: bool,
    ) -> None:
        """Insert the email if not already recorded (first-access wins for was_unread)."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO emails
                    (message_id, subject, sender, recipient, email_date, mailbox,
                     was_unread, first_accessed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(message_id) DO NOTHING
                """,
                (message_id, subject, sender, recipient, email_date, mailbox,
                 1 if was_unread else 0, _now()),
            )

    def record_download(
        self,
        message_id: str,
        filename: str,
        saved_path: str,
        size_bytes: int,
        sha256: str,
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO downloads
                    (message_id, filename, saved_path, size_bytes, sha256, downloaded_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (message_id, filename, saved_path, size_bytes, sha256, _now()),
            )
            return int(cur.lastrowid)

    def mark_processed(self, saved_path: str, result: str = "ok") -> int:
        """Stamp processed_at on the most recent download whose saved_path matches.

        Matches by exact saved_path first, then by filename basename as a fallback.
        Returns the number of rows updated.
        """
        stamp = _now()
        name = Path(saved_path).name
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE downloads SET processed_at = ?, processed_result = ?
                WHERE id = (
                    SELECT id FROM downloads
                    WHERE saved_path = ? OR filename = ?
                    ORDER BY downloaded_at DESC, id DESC LIMIT 1
                )
                """,
                (stamp, result, saved_path, name),
            )
            return cur.rowcount

    # ---- reads --------------------------------------------------------------

    def is_message_processed(self, message_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM downloads WHERE message_id = ? AND processed_at IS NOT NULL LIMIT 1",
                (message_id,),
            ).fetchone()
            return row is not None

    def has_download(self, message_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM downloads WHERE message_id = ? LIMIT 1", (message_id,)
            ).fetchone()
            return row is not None

    def latest_status(self) -> Dict[str, Any]:
        with self._connect() as conn:
            latest_email = conn.execute(
                "SELECT * FROM emails ORDER BY first_accessed_at DESC LIMIT 1"
            ).fetchone()
            latest_download = conn.execute(
                "SELECT * FROM downloads ORDER BY downloaded_at DESC, id DESC LIMIT 1"
            ).fetchone()
            latest_processed = conn.execute(
                "SELECT * FROM downloads WHERE processed_at IS NOT NULL "
                "ORDER BY processed_at DESC, id DESC LIMIT 1"
            ).fetchone()
        return {
            "db_path": str(self.db_path),
            "latest_email": dict(latest_email) if latest_email else None,
            "latest_download": dict(latest_download) if latest_download else None,
            "latest_processed": dict(latest_processed) if latest_processed else None,
        }
