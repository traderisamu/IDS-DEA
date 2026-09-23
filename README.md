# IDS PH - Daily Employee Accomplishment (DEA) Logger

A Windows desktop app for the team to log daily JOB Code / Work
Description / Hours / Details / Remarks. It runs quietly in the system
tray with automatic end-of-day reminder pop-ups, a personal calendar
view, Holiday/Leave marking, and an Admin dashboard with a visual
all-employee calendar.

---

## 1. What's in this package

```
dea_app/
├── DEA_Config.xlsx          <- EDIT THIS to change the Work Description/
│                               Tooltip list, the employee roster, reminder
│                               times, hour thresholds, and the admin login.
├── generate_config.py       <- Only needed once, to (re)build DEA_Config.xlsx
│                               from scratch. You will normally just edit the
│                               .xlsx directly in Excel instead of re-running this.
├── generate_icon.py          <- Only needed if you want to regenerate/redesign
│                               assets/icon.ico (requires `pip install pillow`).
├── assets/icon.ico           <- App/taskbar/shortcut icon, already built.
├── dea_logger_entry.py      <- App entry point (used by the build script)
├── build.bat            <- Run on a Windows PC to build the .exe
│                               (creates a dist\ subfolder here with the exe in it)
├── install.bat               <- Run on each employee's PC to install - stays
│                               right here, reads the exe from dist\ automatically
├── uninstall.bat             <- Run on an employee's PC to remove it
├── requirements.txt
├── client/                   <- App source (GUI, calendar, admin dashboard,
│                               system tray icon, desktop shortcut self-heal)
└── shared/                   <- App source (config loading, Excel data storage)
```

## 2. One-time server setup

The shared network folder itself just needs to exist and be reachable
from everyone's PC (mapped drive or direct UNC access) - you don't need
to manually copy `DEA_Config.xlsx` there yourself. **`install.bat`
does that automatically**, the first time it runs on ANY employee's PC
(see section 4) - and only if a config file isn't already sitting there,
so it can never accidentally overwrite one that's already in use. If
you'd rather set it up yourself ahead of time anyway, or on a PC that
never ends up running install.bat, copy `DEA_Config.xlsx` to:
```
\\EgnyteDrive\idsinc\Shared\Engineering\ENGG PHL\REPORTS\16 Manhour Report LEADERBOARD\DEA App
```
This exact path is already baked in as the app's default, so nobody needs
to type it in. If you ever move it, see section 8.

That's it beyond that — the app creates a `Logs` subfolder there
automatically the first time anyone logs an entry, and creates one
Excel file per employee inside it (e.g. `Logs\Jay Benedict Cabrera.xlsx`).

## 3. Build the .exe (do this once, on any Windows PC with Python)

This can't be cross-built from a Mac/Linux machine — PyInstaller builds for
whatever OS it runs on, so it must run on Windows.

1. Install Python 3.9+ from python.org if not already installed (check
   "Add python.exe to PATH" during setup).
2. Double-click **`build.bat`**.
3. When it finishes, your exe is at `dist\IDS_DEA_Logger.exe`, next to a
   matching `dist\version.txt` release tag.

This build takes noticeably longer than it used to, and the resulting
.exe is a fair bit larger - the My Dashboard tab's charts need
matplotlib, which is a large dependency. Worth expecting a few minutes
for this step rather than a few seconds.

### Rollout notes (handing a build to the team)

