"""
Backup Manager — local SQLite database backup and restore.
"""
import json
import shutil
import sqlite3
from datetime import date, datetime
from pathlib import Path

DATA_DIR   = Path(__file__).parent.parent / "data"
LOG_FILE   = DATA_DIR / "backup_log.json"
MAX_BACKUPS = 12


class BackupManager:

    def __init__(self, db_path: str, company_slug: str):
        self.db_path      = Path(db_path)
        self.company_slug = company_slug
        self._log         = self._load_log()

    # ── Log persistence ───────────────────────────────────────────────────────

    def _load_log(self) -> dict:
        try:
            if LOG_FILE.exists():
                with open(LOG_FILE) as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _save_log(self):
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "w") as f:
            json.dump(self._log, f, indent=2)

    def _company_log(self) -> list:
        return self._log.setdefault(self.company_slug, [])

    # ── Backup ────────────────────────────────────────────────────────────────

    def create_backup(self, dest_dir: str = "") -> Path:
        """
        Flush WAL then copy the .db file to dest_dir (default: data/backups/).
        Returns the path of the new backup file.
        """
        if dest_dir:
            backup_dir = Path(dest_dir)
        else:
            backup_dir = DATA_DIR / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)

        # Flush WAL so the backup file is consistent
        try:
            con = sqlite3.connect(str(self.db_path))
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            con.close()
        except Exception:
            pass

        ts        = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest_name = f"{self.company_slug}_{ts}.db"
        dest_path = backup_dir / dest_name
        shutil.copy2(self.db_path, dest_path)

        entry = {
            "timestamp":  datetime.now().isoformat(),
            "path":       str(dest_path),
            "size_bytes": dest_path.stat().st_size,
        }
        log = self._company_log()
        log.append(entry)

        # Prune oldest if over limit (only auto-backups in default dir)
        if not dest_dir:
            default_entries = [e for e in log
                               if Path(e["path"]).parent == backup_dir]
            if len(default_entries) > MAX_BACKUPS:
                oldest = default_entries[0]
                try:
                    Path(oldest["path"]).unlink(missing_ok=True)
                except Exception:
                    pass
                log.remove(oldest)

        self._save_log()
        return dest_path

    # ── Restore ───────────────────────────────────────────────────────────────

    def restore_backup(self, backup_path: str) -> Path:
        """
        Safety-copy current DB then overwrite it with backup_path.
        Returns the path of the safety copy.
        """
        backup_path = Path(backup_path)
        if not backup_path.exists():
            raise FileNotFoundError(f"Backup not found: {backup_path}")

        safety_dir  = DATA_DIR / "backups" / "pre_restore"
        safety_dir.mkdir(parents=True, exist_ok=True)
        ts          = datetime.now().strftime("%Y%m%d_%H%M%S")
        safety_copy = safety_dir / f"{self.company_slug}_pre_restore_{ts}.db"

        try:
            con = sqlite3.connect(str(self.db_path))
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            con.close()
        except Exception:
            pass

        shutil.copy2(self.db_path, safety_copy)
        shutil.copy2(backup_path, self.db_path)
        return safety_copy

    # ── Queries ───────────────────────────────────────────────────────────────

    def list_backups(self) -> list[dict]:
        """Return backup entries for this company, newest first."""
        return list(reversed(self._company_log()))

    def needs_reminder(self) -> bool:
        log = self._company_log()
        if not log:
            return True
        try:
            from core.user_prefs import prefs
            threshold = int(prefs.get("backup_reminder_days", 7))
        except Exception:
            threshold = 7
        try:
            last = datetime.fromisoformat(log[-1]["timestamp"]).date()
            return (date.today() - last).days >= threshold
        except Exception:
            return True

    def days_since_backup(self) -> int:
        log = self._company_log()
        if not log:
            return -1
        try:
            last = datetime.fromisoformat(log[-1]["timestamp"]).date()
            return (date.today() - last).days
        except Exception:
            return -1

    @property
    def last_backup_display(self) -> str:
        log = self._company_log()
        if not log:
            return "Never"
        try:
            dt = datetime.fromisoformat(log[-1]["timestamp"])
            return dt.strftime("%d %b %Y  %H:%M")
        except Exception:
            return "Unknown"
