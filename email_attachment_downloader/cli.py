import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from .config.settings import load_settings
from .core.downloader import EmailAttachmentDownloader
from .store import HarvestStore


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download email attachments matching configurable rules."
    )
    parser.add_argument(
        "--env",
        default=".env",
        help="Path to the environment file. Default: .env",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Search and report matching attachments without downloading them.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Assume yes to confirmations (already-read / already-processed).",
    )
    parser.add_argument(
        "--mark-processed",
        metavar="PATH",
        help="Mark a downloaded file as processed in the state DB, then exit.",
    )
    parser.add_argument(
        "--processed-result",
        default="ok",
        help="Result label stored alongside --mark-processed. Default: ok",
    )
    parser.add_argument(
        "--gmail-auth-url",
        action="store_true",
        help="EMAIL_PROVIDER=gmail_api: print the Google sign-in link (needs GMAIL_CLIENT_ID), then exit.",
    )
    parser.add_argument(
        "--gmail-auth-code",
        metavar="URL_OR_CODE",
        help="EMAIL_PROVIDER=gmail_api: exchange the address Google redirected to (or its code) for a "
             "refresh token, save it to --gmail-token-file, then exit. The token is never printed.",
    )
    parser.add_argument(
        "--gmail-token-file",
        default=".gmail_refresh_token",
        help="Where --gmail-auth-code saves the refresh token (mode 600). Default: .gmail_refresh_token",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print the latest accessed email / download / processed state, then exit.",
    )
    args = parser.parse_args()

    env_path = Path(args.env)
    if env_path.exists():
        load_dotenv(env_path)
    else:
        load_dotenv()

    if args.yes:
        os.environ["AUTO_CONFIRM"] = "true"

    # Gmail API sign-in helpers (run before settings: no refresh token yet).
    if args.gmail_auth_url or args.gmail_auth_code:
        from .providers import gmail_api_client as gmail
        client_id = os.getenv("GMAIL_CLIENT_ID", "").strip()
        redirect = os.getenv("GMAIL_REDIRECT_URI", gmail.DEFAULT_REDIRECT_URI).strip()
        if not client_id:
            raise SystemExit("Set GMAIL_CLIENT_ID (and GMAIL_CLIENT_SECRET) first.")
        if args.gmail_auth_url:
            print(gmail.consent_url(client_id, redirect, login_hint=os.getenv("EMAIL_USERNAME", "").strip()))
            return
        tokens = gmail.exchange_code(client_id, os.getenv("GMAIL_CLIENT_SECRET", "").strip(),
                                     args.gmail_auth_code, redirect)
        token_path = Path(args.gmail_token_file)
        token_path.write_text(tokens["refresh_token"], encoding="utf-8")
        token_path.chmod(0o600)
        print(f"Refresh token saved to {token_path} (scope: {tokens.get('scope')}). "
              "Set GMAIL_REFRESH_TOKEN from it; never commit it.")
        return

    if not os.getenv("GMAIL_REFRESH_TOKEN") and os.getenv("GMAIL_REFRESH_TOKEN_FILE"):
        token_file = Path(os.environ["GMAIL_REFRESH_TOKEN_FILE"]).expanduser()
        if token_file.exists():
            os.environ["GMAIL_REFRESH_TOKEN"] = token_file.read_text(encoding="utf-8").strip()

    settings = load_settings()

    # State-DB-only commands (do not connect to email).
    if args.status:
        store = HarvestStore(settings.db_path)
        store.initialize()
        print(json.dumps(store.latest_status(), indent=2))
        return

    if args.mark_processed:
        store = HarvestStore(settings.db_path)
        store.initialize()
        updated = store.mark_processed(args.mark_processed, args.processed_result)
        print(f"Marked processed: {updated} download row(s) matching {args.mark_processed}")
        return

    downloader = EmailAttachmentDownloader(settings=settings, dry_run=args.dry_run)
    result = downloader.run()

    print("\nEmail attachment downloader completed.")
    print(f"Matched emails: {result['matched_emails']}")
    print(f"Downloaded files: {result['downloaded_files']}")
    print(f"Skipped (superseded by newer): {result['skipped_older_emails']}")
    print(f"Skipped (read/processed decision): {result['skipped_by_decision']}")
    print(f"Log file: {result['log_file']}")
