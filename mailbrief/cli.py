"""Command line: --run (weekly), --check (hourly), --today (sign-in), or the settings page."""
import datetime as dt
import os
import sys
import traceback

from mailbrief import config
from mailbrief.features.alerts import check_alerts
from mailbrief.features.brief import run_all
from mailbrief.features.calendar import is_holy_time, paused_until
from mailbrief.features.maintenance import make_backup
from mailbrief.features.reminders import fire_reminders
from mailbrief.features.update import cleanup, finish_update
from mailbrief.storage import load_json, save_json
from mailbrief.web.server import serve


def weekly_run():
    log = os.path.join(config.DATA, 'last-run.log')
    try:
        make_backup('auto')
    except OSError:
        pass
    try:
        path, results = run_all(open_report='--quiet' not in sys.argv)
        lines = [f'{r["email"]}: {len(r["items"])} messages, {r["tagged"]} tags, error={r["error"]}' for r in results]
        text = f'{dt.datetime.now():%Y-%m-%d %H:%M} OK {path}\n' + '\n'.join(lines)
    except Exception:
        text = f'{dt.datetime.now():%Y-%m-%d %H:%M} FAILED\n{traceback.format_exc()}'
    try:                                          # the encrypted copy in Google Drive, when turned on
        from mailbrief.features.cloud_backup import maybe_weekly
        state = load_json(config.STATE_FILE, {})
        if maybe_weekly(state):
            save_json(config.STATE_FILE, state)
            text += '\ncloud backup: uploaded'
    except Exception as exc:
        text += f'\ncloud backup failed: {exc}'
    with open(log, 'w', encoding='utf-8') as f:
        f.write(text + '\n')


def set_weekly_pending(value):
    state = load_json(config.STATE_FILE, {})
    state['_weekly_pending'] = value
    save_json(config.STATE_FILE, state)


def main():
    """Entry point used by main.py / MailBrief.exe."""
    from mailbrief.features.diag import setup_logging
    setup_logging()
    if '--uninstall' in sys.argv:               # before removing the program: scheduled runs and Start menu
        from mailbrief.features.setup import remove
        remove()
        return
    if '--replace' in sys.argv:                  # the downloaded update, finishing the swap
        finish_update(sys.argv[sys.argv.index('--replace') + 1])
        return
    os.makedirs(config.DATA, exist_ok=True)
    cleanup()
    automatic = any(flag in sys.argv for flag in ('--run', '--check', '--today'))
    user_paused = paused_until() is not None and '--today' not in sys.argv
    if automatic and (is_holy_time() or user_paused):
        # Shabbat / Yom Tov: nothing automatic runs. A weekly brief that falls now is postponed, not lost.
        if '--run' in sys.argv:
            set_weekly_pending(True)
        with open(os.path.join(config.DATA, 'last-skip.log'), 'w', encoding='utf-8') as f:
            f.write(f'{dt.datetime.now():%Y-%m-%d %H:%M} skipped {sys.argv[1:]} ({"paused" if user_paused else "Shabbat / Yom Tov"})\n')
        sys.exit(0)
    if '--run' in sys.argv:
        weekly_run()
        set_weekly_pending(False)
    elif '--check' in sys.argv:
        try:
            if load_json(config.STATE_FILE, {}).get('_weekly_pending'):
                weekly_run()                     # the brief that was postponed because of Shabbat / Yom Tov
                set_weekly_pending(False)
            check_alerts()
            fire_reminders()
        except Exception:
            with open(os.path.join(config.DATA, 'last-check.log'), 'w', encoding='utf-8') as f:
                f.write(traceback.format_exc())
    elif '--today' in sys.argv:                  # at Windows sign-in: open "My day"
        serve('today')
    else:
        serve()
