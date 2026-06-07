# Scheduling

Run it weekly (or however you like). Two independent briefs is the recommended setup:
- **Newsletters** one day (e.g. Monday 7am): `run_digest.sh --no-videos --label newsletters`
- **YouTube** another day (e.g. Thursday 7am): `run_digest.sh --no-newsletters --label youtube`

(One feed per day you'll actually open beats a daily firehose you ignore.)

## macOS (launchd) — recommended on a Mac
See `macos-launchd/`. Edit the `.plist.example` files: replace `<ABSOLUTE-PATH-TO-REPO>` with the
full path to this folder, then:
```
cp macos-launchd/newsletter.plist.example ~/Library/LaunchAgents/aibrief.newsletter.plist
cp macos-launchd/youtube.plist.example    ~/Library/LaunchAgents/aibrief.youtube.plist
launchctl load ~/Library/LaunchAgents/aibrief.newsletter.plist
launchctl load ~/Library/LaunchAgents/aibrief.youtube.plist
```
Weekday integers: Sunday=0 … Monday=1 … Thursday=4.

## Linux / WSL (cron)
```
crontab -e
# Newsletters Monday 7am, YouTube Thursday 7am
0 7 * * 1 /ABSOLUTE-PATH-TO-REPO/run_digest.sh --no-videos --label newsletters
0 7 * * 4 /ABSOLUTE-PATH-TO-REPO/run_digest.sh --no-newsletters --label youtube
```

## Windows
Use Task Scheduler to run `run_digest.sh` via WSL/Git-Bash on a weekly trigger, or ask your coding
agent to generate a PowerShell scheduled task. The Python code itself is cross-platform.

> Tip: just tell your coding agent "set up the weekly schedule for my OS" and it will handle this.
