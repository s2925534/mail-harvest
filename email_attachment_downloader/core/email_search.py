from datetime import datetime, timedelta
from email.message import Message
from email.utils import parsedate_to_datetime
from typing import List

from ..config.settings import EmailDownloadSettings


def build_imap_search_criteria(settings: EmailDownloadSettings, include_read: bool = False) -> List[str]:
    criteria: List[str] = []

    # include_read forces read + unread (used by the state-aware flow so an
    # already-read latest email can still be detected and offered for download).
    if settings.only_unread and not include_read:
        criteria.append("UNSEEN")
    else:
        criteria.append("ALL")

    if settings.target_from:
        criteria.extend(["FROM", f'"{settings.target_from}"'])

    if settings.target_to:
        criteria.extend(["TO", f'"{settings.target_to}"'])

    if settings.target_subject and settings.target_subject_mode in {"contains", "exact"}:
        criteria.extend(["SUBJECT", f'"{settings.target_subject}"'])

    since_date = _since_date(settings)
    if since_date:
        criteria.extend(["SINCE", since_date.strftime("%d-%b-%Y")])

    return criteria


def _since_date(settings: EmailDownloadSettings):
    today = datetime.now().date()
    if settings.target_date_mode == "today":
        return today
    if settings.target_date_mode == "yesterday":
        return today - timedelta(days=1)
    if settings.target_date_mode == "last_n_days":
        return today - timedelta(days=max(settings.target_last_n_days, 1))
    return None


def message_matches_settings(message: Message, settings: EmailDownloadSettings) -> bool:
    subject = message.get("Subject", "") or ""
    sender = message.get("From", "") or ""
    recipient = message.get("To", "") or ""

    if settings.target_from and settings.target_from.lower() not in sender.lower():
        return False

    if settings.target_to and settings.target_to.lower() not in recipient.lower():
        return False

    if settings.target_subject:
        target = settings.target_subject.lower()
        actual = subject.lower()
        if settings.target_subject_mode == "exact" and actual != target:
            return False
        if settings.target_subject_mode != "exact" and target not in actual:
            return False

    if settings.target_date_mode == "yesterday":
        date_header = message.get("Date")
        if date_header:
            email_date = parsedate_to_datetime(date_header).date()
            if email_date != datetime.now().date() - timedelta(days=1):
                return False

    return True
