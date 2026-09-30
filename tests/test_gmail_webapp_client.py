"""Gmail through the Apps Script web app (EMAIL_PROVIDER=gmail_webapp)."""
import json
import os
import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path
from unittest import mock

from email_attachment_downloader.providers import gmail_webapp_client as webapp

URL = "https://script.google.com/macros/s/ABC/exec"


def feed_message():
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = ("Leader Stock Data Feed - 30/09/2026",
                                              "sales@leadersystems.com.au", "pedro@veloso.dev")
    msg["Message-ID"] = "<feed@leader>"
    msg.set_content("Leader Stock Data Feed")
    msg.add_attachment(b'"STOCK CODE","DBP","RRP"\n', maintype="application", subtype="octet-stream",
                       filename="LCSCOMP_H_STOCK.csv")
    return msg.as_bytes()


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def fake_urlopen(requests_seen):
    def urlopen(request, timeout=None):
        url = request.full_url
        requests_seen.append(url)
        if "action=search" in url:
            return FakeResponse(json.dumps({"ok": True, "messages": [
                {"id": "new", "date": 2, "unread": True}, {"id": "old", "date": 1, "unread": False}]}).encode())
        if "action=raw" in url:
            return FakeResponse(feed_message())
        if "action=headers" in url:
            return FakeResponse(b"Subject: Leader Stock Data Feed - 29/09/2026\r\nFrom: sales@leadersystems.com.au\r\n\r\n")
        if "action=ping" in url:
            return FakeResponse(b'{"ok": true, "account": "pedro@veloso.dev"}')
        raise AssertionError(url)
    return urlopen


class ClientTests(unittest.TestCase):
    def test_search_oldest_first_and_query(self):
        seen = []
        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen(seen)):
            with webapp.GmailWebAppClient(URL) as client:
                client.select_mailbox("ALL")
                ids = client.search(["ALL", "FROM", '"sales@leadersystems.com.au"'])
                self.assertEqual(client.ping()["account"], "pedro@veloso.dev")
        self.assertEqual(ids, [b"old", b"new"])
        self.assertIn("q=from%3A%22sales%40leadersystems.com.au%22", seen[0])

    def test_url_required(self):
        with self.assertRaises(ValueError):
            webapp.GmailWebAppClient("")

    def test_non_json_answer_explained(self):
        with mock.patch("urllib.request.urlopen", return_value=FakeResponse(b"<html>sign in</html>")):
            with self.assertRaises(webapp.GmailWebAppError) as ctx:
                webapp.GmailWebAppClient(URL).search(["ALL"])
        self.assertIn("Anyone", str(ctx.exception))


class DownloaderTests(unittest.TestCase):
    def test_latest_feed_downloaded(self):
        from email_attachment_downloader.config import settings
        from email_attachment_downloader.core import downloader
        with tempfile.TemporaryDirectory() as tmp:
            env = {"EMAIL_PROVIDER": "gmail_webapp", "GMAIL_WEBAPP_URL": URL, "EMAIL_MAILBOX": "ALL",
                   "TARGET_FROM": "sales@leadersystems.com.au", "TARGET_SUBJECT": "Leader Stock Data Feed",
                   "TARGET_ATTACHMENT_EXTENSIONS": ".csv", "DOWNLOAD_DIR": tmp, "LOG_DIR": tmp,
                   "ENABLE_STATE_DB": "false", "EMAIL_USERNAME": "", "EMAIL_PASSWORD": ""}
            with mock.patch.dict(os.environ, env), \
                    mock.patch("urllib.request.urlopen", side_effect=fake_urlopen([])):
                result = downloader.EmailAttachmentDownloader(settings.load_settings()).run()
            self.assertEqual((result["downloaded_files"], result["skipped_older_emails"]), (1, 1))
            path = Path(result["emails"][0]["attachments"][0]["path"])
            self.assertTrue(path.read_bytes().startswith(b'"STOCK CODE"'))


if __name__ == "__main__":
    unittest.main()
