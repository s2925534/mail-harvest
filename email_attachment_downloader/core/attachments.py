import re
import zipfile
from datetime import datetime
from email.message import Message
from pathlib import Path
from typing import Iterable, List, Tuple

from ..config.settings import EmailDownloadSettings


def iter_matching_attachments(message: Message, settings: EmailDownloadSettings) -> Iterable[Tuple[str, bytes]]:
    for part in message.walk():
        content_disposition = part.get_content_disposition()
        if content_disposition != "attachment":
            continue

        filename = part.get_filename()
        if not filename:
            continue

        if not attachment_name_matches(filename, settings):
            continue

        payload = part.get_payload(decode=True)
        if payload is None:
            continue

        yield filename, payload


def attachment_name_matches(filename: str, settings: EmailDownloadSettings) -> bool:
    lower = filename.lower()

    if settings.attachment_extensions:
        if not any(lower.endswith(ext) for ext in settings.attachment_extensions):
            return False

    if settings.attachment_name_contains:
        if not any(keyword in lower for keyword in settings.attachment_name_contains):
            return False

    return True


def safe_filename(filename: str) -> str:
    filename = filename.strip().replace("\\", "_").replace("/", "_")
    return re.sub(r"[^A-Za-z0-9._ -]", "_", filename)


def save_attachment(filename: str, content: bytes, settings: EmailDownloadSettings) -> Path:
    settings.download_dir.mkdir(parents=True, exist_ok=True)

    clean_name = safe_filename(filename)
    path = settings.download_dir / clean_name

    if settings.add_timestamp_to_filename:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = path.with_name(f"{path.stem}_{stamp}{path.suffix}")

    if path.exists() and not settings.overwrite_existing:
        counter = 1
        while True:
            candidate = path.with_name(f"{path.stem}_{counter}{path.suffix}")
            if not candidate.exists():
                path = candidate
                break
            counter += 1

    path.write_bytes(content)

    if settings.extract_zip_files and path.suffix.lower() == ".zip":
        extract_zip(path, settings.download_dir)
        if not settings.keep_zip_files:
            path.unlink(missing_ok=True)

    return path


def extract_zip(zip_path: Path, target_dir: Path) -> List[Path]:
    extracted: List[Path] = []
    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        for member in zip_ref.infolist():
            if member.is_dir():
                continue
            member_name = safe_filename(Path(member.filename).name)
            target_path = target_dir / member_name
            with zip_ref.open(member, "r") as source, target_path.open("wb") as destination:
                destination.write(source.read())
            extracted.append(target_path)
    return extracted
