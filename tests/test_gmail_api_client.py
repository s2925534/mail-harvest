"""Gmail API provider (HTTPS instead of IMAP)."""
import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from email_attachment_downloader.providers import gmail_api_client as gmail


class QueryTests(unittest.TestCase):
    def test_imap_criteria_become_a_gmail_query(self):
        query = gmail.imap_criteria_to_query(
            ["ALL", "FROM", '"sales@leadersystems.com.au"', "TO", '"pedro@veloso.dev"',
             "SUBJECT", '"Leader Stock Data Feed"', "SINCE", "28-Sep-2026"], "INBOX")
        self.assertEqual(query, 'in:inbox from:"sales@leadersystems.com.au" to:"pedro@veloso.dev" '
                                'subject:"Leader Stock Data Feed" after:2026/09/28')
        self.assertEqual(gmail.imap_criteria_to_query(["ALL", "UNSEEN"], "Suppliers"),
                         'label:"Suppliers" is:unread')
        with self.assertRaises(ValueError):
            gmail.imap_criteria_to_query(["LARGER", "100"])

    def test_code_from_redirect_address(self):
        self.assertEqual(gmail.extract_code("http://localhost/?code=4/abc-123&scope=x"), "4/abc-123")
        self.assertEqual(gmail.extract_code("  4/abc  "), "4/abc")
        url = gmail.consent_url("cid", login_hint="me@x.com")
        self.assertIn("access_type=offline", url)
        self.assertIn("prompt=consent", url)
        self.assertIn("gmail.readonly", url)


class ClientTests(unittest.TestCase):
    def fake_http(self, calls):
        raw = base64.urlsafe_b64encode(b"Subject: Hi\r\nFrom: a@b.c\r\n\r\nbody").decode().rstrip("=")

        def http(method, url, data=None, headers=None, timeout=60):
            calls.append((method, url))
            if url == gmail.TOKEN_URL:
                return {"access_token": "at"}
            if "/messages?" in url:
                if "pageToken" not in url:
                    return {"messages": [{"id": "m3"}, {"id": "m2"}], "nextPageToken": "p2"}
                return {"messages": [{"id": "m1"}]}
            if "format=raw" in url:
                return {"raw": raw}
            if "format=metadata" in url:
                return {"payload": {"headers": [{"name": "Subject", "value": "Hi\r\nthere"},
                                                {"name": "From", "value": "a@b.c"}]}}
            raise AssertionError(url)
        return http

    def test_search_oldest_first_and_fetch(self):
        calls = []
        with mock.patch.object(gmail, "_http", side_effect=self.fake_http(calls)):
            with gmail.GmailApiClient("cid", "secret", "refresh") as client:
                client.select_mailbox("INBOX")
                self.assertEqual(client.search(["ALL", "FROM", '"a@b.c"']), [b"m1", b"m2", b"m3"])
                self.assertTrue(client.fetch_message(b"m1").startswith(b"Subject: Hi"))
                self.assertEqual(client.fetch_headers(b"m1"), b"Subject: Hi there\r\nFrom: a@b.c\r\n\r\n")
        self.assertEqual(calls[0], ("POST", gmail.TOKEN_URL))

    def test_missing_credentials(self):
        with self.assertRaises(ValueError):
            gmail.GmailApiClient("cid", "", "refresh")


class SettingsTests(unittest.TestCase):
    def test_gmail_api_needs_no_imap_password(self):
        from email_attachment_downloader.config import settings
        env = {"EMAIL_PROVIDER": "gmail_api", "GMAIL_CLIENT_ID": "c", "GMAIL_CLIENT_SECRET": "s",
               "GMAIL_REFRESH_TOKEN": "r", "EMAIL_USERNAME": "", "EMAIL_PASSWORD": ""}
        with mock.patch.dict(os.environ, env):
            loaded = settings.load_settings()
        self.assertEqual((loaded.provider, loaded.gmail_refresh_token), ("gmail_api", "r"))
        with mock.patch.dict(os.environ, dict(env, GMAIL_REFRESH_TOKEN="")):
            with self.assertRaises(ValueError):
                settings.load_settings()


class DownloaderTests(unittest.TestCase):
    def test_latest_attachment_downloaded_over_gmail_api(self):
        from email.message import EmailMessage
        from email_attachment_downloader.config import settings
        from email_attachment_downloader.core import downloader

        msg = EmailMessage()
        msg["Subject"], msg["From"], msg["To"] = "Leader Stock Data Feed - 30/09/2026", "sales@leadersystems.com.au", "pedro@veloso.dev"
        msg["Message-ID"] = "<feed@leader>"
        msg.set_content("Leader Stock Data Feed")
        msg.add_attachment(b'"STOCK CODE","DBP","RRP"\n', maintype="application", subtype="octet-stream",
                           filename="LCSCOMP_H_STOCK.csv")
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

        def http(method, url, data=None, headers=None, timeout=60):
            if url == gmail.TOKEN_URL:
                return {"access_token": "at"}
            if "/messages?" in url:
                return {"messages": [{"id": "new"}]}
            if "format=raw" in url:
                return {"raw": raw}
            raise AssertionError(url)

        with tempfile.TemporaryDirectory() as tmp:
            env = {"EMAIL_PROVIDER": "gmail_api", "GMAIL_CLIENT_ID": "c", "GMAIL_CLIENT_SECRET": "s",
                   "GMAIL_REFRESH_TOKEN": "r", "TARGET_FROM": "sales@leadersystems.com.au",
                   "TARGET_SUBJECT": "Leader Stock Data Feed", "TARGET_ATTACHMENT_EXTENSIONS": ".csv",
                   "DOWNLOAD_DIR": tmp, "LOG_DIR": tmp, "ENABLE_STATE_DB": "false",
                   "TARGET_DATE_MODE": "last_n_days", "TARGET_LAST_N_DAYS": "2"}
            with mock.patch.dict(os.environ, env), mock.patch.object(gmail, "_http", side_effect=http):
                result = downloader.EmailAttachmentDownloader(settings.load_settings()).run()
            self.assertEqual(result["downloaded_files"], 1)
            saved = Path(result["emails"][0]["attachments"][0]["path"])
            self.assertTrue(saved.read_bytes().startswith(b'"STOCK CODE"'))


if __name__ == "__main__":
    unittest.main()
