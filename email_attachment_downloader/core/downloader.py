import json
import sys
from datetime import datetime
from email import message_from_bytes
from email.policy import default
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..config.settings import EmailDownloadSettings
from ..providers.imap_client import ImapClient
from ..store import HarvestStore, sha256_bytes
from .attachments import iter_matching_attachments, save_attachment
from .body import body_matches, extract_body_rows, save_email_body
from .email_search import build_imap_search_criteria, message_matches_settings


class EmailAttachmentDownloader:
    def __init__(self, settings: EmailDownloadSettings, dry_run: bool = False) -> None:
        self.settings = settings
        self.dry_run = dry_run

    def run(self) -> Dict[str, Any]:
        store: Optional[HarvestStore] = None
        if self.settings.enable_state_db:
            store = HarvestStore(self.settings.db_path)
            store.initialize()

        audit: Dict[str, Any] = {
            "started_at": datetime.now().isoformat(),
            "dry_run": self.dry_run,
            "provider": self.settings.provider,
            "mailbox": self.settings.mailbox,
            "download_dir": str(self.settings.download_dir),
            "download_only_latest": self.settings.download_only_latest,
            "state_db": str(store.db_path) if store else None,
            "emails": [],
        }

        matched_emails = 0
        matched_attachments = 0
        downloaded_files = 0
        saved_body_files = 0
        scraped_body_rows = 0
        skipped_older_emails = 0
        skipped_by_decision = 0
        downloaded_latest = False

        with ImapClient(
            host=self.settings.imap_host,
            port=self.settings.imap_port,
            username=self.settings.username,
            password=self.settings.password,
        ) as client:
            client.select_mailbox(self.settings.mailbox)

            # With the state DB on we must be able to see already-read emails too
            # (to offer the "already read" / "already processed" decisions). Read
            # status is detected via a second UNSEEN search, not by fetching:
            # fetch uses BODY.PEEK and never changes read state.
            include_read = bool(store)
            message_ids = client.search(
                build_imap_search_criteria(self.settings, include_read=include_read)
            )

            unseen_ids = set()
            if include_read:
                unseen_ids = set(
                    client.search(
                        build_imap_search_criteria(self.settings, include_read=True) + ["UNSEEN"]
                    )
                )

            for message_id in reversed(message_ids):
                # Messages are iterated newest-first (reversed search order). Once
                # the latest keepable feed has been handled, any remaining matches
                # are older/superseded: fetch only their HEADERS (not the large
                # attachment body), record + mark them read, and move on. This is
                # the fast path — the newest feed is the only full download.
                if self.settings.download_only_latest and downloaded_latest:
                    try:
                        header_msg = message_from_bytes(
                            client.fetch_headers(message_id), policy=default
                        )
                    except Exception:
                        continue
                    if not message_matches_settings(header_msg, self.settings):
                        continue

                    matched_emails += 1
                    skipped_older_emails += 1
                    stable_id = (header_msg.get("Message-ID") or "").strip() or message_id.decode(errors="ignore")
                    is_unread = (message_id in unseen_ids) if include_read else True
                    audit["emails"].append({
                        "message_id": stable_id,
                        "subject": header_msg.get("Subject", ""),
                        "from": header_msg.get("From", ""),
                        "to": header_msg.get("To", ""),
                        "date": header_msg.get("Date", ""),
                        "is_latest": False,
                        "was_unread": is_unread,
                        "decision": None,
                        "skipped_reason": "superseded_by_newer",
                        "attachments": [],
                        "body": {"saved_text_path": None, "saved_html_path": None, "scraped_rows": []},
                    })
                    if store and not self.dry_run:
                        store.record_email(
                            stable_id, header_msg.get("Subject", ""), header_msg.get("From", ""),
                            header_msg.get("To", ""), header_msg.get("Date", ""),
                            self.settings.mailbox, is_unread,
                        )
                    if not self.dry_run and self.settings.mark_as_read:
                        client.mark_as_read(message_id)
                    continue

                # ---- latest not found yet: full fetch to validate + download ----
                raw = client.fetch_message(message_id)  # PEEK: does not mark read
                message = message_from_bytes(raw, policy=default)

                if not message_matches_settings(message, self.settings):
                    continue
                if not body_matches(message, self.settings):
                    continue

                attachments = list(iter_matching_attachments(message, self.settings))
                should_keep_email = bool(attachments) or self.settings.save_body_text or self.settings.save_body_html or self.settings.scrape_body_content
                if not should_keep_email:
                    continue

                subject = message.get("Subject", "")
                sender = message.get("From", "")
                recipient = message.get("To", "")
                email_date = message.get("Date", "")
                stable_id = (message.get("Message-ID") or "").strip() or message_id.decode(errors="ignore")
                is_unread = (message_id in unseen_ids) if include_read else True

                matched_emails += 1
                email_audit: Dict[str, Any] = {
                    "message_id": stable_id,
                    "subject": subject,
                    "from": sender,
                    "to": recipient,
                    "date": email_date,
                    "is_latest": True,
                    "was_unread": is_unread,
                    "decision": None,
                    "skipped_reason": None,
                    "attachments": [],
                    "body": {"saved_text_path": None, "saved_html_path": None, "scraped_rows": []},
                }

                if store and not self.dry_run:
                    store.record_email(stable_id, subject, sender, recipient, email_date,
                                       self.settings.mailbox, is_unread)

                # ---- latest keepable email: decide by read / processed state ----
                already_processed = store.is_message_processed(stable_id) if store else False
                proceed, decision = self._decide(is_unread, already_processed)
                email_audit["decision"] = decision
                downloaded_latest = True  # the latest has now been handled (download or skip)

                if not proceed:
                    skipped_by_decision += 1
                    email_audit["skipped_reason"] = decision
                    for filename, content in attachments:
                        email_audit["attachments"].append({
                            "filename": filename, "size_bytes": len(content),
                            "downloaded": False, "path": None, "skipped_reason": decision,
                        })
                    # Do NOT mark read: leave it so it can be reconsidered next run.
                    audit["emails"].append(email_audit)
                    continue

                # ---- proceed: download the latest ----
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
                        "filename": filename, "size_bytes": len(content),
                        "downloaded": False, "path": None,
                    }
                    if not self.dry_run:
                        saved_path = save_attachment(filename, content, self.settings)
                        downloaded_files += 1
                        attachment_audit["downloaded"] = True
                        attachment_audit["path"] = str(saved_path)
                        if store:
                            store.record_download(stable_id, filename, str(saved_path),
                                                  len(content), sha256_bytes(content))
                    email_audit["attachments"].append(attachment_audit)

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
        audit["skipped_by_decision"] = skipped_by_decision

        log_file = self._write_audit_log(audit)
        audit["log_file"] = str(log_file)
        return audit

    def _decide(self, is_unread: bool, already_processed: bool) -> Tuple[bool, str]:
        """Return (proceed, decision) for the latest email given its state.

        - unread & not processed -> auto download.
        - already processed      -> confirm reprocess (interactive) / policy (headless).
        - read & not processed   -> confirm download   (interactive) / policy (headless).
        assume_yes forces proceed.
        """
        if is_unread and not already_processed:
            return True, "unread_auto_download"

        if self.settings.assume_yes:
            return True, ("reprocess_forced_yes" if already_processed else "read_forced_yes")

        interactive = sys.stdin.isatty() and not self.dry_run

        if already_processed:
            if interactive:
                proceed = self._prompt("This feed was already PROCESSED. Reprocess it?", default_yes=False)
                return proceed, ("reprocess_confirmed" if proceed else "reprocess_declined")
            proceed = self.settings.on_already_processed == "proceed"
            return proceed, ("reprocess_policy_proceed" if proceed else "reprocess_policy_skip")

        # read but not processed
        if interactive:
            proceed = self._prompt("This email is already READ. Download it?", default_yes=True)
            return proceed, ("read_confirmed" if proceed else "read_declined")
        proceed = self.settings.on_already_read == "proceed"
        return proceed, ("read_policy_proceed" if proceed else "read_policy_skip")

    @staticmethod
    def _prompt(question: str, default_yes: bool) -> bool:
        suffix = "[Y/n]" if default_yes else "[y/N]"
        try:
            answer = input(f"{question} {suffix} ").strip().lower()
        except EOFError:
            return default_yes
        if not answer:
            return default_yes
        return answer in {"y", "yes"}

    def _write_audit_log(self, audit: Dict[str, Any]) -> Path:
        self.settings.log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = self.settings.log_dir / f"email_attachment_download_{stamp}.json"
        log_file.write_text(json.dumps(audit, indent=2), encoding="utf-8")
        return log_file
