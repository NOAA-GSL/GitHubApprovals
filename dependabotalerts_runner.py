"""Dependabot alerts periodic runner.

Uses APScheduler to invoke the standalone notification script logic at a fixed interval.
Environment variables:
  RUN_INTERVAL_MINUTES (default 720 = 12 hours)
  GITHUB_TOKEN, EMAIL_ADDRESS, EMAIL_PASSWORD (required for underlying script)

This runner imports the main() function from dependabotalerts and executes it.
All exceptions are caught per run to avoid scheduler death.
"""
import os
import time
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.triggers.interval import IntervalTrigger

# Import the existing main logic
from dependabotalerts import main as run_dependabot

RUN_INTERVAL_MINUTES = int(os.getenv("RUN_INTERVAL_MINUTES", "1440"))  # default 24h between regular runs
SUMMARY_INTERVAL_DAYS = int(os.getenv("SUMMARY_RUN_INTERVAL_DAYS", "7"))  # weekly summary target

# In-memory tracking of last summary run (process lifetime only)
_last_summary_run = None  # type: datetime | None

scheduler = BackgroundScheduler(
    executors={"default": ThreadPoolExecutor(5)},
    job_defaults={"coalesce": True, "max_instances": 1},
    timezone="UTC"
)


def _run_wrapper():
    global _last_summary_run
    start = datetime.utcnow()
    print(f"[Runner] Starting dependabot notification run at {start.isoformat()}Z")
    try:
        # Decide whether to include summary this cycle (first summary delayed until interval passes)
        run_summary = False
        if _last_summary_run is None:
            # Establish baseline; do NOT run summary yet
            _last_summary_run = start
            print(f"[Runner] Initial baseline set at {start.isoformat()}Z; delaying first summary for {SUMMARY_INTERVAL_DAYS} days.")
        else:
            elapsed_days = (start - _last_summary_run).total_seconds() / 86400.0
            if elapsed_days >= SUMMARY_INTERVAL_DAYS:
                run_summary = True
                print(f"[Runner] {elapsed_days:.2f} days since last summary/baseline >= {SUMMARY_INTERVAL_DAYS}; including summary.")
            else:
                print(f"[Runner] {elapsed_days:.2f} days since baseline < {SUMMARY_INTERVAL_DAYS}; skipping summary this run.")

        if run_summary:
            run_dependabot([])  # normal run includes collaborator + summary by default
            _last_summary_run = start  # reset baseline
        else:
            run_dependabot(["--no-summary"])  # suppress summary, send per-repo notifications only

        print(f"[Runner] Run completed successfully at {datetime.utcnow().isoformat()}Z")
    except SystemExit as e:
        print(f"[Runner] Run exited with SystemExit code {e.code} at {datetime.utcnow().isoformat()}Z")
    except Exception as e:
        print(f"[Runner] Run failed with unexpected error: {e}")


def main():
    print(f"[Runner] Initializing scheduler (interval {RUN_INTERVAL_MINUTES} minutes)")
    # Single job handles both regular and (periodic) summary logic
    scheduler.add_job(
        _run_wrapper,
        trigger=IntervalTrigger(minutes=RUN_INTERVAL_MINUTES),
        id="dependabotalerts_combined_job",
        replace_existing=True,
        next_run_time=datetime.utcnow()  # immediate first run
    )
    scheduler.start()
    print("[Runner] Scheduler started. Press Ctrl+C to exit.")
    try:
        while True:
            time.sleep(3600)  # sleep in large increments; APScheduler runs jobs in background
    except (KeyboardInterrupt, SystemExit):
        print("[Runner] Shutting down scheduler...")
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    main()
