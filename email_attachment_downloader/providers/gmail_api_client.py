"""Gmail over HTTPS (Gmail API) instead of IMAP.

Drop-in replacement for ImapClient for environments where only HTTPS (port
443) is allowed out, e.g. cloud runners behind a web proxy, where IMAP on port
993 cannot connect. It keeps ImapClient's interface (search / fetch_message /
fetch_headers / mark_as_read / move_message), so the downloader, filters,
state DB and audit logs work unchanged.

Authentication is OAuth 2.0: an OAuth client (GMAIL_CLIENT_ID /
GMAIL_CLIENT_SECRET, "Desktop app" type) and a refresh token for the mailbox
(GMAIL_REFRESH_TOKEN), obtained once with consent_url() + exchange_code().
Only the standard library is used (urllib honours HTTPS_PROXY).
"""
import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from contextlib import AbstractContextManager
from datetime import datetime
from typing import Dict, List, Optional

API_ROOT = "https://gmail.googleapis.com/gmail/v1/users/me"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
MODIFY_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
DEFAULT_REDIRECT_URI = "http://localhost"

# IMAP folder names -> Gmail search terms.
MAILBOX_QUERIES = {"INBOX": "in:inbox", "[GMAIL]/ALL MAIL": "", "ALL": ""}


class GmailApiError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"Gmail API {status}: {message}")
        self.status = status


def _http(method: str, url: str, data: Optional[bytes] = None, headers: Optional[Dict[str, str]] = None,
          timeout: Optional[int] = 60) -> dict:
    request = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(detail)
        except ValueError:
            parsed = {}
        err = parsed.get("error")
        if isinstance(err, dict):
            detail = err.get("message") or detail
        elif parsed:
            detail = parsed.get("error_description") or err or detail
        raise GmailApiError(error.code, str(detail)[:300]) from None
    return json.loads(body) if body else {}


def consent_url(client_id: str, redirect_uri: str = DEFAULT_REDIRECT_URI, scope: str = READONLY_SCOPE,
                login_hint: str = "") -> str:
    """Google sign-in page. After approving, the browser is sent to
    redirect_uri?code=...; with the default http://localhost the page does not
    load, but the address bar holds the code (pass the whole address to
    exchange_code)."""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scope,
        "access_type": "offline",
        "prompt": "consent",
    }
    if login_hint:
        params["login_hint"] = login_hint
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"


def extract_code(text: str) -> str:
    """The authorization code from a pasted redirect address (or the bare code)."""
    text = str(text or "").strip()
    if "code=" in text:
        query = urllib.parse.urlparse(text).query or text.split("?", 1)[-1]
        code = urllib.parse.parse_qs(query).get("code", [""])[0]
        if code:
            return code
    return text


def exchange_code(client_id: str, client_secret: str, code_or_url: str,
                  redirect_uri: str = DEFAULT_REDIRECT_URI) -> dict:
    """Exchange the authorization code; returns Google's token response
    (refresh_token, access_token, scope, ...). Never log the tokens."""
    data = urllib.parse.urlencode({
        "code": extract_code(code_or_url),
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }).encode()
    tokens = _http("POST", TOKEN_URL, data, {"Content-Type": "application/x-www-form-urlencoded"})
    if not tokens.get("refresh_token"):
        raise GmailApiError(400, "Google returned no refresh token; sign in again from the consent link "
                                 "(it must include prompt=consent and access_type=offline).")
    return tokens


