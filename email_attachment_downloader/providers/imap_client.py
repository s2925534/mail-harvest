import imaplib
from contextlib import AbstractContextManager
from typing import List, Tuple


class ImapClient(AbstractContextManager):
    def __init__(self, host: str, port: int, username: str, password: str,
                 timeout: int | None = 60) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        # A non-positive/None timeout disables it (blocking sockets). Otherwise the
        # value is a socket timeout in seconds that applies to the connection AND to
        # every later blocking operation (login/search/fetch), so a stalled fetch
        # raises socket.timeout instead of hanging the process forever.
        self.timeout = timeout if (timeout and timeout > 0) else None
        self.connection: imaplib.IMAP4_SSL | None = None

    def __enter__(self) -> "ImapClient":
        self.connection = imaplib.IMAP4_SSL(self.host, self.port, timeout=self.timeout)
        self.connection.login(self.username, self.password)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.connection:
            try:
                self.connection.logout()
            except Exception:
                pass

    def select_mailbox(self, mailbox: str) -> None:
        assert self.connection is not None
        status, _ = self.connection.select(mailbox)
        if status != "OK":
            raise RuntimeError(f"Could not select mailbox: {mailbox}")

    def search(self, criteria: List[str]) -> List[bytes]:
        assert self.connection is not None
        status, data = self.connection.search(None, *criteria)
        if status != "OK":
            return []
        if not data or not data[0]:
            return []
        return data[0].split()

    def fetch_message(self, message_id: bytes) -> bytes:
        # BODY.PEEK[] fetches the full message WITHOUT setting the \Seen flag, so
        # inspecting a candidate email (to check its attachment / read state)
        # never marks it read. Read state is set explicitly via mark_as_read only
        # when we actually act on the email.
        assert self.connection is not None
        status, data = self.connection.fetch(message_id, "(BODY.PEEK[])")
        if status != "OK" or not data:
            raise RuntimeError(f"Could not fetch email id {message_id!r}")
        for item in data:
            if isinstance(item, tuple):
                return item[1]
        raise RuntimeError(f"No message payload returned for email id {message_id!r}")

    def fetch_headers(self, message_id: bytes) -> bytes:
        # BODY.PEEK[HEADER] fetches only the RFC822 headers (no body / attachment)
        # and does not set \Seen. Used for older, superseded feeds so we can record
        # and mark them read without pulling their (large) attachment payload.
        assert self.connection is not None
        status, data = self.connection.fetch(message_id, "(BODY.PEEK[HEADER])")
        if status != "OK" or not data:
            raise RuntimeError(f"Could not fetch headers for email id {message_id!r}")
        for item in data:
            if isinstance(item, tuple):
                return item[1]
        raise RuntimeError(f"No header payload returned for email id {message_id!r}")

    def mark_as_read(self, message_id: bytes) -> None:
        assert self.connection is not None
        self.connection.store(message_id, "+FLAGS", "\\Seen")

    def move_message(self, message_id: bytes, target_mailbox: str) -> None:
        assert self.connection is not None
        self.connection.copy(message_id, target_mailbox)
        self.connection.store(message_id, "+FLAGS", "\\Deleted")
        self.connection.expunge()