The shared handout folder (e.g. `...\Engg Software\DEA`) needs only:
`install.bat` + `IDS_DEA_Logger.exe` (flat, or inside `dist\`) +
`uninstall.bat` + `version.txt`. Optional: `admin_links.json` (offline
fallback) and `DEA_Config.xlsx` (first-install seed only).

`version.txt` is what drives the app's silent auto-update: every launch
compares it against the running build and, when the staged one is newer,
downloads it, swaps it in on restart (keeping one `.bak`), and relaunches
- no prompts, no `install.bat` needed for updates. Deleting or editing
`version.txt` just disables auto-update; the app keeps running.

## 4. Install on each team member's PC

Since you chose the **desktop-EXE reminder** option (real Windows pop-ups,
not just an in-browser banner), a small app does need to run on each PC —
there's no way around that for genuine OS-level pop-ups. The install itself
is lightweight though: no admin rights, no system-wide install, just a
per-user copy + shortcut.

1. **`install.bat` stays right where it is, in the project folder** -
   next to `build.bat`, `DEA_Config.xlsx`, and the `dist\` folder
   that step 3 created. There's no need to copy it into `dist\` or move
   the exe out of `dist\`; the script finds `dist\IDS_DEA_Logger.exe`
   on its own. (If you'd rather hand out a lean package with just the
   exe and this script, that still works too - it checks its own
   folder as a fallback if `dist\` isn't there.)
2. On each PC, run **`install.bat` from a Command Prompt window** (not
   just by double-clicking, so you can read the OK/WARNING lines it
   prints) from that folder. It will:
   - Copy the exe to `%LOCALAPPDATA%\IDS_DEA_Logger\`
   - **Copy `DEA_Config.xlsx` to the shared network drive - but only the
     very first time, on whichever PC happens to run this script first.**
     If a config file is already sitting there (the normal case after
     the first install), this step is skipped entirely, so a later
     install never overwrites an admin's live edits to it. If the
     shared drive can't be reached at all, it warns and skips rather
     than failing the rest of the install.
   - Register auto-start via the registry Run key, using plain `reg.exe`
     (not a scripting engine, so this works even in locked-down
     environments that disable VBScript/PowerShell)
   - Create a Desktop shortcut with the custom icon, at whatever folder
     Windows actually resolves as "Desktop" for that user (this is
     PowerShell/redirection-aware, so it lands in the right place even on
     PCs where OneDrive has moved the Desktop elsewhere); if Windows
     Script Host and PowerShell are both blocked, it falls back to a
     plain `.bat` launcher instead (no custom icon, but guaranteed to work)
   - Prints a clear OK/WARNING for each step
3. **The app also self-registers auto-start AND recreates its own Desktop
   shortcut every time it's opened** (`client/autostart.py` and
   `client/shortcuts.py`), independent of install.bat. So even on a PC
   where the install script's steps somehow didn't take, opening the app
   once fixes it going forward - install.bat only needs to run once, if
   at all.
4. **The app starts quietly in the system tray - it does not pop a
   window open.** Look for its icon near the clock. Click it (or right-
   click for the menu) to open the logger, jump to the Admin Dashboard,
   or exit. The one exception is the very first time it runs on a PC: it
   shows itself so the employee can pick their name from a dropdown
   (pulled from `DEA_Config.xlsx`). That name is remembered after that -
   it shows locked in **red** at the top of every screen so they can't
   accidentally log time under a teammate's name. A **"Not you? Reset"**
   link is available if a PC genuinely needs to be handed to someone
   else, but clicking it doesn't reset anything by itself anymore - it
   prompts for the **admin username and password** first, and only
   clears the saved name once an admin approves. This keeps someone from
   accidentally (or deliberately) knocking their own name loose and
   logging under someone else's identity.
   - If that name-picker gets closed without a name being picked
     (nothing selected, just closed), the app **doesn't force-quit** -
     it goes right on running quietly in the tray (no window forced
     open, same as normal) with a simple "no name selected yet" screen
     and a **Select Your Name** button available whenever it is opened.
     It reminds them starting at **9:00 AM** (same slot as the other
     reminders), then **every hour after that until 4:30 PM**, until a
     name is actually picked - after 4:30 PM it stops nagging for the
     rest of the day rather than going on indefinitely. Nothing can be
     logged until a name is picked, since every log file is
     per-employee.
   - Once a name is picked, the app checks that person's **PIN**, which
     is simply their **employee number** (the trailing number of their
     Employee ID in the `Employees` sheet of `DEA_Config.xlsx` - e.g.
     Employee ID `06-2010-526` -> PIN `526`). There is no separate PIN
     storage, and **employees cannot set, change, or clear their own
     PIN** - there's no button for it anywhere in the main window. The
     only way to change or remove someone's PIN is for the admin to
     edit their Employee ID in that sheet (see section 6). This is
     screen privacy, not a security system - if a PIN exists for that
     person, the app asks for it once, right at startup, before showing
     anything, then trusts the rest of that session. If someone has no
     Employee ID (or it doesn't end in a number) in the sheet, the app
     simply never locks for them. The unlock screen's own "forgot PIN"
     hint just says "It's your employee number" - no self-service reset,
     and no pointer back to the config file for an employee to go dig
     through.
5. Closing the window (the X button) just sends it back to the tray -
   it keeps running so reminders still fire. Use **Exit** in the tray
   icon's right-click menu to actually quit it.

To remove it later, run `uninstall.bat` on that PC.

### If the app still doesn't seem to be running

- Look for the tray icon first (it may be tucked under the "^" overflow
  arrow next to the clock) - that's the normal, correct state, not a bug.
- Confirm auto-start: open Task Manager -> **Startup apps** tab and look
  for "IDS_DEA_Logger". If it's there, reminders will fire even if the
  person never manually opens the app that day.
- As an absolute last resort, you can always run the app directly from
  `%LOCALAPPDATA%\IDS_DEA_Logger\IDS_DEA_Logger.exe` or pin that file to
  the taskbar manually.

## 5. Using the app

**Log Today's Work tab** — enter a JOB code and Details. Both fields are
still free-typeable, and **suggest that same person's own previously used
values as you type** in a small dropdown list underneath the box - it
just shows suggestions, it never auto-fills or grabs your cursor while
you're typing; click a suggestion (or highlight one with the arrow keys
and press Enter) to use it. Details suggestions are scoped to **both**
the currently-entered JOB Code **and** the selected Work Description -
a reference like `SC01` logged under one JOB Code won't show up as a
suggestion under a different JOB Code, even for the same Work
Description, since that's usually a different context entirely (and
the last thing you want is accidentally pasting the wrong reference
onto the wrong job). Pick Work Description from the dropdown, enter
Hours, and Remarks, then **Add Entry**.

- **A few Work Descriptions only show up for certain JOB codes.** As
  soon as a JOB Code is typed, the Work Description dropdown filters
  itself down live (matched against everything before the first `-` in
  the JOB Code, so `ASPM-CUB` counts as `ASPM`):
  - `*Meeting` is **the only option shown** when the JOB Code starts
    with `ASPM` or `AMGM` - every other Work Description, including the
    normally-always-available ones, is hidden for those JOB codes.
  - `*Training` is likewise **the only option shown** for `ASPT`.
  - `*Reading References` is **added on top of** the normal full list
    for `ENGG` or `AESG` - it doesn't hide anything else, since those
    are the everyday engineering JOB codes.
  This is configured in the `Work Items` sheet's "Restricted To JOB
  Codes" and "Exclusive" columns, not the code - see section 7. If a
  JOB Code is changed after a restricted Work Description was already
  picked and it no longer qualifies, the Work Description selection is
  cleared rather than silently left pointing at something now hidden.

- **« Week / ‹ Day / Today / Day › / Week »** sit right next to the Date
  field, so jumping to yesterday, last week, or back to today doesn't
  need a trip to the My Calendar tab. You can still type a date directly
  into the box too - the day of the week (e.g. "Friday") shows right
  underneath it as a sanity check.
- **Press `Alt+Escape` from anywhere** (any program, any time) to
  toggle this window - opens it if it's hidden/minimized, sends it back
  to the tray if it's already open, so the same shortcut does both.
  Even works while it's sitting quietly in the tray with no window
  visible. This is a genuine system-wide hotkey (the same mechanism
  Windows itself uses for things like Win+L) - just two keys held
  together. Note that Alt+Escape is also a longstanding Windows shortcut
  on its own (cycles to the next window, similar to Alt+Tab) - while this
  app is running, it claims that combo for itself instead, so Windows'
  own window-cycling behavior won't fire. If that combo happens to
  already be claimed by something else that got there first on a
  particular PC, this silently does nothing (the tray icon still works
  as a fallback either way).

- **If the selected Work Description has a Details tooltip/hint
  configured** (see `Work Items` sheet below), **Details becomes
  required** for that entry - you'll be blocked from saving until you
  fill it in. Work Descriptions with no hint configured don't require
  Details. **If that hint contains a `#`** (e.g. `# of joints`), Details
  is further restricted to numbers only - the field simply won't accept
  letters while that Work Description is selected.
- **Delete Selected Entry** sits right beside **Add Entry**. Select a row
  and click it, or just press **Delete** (or Backspace) on a selected
  row - same effect either way. Either way, a brief **"Entry deleted -
  Undo"** bar appears for a few seconds afterward in case it was a
  misclick - click **Undo** to put it right back, or just ignore it and
  it fades away on its own.
- **Hours over 24 for a single entry are rejected outright** (a day only
  has 24 hours - almost certainly a typo, like an extra digit or a
  misplaced decimal point). **Hours over 12 for a single entry** ask for
  a quick "are you sure?" confirmation instead of blocking outright,
  since that's unusual but not impossible.
- If total hours logged for that day goes **over 8**, a warning pops up
  after saving.
- A day only turns **green** on the calendar once total hours are **4+**
  - and the calendar updates immediately as you add/edit/delete entries.
- **"Mark this date as Holiday / Leave"** removes the requirement to log
  anything that day — it shows blue on the calendar instead of red.
  **"Clear Holiday/Leave mark"** sits right below it, in case you marked
  the wrong date.
- The bottom-right corner always shows a running **Total** for whichever
  date is selected, a **This week** running total below that, and a
  small **"7:30 AM start + lunch (12-1) → out at ..."** line underneath -
  a quick illustrative gut-check for what a clock-out time would look
  like for that many hours, assuming a 7:30 AM start and the standard
  12:00-1:00 PM lunch break. None of this is tied to any actual
  login/logout tracking - just arithmetic on the hours logged, updated
  live as entries are added, edited, or deleted. A tiny, easy-to-miss-
  on-purpose **"(customize)"** link sits right next to that line, for
  anyone whose actual schedule genuinely isn't 7:30/12-1 - it opens a
  small dialog to set their own Time In / Lunch Out / Lunch In (e.g.
  `8:00 AM`), with a **Reset to Default** button to go back. This only
  changes that one illustrative note - it doesn't touch how hours are
  logged, totaled, or reported anywhere else - and it's local to that
  PC, not synced via the shared drive, so it quietly reverts to the
  7:30/12-1 default on any other PC. The app's default window size is
  tall enough to show all of this without resizing.

**🟢 Job Navigator tab** (2nd tab) — job folder shortcuts, quick links,
and a file link generator (drop files to get share-ready UNC links).

**My Calendar & Dashboard tab** — one scrolling page: month view of your
own logging history on top (click any day to jump back to that date's
entries), with the personal efficiency view below, built to help each
person understand their own work pattern, not to be watched by anyone
else:
- **Where my time goes** — two bar charts, hours by Work Description and
  hours by JOB Code, for whichever period is selected.
- **Efficiency (per unit of output)** — three per-unit numbers:
  - **Calc Creation** (**hours** per calc) — hours per distinct calc name
    logged under "Create Calculation Template" (the Details column
    holds the calc name, so entries reusing the same name count as one
    calc, not one per entry).
  - **Run** (**minutes** per joint) — minutes per joint logged under "Run
    Calculation Joints" (the leading number in the Details column is
    read as the joint count for that entry).
  - **Review Shop Drawing** (**minutes** per sheet) — minutes per sheet
    logged under "Review Shop & Erection Dwgs" (same idea, leading
    number in Details is the sheet count).
  Run and Review are shown in minutes rather than hours since a single
  joint or sheet is usually a small fraction of an hour (0.07 hrs reads
  far less clearly than the equivalent 4.2 min); Calc Creation stays in
  hours since a full calc plausibly takes an hour or more. An entry
  that's missing the expected Details value (blank, or no number where
  one's expected) is simply left out of that metric rather than counted
  as a free zero-unit hour that would skew the average. Shows "No data"
  instead of a misleading 0.00 when there's nothing to compute from for
  the selected period. **These three depend on the exact "Work
  Description" text in the `Work Items` sheet matching what the code
  expects** (see `WORK_DESC_CALC_CREATION` / `WORK_DESC_CALC_RUN` /
  `WORK_DESC_SHOP_REVIEW` in `shared/data_store.py`) - renaming one of
  those three rows in `DEA_Config.xlsx` without updating the matching
  constant just makes that one metric show "No data", nothing breaks.

