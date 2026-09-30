/**
 * mail-harvest web app (Google Apps Script) - read-only Gmail over HTTPS.
 *
 * Lets mail-harvest (EMAIL_PROVIDER=gmail_webapp) read this Gmail account from
 * places where IMAP (port 993) is blocked, without a Google Cloud project.
 *
 * Setup (once, signed in to the Gmail account to read):
 *   1. https://script.google.com -> New project -> replace the code with this file.
 *   2. Edit ALLOWED_SENDERS below if needed.
 *   3. Deploy -> New deployment -> type "Web app"; Execute as: Me;
 *      Who has access: Anyone -> Deploy -> Authorize access (choose the account;
 *      on "Google hasn't verified this app" click Advanced -> Go to ... -> Allow).
 *   4. Copy the Web app URL (https://script.google.com/macros/s/.../exec) and set
 *      GMAIL_WEBAPP_URL to it. Treat the URL like a password.
 *
 * Every search is restricted to ALLOWED_SENDERS, so the URL can only ever read
 * those senders' emails. The script never changes, sends or deletes mail.
 */
var ALLOWED_SENDERS = [
  'sales@leadersystems.com.au',
  'ebay.com',
  'ebay.com.au'
];

function allowedClause_() {
  return '{' + ALLOWED_SENDERS.map(function (s) { return 'from:' + s; }).join(' ') + '}';
}

function isAllowed_(message) {
  var from = String(message.getFrom() || '').toLowerCase();
  return ALLOWED_SENDERS.some(function (s) { return from.indexOf(String(s).toLowerCase()) >= 0; });
}

function json_(value) {
  return ContentService.createTextOutput(JSON.stringify(value)).setMimeType(ContentService.MimeType.JSON);
}

function doGet(e) {
  var p = (e && e.parameter) || {};
  var action = p.action || 'ping';
  try {
    if (action === 'ping') {
      return json_({ ok: true, account: Session.getEffectiveUser().getEmail(), allowed: ALLOWED_SENDERS });
    }
    if (action === 'search') {
      var query = allowedClause_() + ' ' + (p.q || '');
      var max = Math.min(parseInt(p.max || '50', 10) || 50, 200);
      var ids = [];
      GmailApp.search(query, 0, max).forEach(function (thread) {
        thread.getMessages().forEach(function (m) {
          if (isAllowed_(m)) ids.push({ id: m.getId(), date: m.getDate().getTime(), unread: m.isUnread() });
        });
      });
      ids.sort(function (a, b) { return b.date - a.date; });   // newest first
      return json_({ ok: true, query: query, messages: ids });
    }
    if (action === 'raw' || action === 'headers') {
      var message = GmailApp.getMessageById(p.id);
      if (!message || !isAllowed_(message)) return json_({ ok: false, error: 'not found' });
      var raw = message.getRawContent();
      if (action === 'headers') {
        var end = raw.search(/\r?\n\r?\n/);
        raw = end >= 0 ? raw.substring(0, end) + '\r\n\r\n' : raw;
      }
      return ContentService.createTextOutput(raw).setMimeType(ContentService.MimeType.TEXT);
    }
    return json_({ ok: false, error: 'unknown action' });
  } catch (err) {
    return json_({ ok: false, error: String(err) });
  }
}
