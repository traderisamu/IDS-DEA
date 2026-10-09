"""
Central constants for the IDS PH DEA Logger.
"""
import datetime as dt

COMPANY_NAME = "IDS PH"
APP_TITLE = "IDS PH - Daily Employee Accomplishment (DEA) Logger"
# Bump this with every rebuild that goes out to the team. Since the app
# is manually rebuilt and redistributed rather than auto-updating, this
# is the only way to tell at a glance (main window title bar + Admin
# Dashboard) which PCs are still running an old build if a fix goes out.
APP_VERSION = "2.6.19"

# Default network location of the config file + Logs folder.
# Can be overridden per-machine via the local settings file
# (see client/local_settings.py) without touching this source file.
DEFAULT_SHARED_PATH = (
    r"\\EgnyteDrive\idsinc\Shared\Engineering\ENGG PHL\REPORTS"
    r"\16 Manhour Report LEADERBOARD\DEA App"
)

CONFIG_FILENAME = "DEA_Config.xlsx"
LOGS_SUBFOLDER = "Logs"

# File-open password for DEA_Config.xlsx (Excel "Encrypt with Password").
# Casual-deterrent only: it stops curious double-click browsing of the
# shared config, but anyone with this private repo (or the built exe) can
# read it straight out of here. Rotation = set the new password on the
# workbook in Excel, update this constant, rebuild, redeploy - and always
# ship the matching app BEFORE encrypting, since older builds cannot
# decrypt at all.
CONFIG_FILE_PASSWORD = "nimda"

# Silent auto-update source: the shared folder where staged releases live
# (IDS_DEA_Logger.exe + version.txt, copied there at rollout time - see
# README's rollout notes). The app compares version.txt against its own
# APP_VERSION at startup and self-updates when the staged one is newer.
UPDATE_DIST_FOLDER = (
    r"\\EgnyteDrive\idsinc\Shared\Engineering\ENGG PHL\STANDARD PROCEDURES & FILES"
    r"\Engg Software\DEA"
)
UPDATE_EXE_FILENAME = "IDS_DEA_Logger.exe"
UPDATE_VERSION_FILENAME = "version.txt"

# Local (per-PC) settings file - remembers which employee this PC belongs
# to, and the resolved shared path, so the user is never asked twice.
LOCAL_APP_FOLDER_NAME = "IDS_DEA_Logger"
LOCAL_SETTINGS_FILENAME = "dea_app_settings.json"

# Standard-schedule defaults for the illustrative "start + lunch -> out at"
# indicator on the Log Today's Work tab (see client/main_app.py). A 7:30 AM
# start with a 12:00-1:00 PM lunch and 8h of logged work lands at 4:30 PM,
# so the default log-out matches that.
DEFAULT_TIME_IN = "07:30"
DEFAULT_LUNCH_OUT = "12:00"
DEFAULT_LUNCH_IN = "13:00"
DEFAULT_LOG_OUT = "16:30"

# Fallback defaults, used only if App Settings sheet is missing a row.
DEFAULT_REMINDER_TIME = "15:00"
DEFAULT_REMINDER_REPEAT_MINUTES = 30
# Hard floor for the repeat nag interval, regardless of what
# ReminderRepeatMinutes is set to in the config sheet - a very low/zero
# value there previously caused the reminder to re-fire almost every
# check cycle (as often as once a minute), which is disruptive.
MIN_REMINDER_REPEAT_MINUTES = 15
# How long after the last "today" reminder slot (e.g. 3:00 PM) to keep
# repeating before giving up for the day entirely - default 90 minutes
# means repeats at +30/+60/+90 (e.g. 3:30, 4:00, 4:30) and then nothing
# beyond that, even if the day is still incomplete.
DEFAULT_REMINDER_REPEAT_CUTOFF_MINUTES = 90
DEFAULT_MIN_HOURS_GREEN = 4
DEFAULT_MAX_HOURS_WARNING = 8
# "You haven't picked a name yet" reminder: fixed schedule (not
# admin-configurable like the work-log reminders above, since there's no
# per-day threshold to check here - either a name is picked or it isn't).
# Repeats hourly, starting at the same morning slot as the other
# reminders, with a hard stop at 4:30 PM so it doesn't nag all evening.
NAME_REMINDER_REPEAT_MINUTES = 60
NAME_REMINDER_CUTOFF_TIME = dt.time(16, 30)
# Sanity checks for a SINGLE entry's Hours value (separate from
# MaxHoursWarningThreshold above, which is about the DAY's total). These
# catch an obvious typo - like an extra digit or a misplaced decimal
# point - before it ever gets saved.
SINGLE_ENTRY_HOURS_CONFIRM_THRESHOLD = 12  # ask "are you sure?" above this
MAX_SINGLE_ENTRY_HOURS = 24  # hard block above this - a day only has 24 hours
DEFAULT_ADMIN_USER = "admin"
DEFAULT_ADMIN_PASS = "nimda"

DATE_FMT = "%Y-%m-%d"
