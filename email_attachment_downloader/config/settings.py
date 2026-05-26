import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


def _bool(value: str, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _list(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(frozen=True)
class EmailDownloadSettings:
    provider: str
    imap_host: str
    imap_port: int
    username: str
    password: str
    mailbox: str

    target_from: str
    target_to: str
    target_subject: str
    target_subject_mode: str

    target_date_mode: str
    target_last_n_days: int
    only_unread: bool

    attachment_extensions: List[str]
    attachment_name_contains: List[str]

    body_contains: List[str]
    save_body_text: bool
    save_body_html: bool
    scrape_body_content: bool
    body_line_contains: List[str]
    body_key_value_separator: str
    body_output_dir: Path

    extract_zip_files: bool
    keep_zip_files: bool

    download_dir: Path
    overwrite_existing: bool
    add_timestamp_to_filename: bool

    mark_as_read: bool
    move_processed_email: bool
    processed_mailbox: str

    log_dir: Path


def load_settings() -> EmailDownloadSettings:
    username = os.getenv("EMAIL_USERNAME", "").strip()
    password = os.getenv("EMAIL_PASSWORD", "").strip()
    if not username or not password:
        raise ValueError("EMAIL_USERNAME and EMAIL_PASSWORD are required.")

    provider = os.getenv("EMAIL_PROVIDER", "custom").strip().lower()
    host = os.getenv("EMAIL_IMAP_HOST", "").strip()
    if not host:
        if provider == "gmail":
            host = "imap.gmail.com"
        elif provider in {"outlook", "hotmail"}:
            host = "imap-mail.outlook.com"
        else:
            raise ValueError("EMAIL_IMAP_HOST is required for custom providers.")

    return EmailDownloadSettings(
        provider=provider,
        imap_host=host,
        imap_port=int(os.getenv("EMAIL_IMAP_PORT", "993")),
        username=username,
        password=password,
        mailbox=os.getenv("EMAIL_MAILBOX", "INBOX").strip() or "INBOX",
        target_from=os.getenv("TARGET_FROM", "").strip(),
        target_to=os.getenv("TARGET_TO", "").strip(),
        target_subject=os.getenv("TARGET_SUBJECT", "").strip(),
        target_subject_mode=os.getenv("TARGET_SUBJECT_MODE", "contains").strip().lower(),
        target_date_mode=os.getenv("TARGET_DATE_MODE", "").strip().lower(),
        target_last_n_days=int(os.getenv("TARGET_LAST_N_DAYS", "7")),
        only_unread=_bool(os.getenv("ONLY_UNREAD", "false")),
        attachment_extensions=[ext.lower() for ext in _list(os.getenv("TARGET_ATTACHMENT_EXTENSIONS"))],
        attachment_name_contains=[x.lower() for x in _list(os.getenv("TARGET_ATTACHMENT_NAME_CONTAINS"))],
        body_contains=_list(os.getenv("TARGET_BODY_CONTAINS")),
        save_body_text=_bool(os.getenv("SAVE_BODY_TEXT", "false")),
        save_body_html=_bool(os.getenv("SAVE_BODY_HTML", "false")),
        scrape_body_content=_bool(os.getenv("SCRAPE_BODY_CONTENT", "false")),
        body_line_contains=_list(os.getenv("BODY_LINE_CONTAINS")),
        body_key_value_separator=os.getenv("BODY_KEY_VALUE_SEPARATOR", ":").strip() or ":",
        body_output_dir=Path(os.getenv("BODY_OUTPUT_DIR", "downloads/email_bodies")).resolve(),
        extract_zip_files=_bool(os.getenv("EXTRACT_ZIP_FILES", "true"), True),
        keep_zip_files=_bool(os.getenv("KEEP_ZIP_FILES", "true"), True),
        download_dir=Path(os.getenv("DOWNLOAD_DIR", "downloads")).resolve(),
        overwrite_existing=_bool(os.getenv("OVERWRITE_EXISTING", "true"), True),
        add_timestamp_to_filename=_bool(os.getenv("ADD_TIMESTAMP_TO_FILENAME", "false")),
        mark_as_read=_bool(os.getenv("MARK_AS_READ", "false")),
        move_processed_email=_bool(os.getenv("MOVE_PROCESSED_EMAIL", "false")),
        processed_mailbox=os.getenv("PROCESSED_MAILBOX", "Processed").strip() or "Processed",
        log_dir=Path(os.getenv("LOG_DIR", "logs")).resolve(),
    )
