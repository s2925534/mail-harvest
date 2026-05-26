import html
import re
from datetime import datetime
from email.message import Message
from pathlib import Path
from typing import Dict, List, Optional

from ..config.settings import EmailDownloadSettings
from .attachments import safe_filename


def extract_email_body(message: Message) -> Dict[str, Optional[str]]:
    """Return best plain text and HTML bodies from an email message."""
    text_parts: List[str] = []
    html_parts: List[str] = []

    if message.is_multipart():
        for part in message.walk():
            content_disposition = part.get_content_disposition()
            if content_disposition == "attachment":
                continue

            content_type = part.get_content_type()
            if content_type not in {"text/plain", "text/html"}:
                continue

            try:
                content = part.get_content()
            except Exception:
                payload = part.get_payload(decode=True)
                if payload is None:
                    continue
                charset = part.get_content_charset() or "utf-8"
                content = payload.decode(charset, errors="replace")

            if content_type == "text/plain":
                text_parts.append(str(content).strip())
            elif content_type == "text/html":
                html_parts.append(str(content).strip())
    else:
        content_type = message.get_content_type()
        try:
            content = message.get_content()
        except Exception:
            payload = message.get_payload(decode=True)
            charset = message.get_content_charset() or "utf-8"
            content = payload.decode(charset, errors="replace") if payload else ""

        if content_type == "text/html":
            html_parts.append(str(content).strip())
        else:
            text_parts.append(str(content).strip())

    html_body = "\n\n".join(part for part in html_parts if part)
    text_body = "\n\n".join(part for part in text_parts if part)

    if not text_body and html_body:
        text_body = html_to_text(html_body)

    return {
        "text": text_body or None,
        "html": html_body or None,
    }


def html_to_text(html_body: str) -> str:
    html_body = re.sub(r"(?is)<(script|style).*?>.*?</\\1>", "", html_body)
    html_body = re.sub(r"(?i)<br\s*/?>", "\n", html_body)
    html_body = re.sub(r"(?i)</p>", "\n\n", html_body)
    html_body = re.sub(r"<[^>]+>", " ", html_body)
    html_body = html.unescape(html_body)
    html_body = re.sub(r"[ \t\r\f\v]+", " ", html_body)
    html_body = re.sub(r"\n\s+", "\n", html_body)
    html_body = re.sub(r"\n{3,}", "\n\n", html_body)
    return html_body.strip()


def body_matches(message: Message, settings: EmailDownloadSettings) -> bool:
    if not settings.body_contains:
        return True

    bodies = extract_email_body(message)
    combined = "\n".join(value for value in bodies.values() if value).lower()
    return all(keyword.lower() in combined for keyword in settings.body_contains)


def save_email_body(message: Message, message_id: bytes, settings: EmailDownloadSettings) -> Dict[str, Optional[str]]:
    bodies = extract_email_body(message)
    if not settings.save_body_text and not settings.save_body_html:
        return {"text_path": None, "html_path": None}

    settings.body_output_dir.mkdir(parents=True, exist_ok=True)

    message_id_str = message_id.decode(errors="ignore") or "unknown"
    subject = safe_filename(message.get("Subject", "email")[:80]) or "email"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"{stamp}_{message_id_str}_{subject}"

    result: Dict[str, Optional[str]] = {"text_path": None, "html_path": None}

    if settings.save_body_text and bodies["text"]:
        text_path = settings.body_output_dir / f"{base_name}.txt"
        text_path.write_text(bodies["text"] or "", encoding="utf-8")
        result["text_path"] = str(text_path)

    if settings.save_body_html and bodies["html"]:
        html_path = settings.body_output_dir / f"{base_name}.html"
        html_path.write_text(bodies["html"] or "", encoding="utf-8")
        result["html_path"] = str(html_path)

    return result


def extract_body_rows(message: Message, settings: EmailDownloadSettings) -> List[Dict[str, str]]:
    """
    Extract simple key/value rows from the body.

    This is intentionally conservative. It is useful for supplier emails that put
    CSV-like values, product notices, or file links in the email body rather than
    in an attachment.
    """
    if not settings.scrape_body_content:
        return []

    bodies = extract_email_body(message)
    text = bodies["text"] or ""
    rows: List[Dict[str, str]] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if settings.body_line_contains:
            lower_line = line.lower()
            if not any(keyword.lower() in lower_line for keyword in settings.body_line_contains):
                continue

        if settings.body_key_value_separator and settings.body_key_value_separator in line:
            key, value = line.split(settings.body_key_value_separator, 1)
            rows.append({"key": key.strip(), "value": value.strip(), "raw": line})
        else:
            rows.append({"raw": line})

    return rows
