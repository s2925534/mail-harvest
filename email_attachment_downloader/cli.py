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
