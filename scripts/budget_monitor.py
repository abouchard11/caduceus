#!/usr/bin/env python3
"""
Layer C: 15-minute monitor cron for daily spend aggregation.

This script:
1. Aggregates today's estimated_cost_usd across all profiles
2. Applies drift multiplier (2.5x)
3. Warns at 80% of daily ceiling ($8.00)
4. Pauses autonomous runs at 100% ($10.00)
5. Reports status to guard.log.jsonl

Run via: hermes cron add --name "budget-monitor" --every 15m --command "python3 /path/to/budget_monitor.py"
"""
import sys
import json
import time
from pathlib import Path

# Add caduceus to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from caduceus import budgets, config

def monitor():
    """Check daily budget and take action if needed."""
    # Get current daily spend
    status, spend, ceiling = budgets.check_daily_budget()
    
    # Log the check
    log_entry = {
        "ts": time.time(),
        "action": f"budget-monitor-{status}",
        "spend": spend,
        "ceiling": ceiling,
        "percent": (spend / ceiling * 100) if ceiling > 0 else 0
    }
    
    # Write to guard log
    log_path = config.guard_log_path()
    with open(log_path, 'a') as f:
        f.write(json.dumps(log_entry) + '\n')
    
    # Take action based on status
    if status == "warn":
        # At 80% - just warn
        print(f"⚠️  Budget warning: ${spend:.2f} / ${ceiling:.2f} ({log_entry['percent']:.0f}%)")
        print("Approaching daily ceiling. Consider pausing non-critical runs.")
        
    elif status == "block":
        # At 100% - pause all active budgets
        print(f"🛑 Budget limit reached: ${spend:.2f} / ${ceiling:.2f}")
        print("Pausing all active budgets...")
        
        active = budgets.list_active_budgets()
        paused_count = 0
        for budget in active:
            if not budget.paused:
                budget.paused = True
                budgets.save_budget(budget)
                paused_count += 1
                print(f"  Paused: {budget.run_id}")
        
        print(f"Paused {paused_count} active budgets.")
        print("Manual override required to resume: cad budget resume --run <run_id>")
        
    else:
        # Under 80% - all good
        print(f"✓ Budget OK: ${spend:.2f} / ${ceiling:.2f} ({log_entry['percent']:.0f}%)")
    
    return status

if __name__ == "__main__":
    status = monitor()
    # Exit code: 0 for ok/warn, 1 for block (so cron can alert)
    sys.exit(1 if status == "block" else 0)
