"""Setting MailBrief up on a new computer by itself: the three scheduled runs and a Start-menu shortcut (no admin rights)."""
import base64
import os
import subprocess
import sys

from mailbrief import config


TASKS = {config.TASK_NAME: '--run', config.ALERTS_TASK: '--check', 'MailBrief Today': '--today'}


INSTALL_PS = r'''
$ErrorActionPreference = 'Stop'
$exe = $env:MB_EXE; $dir = Split-Path $exe
$set = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 2)
function Act($arg) { New-ScheduledTaskAction -Execute $exe -Argument $arg -WorkingDirectory $dir }
# weekly brief: Sunday 08:00
Register-ScheduledTask -TaskName $env:MB_WEEKLY -Action (Act '--run') -Settings $set -Force `
    -Trigger (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 08:00) | Out-Null
# hourly check 07:00-23:00
$hourly = New-ScheduledTaskTrigger -Daily -At 07:00
$hourly.Repetition = (New-ScheduledTaskTrigger -Once -At 07:00 -RepetitionInterval (New-TimeSpan -Hours 1) -RepetitionDuration (New-TimeSpan -Hours 16)).Repetition
Register-ScheduledTask -TaskName $env:MB_ALERTS -Action (Act '--check') -Settings $set -Trigger $hourly -Force | Out-Null
# "My day" when signing in to Windows
Register-ScheduledTask -TaskName 'MailBrief Today' -Action (Act '--today') -Force `
    -Trigger (New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME") | Out-Null
# Start menu
$lnk = Join-Path ([Environment]::GetFolderPath('Programs')) 'MailBrief.lnk'
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
$s.TargetPath = $exe; $s.WorkingDirectory = $dir; $s.IconLocation = "$exe,0"; $s.Description = 'MailBrief'; $s.Save()
'''


REMOVE_PS = r'''
foreach ($n in @($env:MB_WEEKLY, $env:MB_ALERTS, 'MailBrief Today')) {
  $t = Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue
  if ($t -and (-not $env:MB_EXE -or $t.Actions[0].Execute -eq $env:MB_EXE)) { Unregister-ScheduledTask -TaskName $n -Confirm:$false }
}
$lnk = Join-Path ([Environment]::GetFolderPath('Programs')) 'MailBrief.lnk'
if ((Test-Path $lnk) -and (-not $env:MB_EXE -or (New-Object -ComObject WScript.Shell).CreateShortcut($lnk).TargetPath -eq $env:MB_EXE)) { Remove-Item $lnk }
'''


QUERY_PS = r'''
foreach ($n in @($env:MB_WEEKLY, $env:MB_ALERTS, 'MailBrief Today')) {
  $t = Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue
  if ($t) { $t.Actions[0].Execute } else { '-' }
}
'''


def _powershell(script, exe=''):
    """Runs a script given as -EncodedCommand (UTF-16) so a Hebrew program path survives intact."""
    encoded = base64.b64encode(script.encode('utf-16-le')).decode()
    env = {**os.environ, 'MB_EXE': exe, 'MB_WEEKLY': config.TASK_NAME, 'MB_ALERTS': config.ALERTS_TASK}
    return subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', encoded],
                          capture_output=True, text=True, encoding='utf-8', errors='replace', env=env, timeout=60,
                          creationflags=0x08000000)


def program_path():
    return sys.executable if getattr(sys, 'frozen', False) else ''


def installed_paths():
    out = _powershell('[Console]::OutputEncoding = [Text.Encoding]::UTF8\n' + QUERY_PS).stdout
    return [line.strip() for line in out.splitlines() if line.strip()]


def schedule_ok(exe=None):
    exe = exe or program_path()
    paths = installed_paths()
    return len(paths) == 3 and all(os.path.normcase(p) == os.path.normcase(exe) for p in paths)


def install(exe=None):
    exe = exe or program_path()
    if not exe:
        raise RuntimeError('התזמונים נרשמים רק מ-MailBrief.exe (לא מקוד המקור)')
    done = _powershell(INSTALL_PS, exe)
    if done.returncode != 0:
        raise RuntimeError('רישום התזמונים נכשל: ' + (done.stderr.strip().splitlines() or ['?'])[-1][:200])


def remove(only_this_copy=True):
    _powershell(REMOVE_PS, program_path() if only_this_copy else '')


def ensure():
    """On start: register the runs when missing or pointing at another copy (e.g. after winget moved the program)."""
    exe = program_path()
    if exe and not schedule_ok(exe):
        from mailbrief.features.migrate import remember_previous
        for old in installed_paths():
            if old != '-' and os.path.normcase(old) != os.path.normcase(exe):
                remember_previous(old)             # its data can be brought over from the settings page
                break
        install(exe)
        return True
    return False