def imap_criteria_to_query(criteria: List[str], mailbox: str = "INBOX") -> str:
    """Translate the downloader's IMAP SEARCH criteria into a Gmail search query."""
    terms: List[str] = []
    base = MAILBOX_QUERIES.get(str(mailbox or "INBOX").upper())
    if base is None:
        base = f'label:"{mailbox}"'
    if base:
        terms.append(base)
    tokens = list(criteria)
    i = 0
    while i < len(tokens):
        key = str(tokens[i]).upper()
        value = str(tokens[i + 1]).strip('"') if i + 1 < len(tokens) else ""
        if key == "ALL":
            i += 1
        elif key == "UNSEEN":
            terms.append("is:unread")
            i += 1
        elif key in ("FROM", "TO"):
            terms.append(f'{key.lower()}:"{value}"')
            i += 2
        elif key == "SUBJECT":
            terms.append(f'subject:"{value}"')
            i += 2
        elif key == "SINCE":
            day = datetime.strptime(value, "%d-%b-%Y")
            terms.append(f"after:{day.strftime('%Y/%m/%d')}")
            i += 2
        else:
            raise ValueError(f"IMAP search key not supported by the Gmail API provider: {tokens[i]}")
    return " ".join(terms)


class GmailApiClient(AbstractContextManager):
    def __init__(self, client_id: str, client_secret: str, refresh_token: str,
                 timeout: Optional[int] = 60) -> None:
        if not (client_id and client_secret and refresh_token):
            raise ValueError("GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET and GMAIL_REFRESH_TOKEN are required "
                             "for EMAIL_PROVIDER=gmail_api.")
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.timeout = timeout if (timeout and timeout > 0) else None
        self.access_token: Optional[str] = None
        self.mailbox = "INBOX"

    # --- context manager -------------------------------------------------
    def __enter__(self) -> "GmailApiClient":
        data = urllib.parse.urlencode({
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token",
        }).encode()
        tokens = _http("POST", TOKEN_URL, data, {"Content-Type": "application/x-www-form-urlencoded"},
                       self.timeout)
        self.access_token = tokens["access_token"]
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.access_token = None

    def _api(self, method: str, path: str, params: Optional[dict] = None, body: Optional[dict] = None) -> dict:
        url = f"{API_ROOT}/{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params, doseq=True)
        headers = {"Authorization": f"Bearer {self.access_token}"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        return _http(method, url, data, headers, self.timeout)

    # --- ImapClient interface ---------------------------------------------
    def select_mailbox(self, mailbox: str) -> None:
        self.mailbox = mailbox or "INBOX"

    def search(self, criteria: List[str]) -> List[bytes]:
        """Message ids oldest-first (IMAP order); the downloader walks them in reverse."""
        query = imap_criteria_to_query(criteria, self.mailbox)
        ids: List[bytes] = []
        page_token = None
        while True:
            params = {"q": query, "maxResults": 500}
            if page_token:
                params["pageToken"] = page_token
            page = self._api("GET", "messages", params)
            ids.extend(m["id"].encode() for m in page.get("messages") or [])
            page_token = page.get("nextPageToken")
            if not page_token:
                break
        return list(reversed(ids))   # Gmail lists newest first

    def fetch_message(self, message_id: bytes) -> bytes:
        message = self._api("GET", f"messages/{message_id.decode()}", {"format": "raw"})
        return base64.urlsafe_b64decode(message["raw"] + "=" * (-len(message["raw"]) % 4))

    def fetch_headers(self, message_id: bytes) -> bytes:
        message = self._api("GET", f"messages/{message_id.decode()}", {"format": "metadata"})
        headers = (message.get("payload") or {}).get("headers") or []
        lines = ["%s: %s" % (h["name"], re.sub(r"[\r\n]+", " ", h["value"])) for h in headers]
        return ("\r\n".join(lines) + "\r\n\r\n").encode("utf-8")

    def mark_as_read(self, message_id: bytes) -> None:
        # Needs the gmail.modify scope; with a read-only sign-in this raises.
        self._api("POST", f"messages/{message_id.decode()}/modify", body={"removeLabelIds": ["UNREAD"]})

    def move_message(self, message_id: bytes, target_mailbox: str) -> None:
        raise NotImplementedError("MOVE_PROCESSED_EMAIL is not supported with EMAIL_PROVIDER=gmail_api; "
                                  "use Gmail filters/labels instead.")
