// STYLST B-roll weekly sync. Runs inside Google as founders@stylst.co. Adds ONE shortcut per photo/video to the library.
// Never moves, edits, deletes or re-shares originals. Duplicates are prevented by checking the library's existing shortcuts.
const LIBRARY = '1Xgo-G-cgH57hJ2VlLhcZhsHTJkvm3op9';
const UNSORTED = '1Gmta1ARn7X5VzXQIxPPfun9aFvbgCXn6';
const ALERT_TO = 'aspen@aspenbrookmedia.com';
const SOURCES = [ // [creator, folderId]  (add new contributors here)
  ['Amanda','1dgXB6h_qflBwa-F1QrxThVb9z3fq1crW'], ['Anna','1QIzofOYpN_TRGoC1tpwP33TlpjEsWEA3'],
  ['Cassidy','17GDxCPL_W2fL5vTaJ54v5QxQ7AwP1J2e'], ['Deanne','1ORsqTrvQncGw47vl0dLD1OMOMYWrKpeA'],
  ['Faith','1x2AP_NINaVG0lo84XfZg3aaVqcbtkuYL'], ['Grace','17ZvvatLgqef6Cm1H6tLJA7EJ0Zsi-ixI'],
  ['Kira','14ji4BXReQLD1et_1US3Y6AbKQXA_P5W8'], ['Marchel','1ZGgsIwogEUCj8-56gMiQ-kwkSpAI-kCT'],
  ['Marchel','1GVfYUfKSrNwn92tKZT8XBHm0jJmlbxP0'], ['Mya','1D0uiZQQSk7UC1RffCQc7LVLhst-xCg5W'],
  ['Shouq','1H_YTXfTH-auhgDnF_KikuJZMbx2_hjau']];
// Only footage someone has actually viewed. Everything else goes to 00 Unsorted Pile.
const KNOWN = {'1ITVvDxw3Bnc28ceuH9_C-WpLO9bkeVmC': {prefix: '03 Closet', title: 'Grace: cream sweater dress by Christmas tree (photo)'}};
const PILOT = [['Grace','1ITVvDxw3Bnc28ceuH9_C-WpLO9bkeVmC'], ['Marchel','1hoL3W4lIyh25fsBLZzmujAlMefZC-c62']];
const SKIP_FOLDER = /\b(meetings?|hr|legal|payroll|contracts?|invoices?|b-?roll library)\b/i;
const BUDGET_MS = 5 * 60 * 1000;

function runPilot() { return sync_(true); }       // run this first: only the two pilot files
function weeklySync() { return sync_(false); }    // the weekly job

function sync_(pilotOnly) {
  const t0 = Date.now(), log = [], problems = [];
  try {
    const idx = indexLibrary_();                  // targetId -> true, subject folders by name
    const files = pilotOnly ? PILOT.map(p => ({creator: p[0], id: p[1]})) : discover_(problems, t0);
    for (const f of files) {
      if (Date.now() - t0 > BUDGET_MS) { problems.push('Time budget reached; continuing in 10 minutes.'); scheduleContinue_(); break; }
      if (idx.targets[f.id]) continue;            // already in library (matched by original file ID, never by name)
      try {
        const file = DriveApp.getFileById(f.id), known = KNOWN[f.id];
        let dest = UNSORTED, title = f.creator + ': ' + file.getName() + ' (not visually reviewed)';
        if (known) {
          const m = Object.keys(idx.subjects).filter(n => n.toLowerCase().indexOf(known.prefix.toLowerCase()) === 0);
          if (m.length !== 1) throw new Error('subject folder not found: ' + known.prefix);
          dest = idx.subjects[m[0]]; title = known.title;
        }
        const sc = DriveApp.getFolderById(dest).createShortcut(f.id); sc.setName(title);
        if (sc.getTargetId() !== f.id) throw new Error('readback mismatch');
        idx.targets[f.id] = true; log.push([new Date(), f.creator, f.id, sc.getId(), dest, title, 'created', sc.getUrl()]);
      } catch (e) { problems.push(f.id + ': ' + e.message); log.push([new Date(), f.creator, f.id, '', '', '', 'error', e.message]); }
    }
  } catch (e) { problems.push('Run failed: ' + e.message); }
  writeLog_(log, problems, pilotOnly);
  if (problems.length) MailApp.sendEmail(ALERT_TO, 'B-roll sync needs attention',
    problems.slice(0, 20).join('\n') + '\n\nIt retries failed items next run. A sign-in problem needs you to re-authorize the script.');
  return {created: log.filter(r => r[6] === 'created').length, problems: problems.length};
}

function indexLibrary_() {
  const targets = {}, subjects = {}, stack = [LIBRARY];
  while (stack.length) {
    const folder = DriveApp.getFolderById(stack.pop());
    for (const it = folder.getFolders(); it.hasNext();) { const f = it.next(); if (folder.getId() === LIBRARY) subjects[f.getName()] = f.getId(); stack.push(f.getId()); }
    for (const it = folder.getFiles(); it.hasNext();) { const f = it.next(); if (f.getMimeType() === 'application/vnd.google-apps.shortcut') targets[f.getTargetId()] = true; }
  }
  return {targets, subjects};
}

function discover_(problems, t0) {
  const out = [];
  for (const [creator, root] of SOURCES) {
    const stack = [root];
    while (stack.length) {
      try {
        const folder = DriveApp.getFolderById(stack.pop());
        for (const it = folder.getFolders(); it.hasNext();) { const f = it.next(); if (!SKIP_FOLDER.test(f.getName())) stack.push(f.getId()); }
        for (const it = folder.getFiles(); it.hasNext();) { const f = it.next(), mt = f.getMimeType(); if (/^(image|video)\//.test(mt)) out.push({creator, id: f.getId()}); }
      } catch (e) { problems.push('Cannot read a ' + creator + ' folder: ' + e.message); }
    }
  }
  return out;
}

function writeLog_(rows, problems, pilot) {
  const props = PropertiesService.getScriptProperties();
  let id = props.getProperty('LOG_SHEET'), ss;
  try { ss = id ? SpreadsheetApp.openById(id) : null; } catch (e) { ss = null; }
  if (!ss) { ss = SpreadsheetApp.create('B-roll sync log (private)'); props.setProperty('LOG_SHEET', ss.getId()); ss.appendRow(['time','creator','original id','shortcut id','destination','title','result','link/error']); }
  const sh = ss.getSheets()[0];
  rows.forEach(r => sh.appendRow(r));
  sh.appendRow([new Date(), '', '', '', '', (pilot ? 'PILOT ' : 'WEEKLY ') + 'run finished', problems.length ? 'PARTIAL' : 'OK', problems.length + ' problems']);
}

function scheduleContinue_() { ScriptApp.newTrigger('weeklySync').timeBased().after(10 * 60 * 1000).create(); }

function installWeeklyTrigger() { // run once. Sunday ~8 AM in the project's time zone (set to America/Los_Angeles).
  ScriptApp.getProjectTriggers().filter(t => t.getHandlerFunction() === 'weeklySync' && t.getEventType() === ScriptApp.EventType.CLOCK).forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('weeklySync').timeBased().onWeekDay(ScriptApp.WeekDay.SUNDAY).atHour(8).create();
}
