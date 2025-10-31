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

RUN_INTERVAL_MINUTES = int(os.getenv("RUN_INTERVAL_MINUTES", "720"))  # default 12h
SUMMARY_INTERVAL_DAYS = int(os.getenv("SUMMARY_RUN_INTERVAL_DAYS", "7"))  # weekly summary default

scheduler = BackgroundScheduler(
    executors={"default": ThreadPoolExecutor(5)},
    job_defaults={"coalesce": True, "max_instances": 1},
    timezone="UTC"
)


def _run_wrapper():
    start = datetime.utcnow()
    print(f"[Runner] Starting dependabot notification run at {start.isoformat()}Z")
    try:
        run_dependabot([])  # normal run (no arguments)
        print(f"[Runner] Run completed successfully at {datetime.utcnow().isoformat()}Z")
    except SystemExit as e:
        print(f"[Runner] Run exited with SystemExit code {e.code} at {datetime.utcnow().isoformat()}Z")
    except Exception as e:
        print(f"[Runner] Run failed with unexpected error: {e}")


def _run_summary_wrapper():
    start = datetime.utcnow()
    print(f"[Runner] Starting summary-only dependabot run at {start.isoformat()}Z")
    try:
        run_dependabot(["--summary-only"])  # summary only
        print(f"[Runner] Summary run completed successfully at {datetime.utcnow().isoformat()}Z")
    except SystemExit as e:
        print(f"[Runner] Summary run exited with SystemExit code {e.code} at {datetime.utcnow().isoformat()}Z")
    except Exception as e:
        print(f"[Runner] Summary run failed with unexpected error: {e}")


def main():
    print(f"[Runner] Initializing scheduler (interval {RUN_INTERVAL_MINUTES} minutes)")
    # Regular cadence job
    scheduler.add_job(
        _run_wrapper,
        trigger=IntervalTrigger(minutes=RUN_INTERVAL_MINUTES),
        id="dependabot_alerts_job",
        replace_existing=True,
        next_run_time=datetime.utcnow()  # run immediately at start
    )
    # Weekly summary job
    scheduler.add_job(
        _run_summary_wrapper,
        trigger=IntervalTrigger(days=SUMMARY_INTERVAL_DAYS),
        id="dependabot_summary_job",
        replace_existing=True,
        next_run_time=datetime.utcnow() + timedelta(seconds=5)  # slight delay after first normal run
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