A period selector (This Week / This Month / Last Month / Last 3 Months)
controls all of these together, defaulting to This Month. This tab is
built lazily the first time it's opened (not at every app startup),
since the charting library it uses takes a moment to load - opening the
tab for the first time in a session may have a brief pause before the
charts appear. Admins get the same breakdown/efficiency view for ANY
employee, with a free-form custom date range instead of a fixed period
list, from the Admin Dashboard's **"Efficiency Dashboard..."** - see
section 6.

**Cutoff Summary** — the **"Cutoff Summary..."** button in the header
(next to "Not you? Reset") builds a Day/Date/Total/per-JOB-code table
for one payroll cutoff period, laid out to make manual entry into the
company's Online Timesheet Portal faster - a row can be read straight
off and typed in. This is what it's for, not a replacement for the
portal itself, and it does **not** try to reproduce the portal's own
actual clock-in/out times (this app has no way of knowing those).
- **Cutoff periods** are always the 23rd of one month through the 7th of
  the next, or the 8th through the 22nd of the same month - the
  dropdown defaults to whichever one contains today, with a few
  neighboring periods also selectable.
- **JOB code columns** — one column per JOB code that has at least one
  hour logged SOMEWHERE in the selected period, sorted alphabetically
  left to right. A code nobody touched that period just isn't shown, so
  the table doesn't fill up with all-blank columns.
