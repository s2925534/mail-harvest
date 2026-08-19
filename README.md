# Email Attachment Downloader

Standalone Python CLI tool for searching Gmail, Outlook/Hotmail, or custom IMAP mailboxes and downloading targeted attachments into a configured directory.

It was designed as a safe pre-processing tool for supplier CSV feeds before a Shopify sync workflow, but it can be reused for any email attachment download job.

## Features

- Gmail, Outlook/Hotmail, or custom IMAP server support
- Filter emails by sender, recipient, subject, unread status, and date window
- Filter attachments by extension and filename keywords
- Download CSV, XLSX, ZIP, PDF, or any configured file type
- Optional ZIP extraction
- Optional email body capture as plain text or HTML
- Optional body scraping into JSON audit rows
- Dry-run mode before downloading
- Optional mark-as-read and move-to-folder behaviour
- JSON audit log for every run

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

## Run

```bash
python -m email_attachment_downloader
```

Dry run:

```bash
python -m email_attachment_downloader --dry-run
```

## Gmail notes

For Gmail, enable IMAP and use an app password if two-factor authentication is enabled. Do not use your normal Gmail password if Google blocks basic password sign-in.

## Outlook / Hotmail notes

Use:

```env
EMAIL_PROVIDER=outlook
EMAIL_IMAP_HOST=imap-mail.outlook.com
EMAIL_IMAP_PORT=993
```

Depending on your Microsoft account security settings, you may need an app password or OAuth in a later version.

## Attachment targeting

Example supplier CSV download:

```env
TARGET_FROM=supplier@example.com
TARGET_SUBJECT=Daily Supplier Stock File
TARGET_SUBJECT_MODE=contains
TARGET_DATE_MODE=last_n_days
TARGET_LAST_N_DAYS=7
TARGET_ATTACHMENT_EXTENSIONS=.csv,.zip
TARGET_ATTACHMENT_NAME_CONTAINS=stock,inventory
DOWNLOAD_DIR=downloads/supplier/latest
```

## Email body capture

Use this when the useful data is inside the email body instead of an attachment, or when you want to keep a copy of the matched email content for audit purposes.

```env
SAVE_BODY_TEXT=true
SAVE_BODY_HTML=false
BODY_OUTPUT_DIR=downloads/email_bodies
```

The tool will save a `.txt` copy of the body for every matched email. If the email only has HTML, the tool also creates a plain-text version internally.

## Email body filtering

You can require body text to contain specific words before the email is accepted:

```env
TARGET_BODY_CONTAINS=StockCode,Warehouse
```

All listed values must be found somewhere in the body.

## Email body scraping

Enable simple body scraping when an email contains useful lines such as product notices, stock lines, links, or key/value pairs.

```env
SCRAPE_BODY_CONTENT=true
BODY_LINE_CONTAINS=StockCode,Qty,Warehouse
BODY_KEY_VALUE_SEPARATOR=:
```

The scraped rows are written into the JSON audit log under each matched email:

```json
{
  "body": {
    "saved_text_path": "downloads/email_bodies/example.txt",
    "saved_html_path": null,
    "scraped_rows": [
      {"key": "StockCode", "value": "ABC123", "raw": "StockCode: ABC123"}
    ]
  }
}
```

If `BODY_LINE_CONTAINS` is blank, all non-empty body lines are captured. If the separator is present, the row is stored as `key`, `value`, and `raw`; otherwise it is stored as `raw` only.

## Output

Downloaded files go to `DOWNLOAD_DIR`.

Saved email bodies go to `BODY_OUTPUT_DIR`.

Audit logs go to `LOG_DIR` and include:

- matched emails
- downloaded attachments
- saved body paths
- scraped body rows
- counts for matched attachments, downloaded files, saved body files, and scraped rows

## State tracking & download policy

A SQLite state DB (`state/harvest.db`, auto-created from the committed
`state/schema.sql`, gitignored) records which emails were accessed, which files
were downloaded, and whether a download was later processed by the downstream
sync — for visibility of the latest source used.

Only the **latest** matching email is fetched (`DOWNLOAD_ONLY_LATEST=true`).
Behaviour for that latest email depends on its state:

- **unread** → download automatically.
- **already read** → confirm before downloading (interactive) / policy `ON_ALREADY_READ` (headless).
- **already processed** → confirm before reprocessing (interactive) / policy `ON_ALREADY_PROCESSED` (headless).

Interactivity is auto-detected: prompts appear only on a TTY. When run headless
(e.g. a scheduler/pipeline), the `ON_ALREADY_*` policies apply and prompts never
block. `--yes` forces confirmation on. Relevant env:

```env
ENABLE_STATE_DB=true
DOWNLOAD_ONLY_LATEST=true
ON_ALREADY_READ=proceed        # proceed | skip  (headless)
ON_ALREADY_PROCESSED=skip      # proceed | skip  (headless)
# HARVEST_DB_PATH=state/harvest.db
```

Commands:

```bash
python -m email_attachment_downloader              # harvest per the rules above
python -m email_attachment_downloader --status     # latest accessed email / download / processed
python -m email_attachment_downloader --mark-processed <path>   # called by the sync after a successful run
```

## Suggested use before Shopify sync

1. Run this downloader to fetch the supplier CSV into `downloads/supplier/latest`.
2. Point your Shopify supplier sync tool to that downloaded CSV directory or file.
3. After the sync succeeds, call `--mark-processed <file>` so the state DB records it as processed.
4. Keep the JSON audit log as evidence of which email and attachment produced the supplier feed.
#   m a i l - h a r v e s t 
 
 

