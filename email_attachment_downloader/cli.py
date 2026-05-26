import argparse
from pathlib import Path

from dotenv import load_dotenv

from .config.settings import load_settings
from .core.downloader import EmailAttachmentDownloader


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
    args = parser.parse_args()

    env_path = Path(args.env)
    if env_path.exists():
        load_dotenv(env_path)
    else:
        load_dotenv()

    settings = load_settings()
    downloader = EmailAttachmentDownloader(settings=settings, dry_run=args.dry_run)
    result = downloader.run()

    print("\nEmail attachment downloader completed.")
    print(f"Matched emails: {result['matched_emails']}")
    print(f"Matched attachments: {result['matched_attachments']}")
    print(f"Downloaded files: {result['downloaded_files']}")
    print(f"Log file: {result['log_file']}")