- Each day shows its **Total** hours and hours **per JOB code** column -
  blank (not 0) when a day didn't touch that code, so the table reads
  cleanly; Total itself always shows a number, including 0.
- **Export to Excel/CSV...** saves the currently-shown period to a file
  in the same layout, for printing or for reference while filling out
  the portal by hand.
- Admins get the same dialog from the Admin Dashboard (**"Cutoff
  Summary..."**), with an employee picker added so they can pull
  anyone's summary without needing to be signed in as them.

**Reminder pop-ups** — governed by `ReminderTimes` in `DEA_Config.xlsx`
(comma-separated `HH:MM`, earliest first; default **09:00,15:00**), but
the earliest and later times mean different things:
- The **earliest time (9:00 AM by default)** checks whether the
  **previous work day's** log was completed:
  - **Under 4h logged** → pops up **once** to say it's incomplete - it
    does not repeat, so it won't nag you all morning about yesterday.
  - **4h up to (not including) 8h logged** → technically clears the
    green threshold, but well under a full day, so rather than silently
    assuming it's done, it **asks**: "Is that log actually complete?"
    Answer **Yes** and nothing more happens. Answer **No** and it's not
    nagged about separately - instead it gets folded into **today's**
    3 PM+ reminder (see below), so it shows up as part of that
    notification rather than a second, separate one.
  - **8h or more logged** → treated as obviously complete, no question asked.
- **Every time after that (3:00 PM by default)** checks **today's** log.
  Once the last of those times has passed and today still isn't
  complete, it keeps re-nagging every **`ReminderRepeatMinutes`**
  (default and floor: **30 minutes**) - but only for
  **`ReminderRepeatCutoffMinutes`** (default: **90 minutes**) after that
  last time. With the defaults that's popups at **3:00, 3:30, 4:00 and
  4:30**, then **nothing more that day**, even if it's still incomplete -
  it stops nagging rather than going on indefinitely. If a previous day
  was flagged "not actually complete" (see above), that note rides
  along with whichever of these fires first - even if today's own log
  is already complete and nothing would otherwise have popped up - and
  is only mentioned once, not repeated at every 30-minute interval.

A single 1-hour entry doesn't silence either check - it's the 4-hour
green threshold that counts as "done" for the day being checked.

**If no name has been picked yet on that PC**, none of the above applies
- there's nothing to check logs for. Instead, starting at that same
earliest slot (9:00 AM by default), it reminds them to open the name
picker every hour until 4:30 PM, then stops for the day. See the note
in section 4 above.

## 6. Admin access (you only)

Both the main window and the Admin Dashboard show a version number
(e.g. `v1.4.0`) in their title bars. Since this app is rebuilt and
handed out manually rather than auto-updating, that's the way to tell
at a glance which PCs are still on an older build if a fix goes out -
bump `APP_VERSION` in `shared/constants.py` with each rebuild.

Click **"Admin Login"** in the top right of the app. Login:
- Username: `admin`
- Password: `nimda`

**Change this password** by editing the `AdminPassword` row in the
`App Settings` sheet of `DEA_Config.xlsx` — it's read live, no rebuild
needed.

Admin Dashboard has:
- **All-Employee Calendar** — a color-coded grid, one row per employee
  grouped by team, one column per day of the month. Green/orange/blue/
  red/gray at a glance tells you who's logging consistently - today's
  column doubles as the "who's missing today" view, so there's no
  separate list to check. Click any cell to see that person's entries
  for that day. A summary line above it shows **teams ranked by average
  hours logged this month** (busiest first - total hours / number of
  employees on that team), and right below that, a **"Most hours logged
  this month"** line flags whichever single employee has logged the
  most hours and the busiest team - a quick flag for who or what might
  be overworked, worth a closer look.
  - If someone who's actively logging still shows up red/missing for a
    day they clearly worked, it's almost always because their name in
    the `Employees` sheet was edited (typo fix, spacing, capitalization)
    *after* they'd already started logging under the original spelling -
    their PC remembers the name they first picked and never asks again.
    A pure case/whitespace difference is reconciled automatically.
    Anything more than that (an actual name change, not just formatting)
    needs that person to clear
    `%APPDATA%\IDS_DEA_Logger\dea_app_settings.json` and reopen the app
    so it prompts them to pick their (now-corrected) name again - their
    existing log history stays intact either way, since it's keyed by
    file name on disk, not by anything in that settings file.
  - If the shared drive itself is unreachable (a dropped VPN/network
    connection) when the grid tries to load, it shows a clear "Can't
    reach the shared drive" message instead of rendering a misleading
    all-red/all-missing grid that never actually happened.
- **Open Database Folder** — jumps straight to the `Logs` folder (admin
  only — this button doesn't appear for regular employees).
- **Open Config File** — opens `DEA_Config.xlsx` directly (in Excel, or
  whatever's set as the default handler) so you can edit the dropdown
  lists, roster, or settings below without hunting for the file yourself.
- **Refresh Config** — reloads `DEA_Config.xlsx` and shows a real summary
  ("Loaded 28 employees, 12 work items") plus a heads-up for common
  mistakes worth double-checking (an empty roster, two employees with
  the exact same name, someone with no Team assigned). If the file
  itself is broken (a required sheet got deleted, for instance) this
  shows a clear error instead of silently leaving the dashboard showing
  stale data. **This also immediately updates the main window** (the
  Work Description dropdown, its Details hints) - previously a config
  edit only showed up in the main window after fully closing and
  reopening the app; now Refresh Config alone is enough.
- **Export Month...** — exports whichever month the calendar grid is
  currently showing, across **every** employee, to a single `.xlsx` or
  `.csv` file (pick the format via the extension in the save dialog).
  Includes each logged entry plus any Holiday/Leave marks for that
  month. Handy for payroll or reporting without opening each employee's
  file individually.
- **Rankings...** — opens the full busyness ranking for whichever month
  the calendar grid is showing: every team ranked by average hours per
  employee, and every individual ranked by total hours logged, not just
  the single top pick shown inline above the grid.
- **Version chips** — every employee row shows the app version green
  (`v2.0.0`) when they're on your build, amber (`v1.x.x`) when outdated,
  gray (`--`) when they've never launched a version-reporting build.
  Versions come from tiny heartbeat files each app writes to
  `Logs\.versions\` at startup - don't delete that folder. Anyone showing
  `--` or amber after a rollout is who still needs the new installer.
- **View Employee PINs...** — a read-only lookup of every employee's
  current PIN, so you don't have to go hunt through the spreadsheet to
  answer "what's so-and-so's PIN" or "why isn't the app locking for
  them". There's nothing to set or clear from the Admin Dashboard: a
  PIN is just the trailing number of that person's **Employee ID** in
  the `Employees` sheet of `DEA_Config.xlsx` (e.g. Employee ID
  `06-2010-526` -> PIN `526`). **To set, change, or remove someone's
  PIN, edit their Employee ID in that sheet directly** and hit
  **Refresh Config** (or restart the app) - there is no other way to
  do it, on purpose: employees have no self-service PIN option, and
  neither does the dashboard. Leaving the Employee ID blank for
  someone means the app simply never locks for them.
- **Cutoff Summary...** — same dialog described in section 5, with an
  employee picker added so an admin can view or export anyone's
  payroll-cutoff summary directly, without switching PCs or being
  signed in as them.
- **Efficiency Dashboard...** — the same breakdown-by-Work-Description /
  breakdown-by-JOB-code / per-unit-efficiency view as My Dashboard (see
  section 5), but with an employee picker AND a free-form "From" / "To"
  date range (type any `YYYY-MM-DD` dates, or use one of the Quick
  Range buttons) instead of a fixed period list - for checking any
  custom stretch of time on demand, not just this/last month.

## 7. Editing the dropdown lists / roster / settings

Everything the app treats as "hardcoded" data lives in `DEA_Config.xlsx`,
never in the code:

| Sheet | Controls |
|---|---|
| `Work Items` | The Work Description dropdown, its Details tooltip, and (optionally) which JOB code prefixes it's restricted/exclusive to |
| `Employees` | Who shows up in the name-picker, their Team, and their Employee ID (the trailing number of which is that person's PIN - see section 6) |
| `App Settings` | Reminder times, hour thresholds, admin login, company name |

Just edit the Excel file and save — the app re-reads it automatically
(cached ~3 minutes) or you can restart the app for an instant refresh.
Note: **JOB Code is a free-text field**, matching how your current
spreadsheet works (it isn't a fixed dropdown list in your source file) -
it auto-suggests each employee's own previously-used codes from their
personal history, rather than a shared company-wide list.

**Restricting a Work Description to certain JOB codes:** fill in the
`Work Items` sheet's 3rd column with a comma-separated list of JOB code
prefixes (the part before the first `-`, e.g. `ASPM` out of
`ASPM-CUB`) - that item then only shows up in the dropdown once a JOB
Code starting with one of those prefixes is typed. Leave it blank for
an item that should always be available.

**Making a restriction exclusive:** set the 4th column ("Exclusive") to
`Yes` for a restricted item, and for its listed prefixes it becomes the
**only** Work Description shown - every normally-always-available item
gets hidden too for that JOB code, not just other restricted ones. Use
this for a JOB code dedicated to one specific activity (a meeting- or
training-only code, say) that shouldn't be usable for anything else.
Leave the 4th column blank for a restriction that should just ADD an
option on top of the normal list instead of replacing it.

Out of the box: `*Meeting` → `ASPM, AMGM`, Exclusive `Yes` (only
`*Meeting` shows for those codes); `*Training` → `ASPT`, Exclusive
`Yes` (same idea); `*Reading References` → `ENGG, AESG`, Exclusive left
blank (added on top of the full list, since those are everyday
engineering codes that still need everything else too).

A leading `*` or `~` in the Description itself is purely a visual
grouping cue - it does nothing on its own; the restriction/exclusivity
behavior only comes from the 3rd/4th columns. The sheet lists plain
(unmarked) items first, then `*`/`~`-marked ones at the end - that's
just the row order in the sheet, so re-sort it however you like.

## 8. If the shared path ever changes

The app accepts either a UNC path (`\\Server\Share\Folder`) or a mapped
drive letter (`Z:\Folder`), and normalizes whatever you paste in — forward
slashes, trailing slashes, or stray quotes from a copy-paste all get
cleaned up automatically.

**Finding the config file at startup:** the app checks, in order: the
folder it found the config in last time (remembered per-PC), the default
network path baked into the app, then the folder it's actually running
from (so a simpler "copy the exe and `DEA_Config.xlsx` into one local
folder" deployment works too, with nothing to configure). Each location
gets a couple of quick retries with a short pause before moving on -
this specifically covers the case where the app auto-starts at Windows
login before a mapped/network drive has finished mounting, which used to
show a "config not found" error even though the path was correct and
would have worked a second later.

If `\\EgnyteDrive\...` genuinely moves and none of the above finds it,
the employee will be prompted once for the new path — or you can
proactively have them clear `%APPDATA%\IDS_DEA_Logger\dea_app_settings.json`
and it'll re-resolve from scratch on next launch.

## 9. App icon

`assets/icon.ico` is embedded into the .exe itself (so Explorer, the
taskbar, and Alt-Tab all show it) and set as the window icon for every
screen in the app, including the Admin Dashboard. To change it, edit and
re-run `generate_icon.py` (needs `pip install pillow`), then rebuild with
`build.bat`.

## 10. Data & privacy notes

- Each employee's log lives in **their own Excel file** on the shared
  drive — nobody's app lets them browse into or edit anyone else's file.
- The Admin Dashboard is the only place that reads across everyone's files
  at once, and it's protected by the admin login above.
- **The PIN** (see section 4) isn't a separately stored secret at all -
  it's read straight out of `DEA_Config.xlsx` (the trailing number of
  that person's Employee ID), the same file everyone already needs read
  access to just to run the app. Worth being honest about what this is:
  it's screen privacy (stopping a coworker from casually opening an
  already-running app on someone else's unlocked PC), not a security
  boundary - anyone with read access to the shared drive, or Excel open
  on the config file, can already see every PIN directly.
- **My Dashboard** only ever shows the signed-in person's own numbers -
  never another individual's name or hours. There's no way to use it to
  look up a specific coworker.

## 11. Reliability notes

- **Saves are atomic.** Every write (a log entry, a Holiday/Leave mark, a
  month export) is written to a temp file first, then swapped into place
  in one step. A save that gets interrupted partway through - a dropped
  network connection, the app being closed at the wrong moment - can
  never leave a half-written, corrupted file behind; the original is
  only ever replaced by a fully-written new one.
- **If someone's file is open in Excel** when a save is attempted (an
  admin poking around, or the employee double-clicking their own file
  out of curiosity), the app shows a plain "please close it and try
  again" message instead of an error dialog full of jargon or a silent
  failure.
- **A quiet troubleshooting log** at `%APPDATA%\IDS_DEA_Logger\app.log`
  records anything that fails behind the scenes (a reminder check that
  hit a snag, a config file that couldn't be found at startup). Nothing
  in it is ever shown to the user - it's purely there for whoever needs
  to troubleshoot a recurring problem later, and it rotates automatically
  so it never grows unbounded.
- **A disconnected shared drive is told apart from genuinely no data.**
  If the network drive drops mid-session (VPN blip, etc.), reading logs,
  refreshing the calendar, and the reminder checks all recognize that the
  shared root itself is unreachable and say so clearly - rather than
  quietly showing an empty day/grid that looks like data vanished, or
  falsely nagging that nothing's been logged.
- **Deletes have a brief undo.** A short "Entry deleted - Undo" bar
  appears for a few seconds after deleting an entry, as a safety net
  against a misclick, before it fades away.
