"""Gmail through a small Google Apps Script web app (apps_script/MailHarvestWebApp.gs).

The easiest HTTPS alternative to IMAP: no Google Cloud project or OAuth client.
The mailbox owner deploys the script as a web app in their own Google account
and gives mail-harvest its URL (GMAIL_WEBAPP_URL). The script only answers for
the senders listed in it and is read-only.

Same interface as ImapClient (search / fetch_message / fetch_headers), so the
downloader, filters, state DB and audit logs work unchanged.
"""
import json
import urllib.error
import urllib.parse
import urllib.request
from contextlib import AbstractContextManager
from typing import List, Optional

from .gmail_api_client import imap_criteria_to_query


class GmailWebAppError(RuntimeError):
    pass


class GmailWebAppClient(AbstractContextManager):
    def __init__(self, url: str, timeout: Optional[int] = 120) -> None:
        url = str(url or "").strip()
        if not url.startswith("https://"):
            raise ValueError("GMAIL_WEBAPP_URL (the Apps Script web app URL) is required for "
                             "EMAIL_PROVIDER=gmail_webapp.")
        self.url = url
        # Large feeds take the script a while to serialise; allow for it.
        self.timeout = max(int(timeout or 0), 120)
        self.mailbox = "INBOX"

    def _get(self, **params) -> bytes:
        url = f"{self.url}{'&' if '?' in self.url else '?'}{urllib.parse.urlencode(params)}"
        try:
            with urllib.request.urlopen(urllib.request.Request(url), timeout=self.timeout) as response:
                return response.read()   # urllib follows the script.googleusercontent.com redirect
        except urllib.error.HTTPError as error:
            raise GmailWebAppError(f"web app answered HTTP {error.code}") from None

    def _json(self, **params) -> dict:
        body = self._get(**params)
        try:
            data = json.loads(body)
        except ValueError:
            raise GmailWebAppError("web app did not answer with JSON - is GMAIL_WEBAPP_URL the /exec URL "
                                   "of a deployment with access 'Anyone'?") from None
        if not data.get("ok"):
            raise GmailWebAppError(f"web app error: {data.get('error')}")
        return data

    def ping(self) -> dict:
        return self._json(action="ping")

    # --- ImapClient interface ---------------------------------------------
    def __enter__(self) -> "GmailWebAppClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def select_mailbox(self, mailbox: str) -> None:
        self.mailbox = mailbox or "INBOX"

    def search(self, criteria: List[str]) -> List[bytes]:
        """Message ids oldest-first (IMAP order); the downloader walks them in reverse."""
        data = self._json(action="search", q=imap_criteria_to_query(criteria, self.mailbox), max=50)
        ids = [str(m["id"]).encode() for m in data.get("messages") or []]
        return list(reversed(ids))   # the script lists newest first

    def fetch_message(self, message_id: bytes) -> bytes:
        body = self._get(action="raw", id=message_id.decode())
        if body[:1] == b"{" and b'"ok":false' in body[:200].replace(b" ", b""):
            raise GmailWebAppError(f"web app could not read message {message_id.decode()}")
        return body

    def fetch_headers(self, message_id: bytes) -> bytes:
        return self._get(action="headers", id=message_id.decode())

    def mark_as_read(self, message_id: bytes) -> None:
        raise NotImplementedError("The web app is read-only; MARK_AS_READ is not available with gmail_webapp.")

    def move_message(self, message_id: bytes, target_mailbox: str) -> None:
        raise NotImplementedError("The web app is read-only; MOVE_PROCESSED_EMAIL is not available with gmail_webapp.")
