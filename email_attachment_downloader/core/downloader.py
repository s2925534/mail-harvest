import json
from datetime import datetime
from email import message_from_bytes
from email.policy import default
from pathlib import Path
from typing import Any, Dict, List

from ..config.settings import EmailDownloadSettings
from ..providers.imap_client import ImapClient
from .attachments import iter_matching_attachments, save_attachment
from .body import body_matches, extract_body_rows, save_email_body
from .email_search import build_imap_search_criteria, message_matches_settings


class EmailAttachmentDownloader:
    def __init__(self, settings: EmailDownloadSettings, dry_run: bool = False) -> None:
        self.settings = settings
        self.dry_run = dry_run

    def run(self) -> Dict[str, Any]:
        audit: Dict[str, Any] = {
            "started_at": datetime.now().isoformat(),
            "dry_run": self.dry_run,
            "provider": self.settings.provider,
            "mailbox": self.settings.mailbox,
            "download_dir": str(self.settings.download_dir),
            "download_only_latest": self.settings.download_only_latest,
            "emails": [],
        }

        matched_emails = 0
        matched_attachments = 0
        downloaded_files = 0
        saved_body_files = 0
        scraped_body_rows = 0
        skipped_older_emails = 0
        downloaded_latest = False

        with ImapClient(
            host=self.settings.imap_host,
            port=self.settings.imap_port,
            username=self.settings.username,
            password=self.settings.password,
        ) as client:
            client.select_mailbox(self.settings.mailbox)
            criteria = build_imap_search_criteria(self.settings)
            message_ids = client.search(criteria)

            for message_id in reversed(message_ids):
                raw = client.fetch_message(message_id)
                message = message_from_bytes(raw, policy=default)

                if not message_matches_settings(message, self.settings):
                    continue

                if not body_matches(message, self.settings):
                    continue

                attachments = list(iter_matching_attachments(message, self.settings))
                should_keep_email = bool(attachments) or self.settings.save_body_text or self.settings.save_body_html or self.settings.scrape_body_content
                if not should_keep_email:
                    continue

                # Messages are iterated newest-first (reversed search order), so the
                # first keepable email is the latest supplier feed. With
                # download_only_latest, later (older) matches are treated as
                # superseded: they are not downloaded, only marked read to clear the
                # backlog, so a stale attachment can never overwrite the latest one.
                is_older_duplicate = self.settings.download_only_latest and downloaded_latest

                matched_emails += 1
                email_audit: Dict[str, Any] = {
                    "message_id": message_id.decode(errors="ignore"),
                    "subject": message.get("Subject", ""),
                    "from": message.get("From", ""),
                    "to": message.get("To", ""),
                    "date": message.get("Date", ""),
                    "is_latest": not is_older_duplicate,
                    "skipped_reason": "superseded_by_newer" if is_older_duplicate else None,
                    "attachments": [],
                    "body": {
                        "saved_text_path": None,
                        "saved_html_path": None,
                        "scraped_rows": [],
                    },
                }

                if is_older_duplicate:
                    skipped_older_emails += 1
                    for filename, content in attachments:
                        matched_attachments += 1
                        email_audit["attachments"].append({
                            "filename": filename,
                            "size_bytes": len(content),
                            "downloaded": False,
                            "path": None,
                            "skipped_reason": "superseded_by_newer",
                        })
                    if not self.dry_run and self.settings.mark_as_read:
                        client.mark_as_read(message_id)
                    audit["emails"].append(email_audit)
                    continue

                if not self.dry_run:
                    body_paths = save_email_body(message, message_id, self.settings)
                    email_audit["body"]["saved_text_path"] = body_paths.get("text_path")
                    email_audit["body"]["saved_html_path"] = body_paths.get("html_path")
                    saved_body_files += sum(1 for value in body_paths.values() if value)

                body_rows = extract_body_rows(message, self.settings)
                if body_rows:
                    email_audit["body"]["scraped_rows"] = body_rows
                    scraped_body_rows += len(body_rows)

                for filename, content in attachments:
                    matched_attachments += 1
                    attachment_audit: Dict[str, Any] = {
                        "filename": filename,
                        "size_bytes": len(content),
                        "downloaded": False,
                        "path": None,
                    }

                    if not self.dry_run:
                        saved_path = save_attachment(filename, content, self.settings)
                        downloaded_files += 1
                        attachment_audit["downloaded"] = True
                        attachment_audit["path"] = str(saved_path)

                    email_audit["attachments"].append(attachment_audit)

                downloaded_latest = True

                audit["emails"].append(email_audit)

                if not self.dry_run:
                    if self.settings.mark_as_read:
                        client.mark_as_read(message_id)
                    if self.settings.move_processed_email:
                        client.move_message(message_id, self.settings.processed_mailbox)

        audit["finished_at"] = datetime.now().isoformat()
        audit["matched_emails"] = matched_emails
        audit["matched_attachments"] = matched_attachments
        audit["downloaded_files"] = downloaded_files
        audit["saved_body_files"] = saved_body_files
        audit["scraped_body_rows"] = scraped_body_rows
        audit["skipped_older_emails"] = skipped_older_emails

        log_file = self._write_audit_log(audit)
        audit["log_file"] = str(log_file)
        return audit

    def _write_audit_log(self, audit: Dict[str, Any]) -> Path:
        self.settings.log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = self.settings.log_dir / f"email_attachment_download_{stamp}.json"
        log_file.write_text(json.dumps(audit, indent=2), encoding="utf-8")
        return log_file
