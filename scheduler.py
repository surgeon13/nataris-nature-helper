# ==========================================
#           NATARIS SCHEDULER
#           Runs in background thread.
#           Only sets flags - never touches
#           Chrome directly.
#           Main thread reads flags and acts.
#           Checks tasks every 60 seconds.
#           Persists tasks to JSON so they
#           survive bot restarts.
# ==========================================

import threading
import time
import json
import os
from helpers import red, yellow, green, cyan, bold, info, ok, warn, err, status

# ==========================================
#           SCHEDULER FLAGS
#           Only scheduler thread writes these.
#           Only main thread reads and resets these.
# ==========================================

flags = {
    "demolition_ready": False,  # Demolition timer expired - resume
    "resources_needed": False,  # A village needs resources sent
    "queue_empty":      False,  # A village build queue is empty
    "checkup_due":      False,  # Time for a village checkup
}

# ==========================================
#           TASK LIST AND LOCKS
# ==========================================

tasks      = []
tasks_lock = threading.Lock()
stop_event = threading.Event()

STATE_FILE    = os.path.join(os.path.dirname(__file__), "demolition_state.json")
SCHEDULE_FILE = os.path.join(os.path.dirname(__file__), "scheduler_tasks.json")

# ==========================================
#           TASK PERSISTENCE
# ==========================================

def load_tasks():
    """
    Loads saved tasks from JSON file on startup.
    Restores any tasks that survived a bot restart.
    Called once when scheduler thread starts.
    """
    global tasks
    if not os.path.exists(SCHEDULE_FILE):
        return
    try:
        with open(SCHEDULE_FILE, "r") as f:
            with tasks_lock:
                tasks = json.load(f)
        print(f"Scheduler: loaded {len(tasks)} saved tasks.")
    except Exception:
        err("Scheduler: could not load saved tasks.")

def save_tasks():
    """
    Saves current task list to JSON file.
    Called after every task change to ensure persistence.
    """
    try:
        with tasks_lock:
            with open(SCHEDULE_FILE, "w") as f:
                json.dump(tasks, f, indent=2)
    except Exception:
        err("Scheduler: could not save tasks.")

# ==========================================
#           TASK MANAGEMENT
# ==========================================

def add_task(task_type, village, run_at, data=None):
    """
    Adds a new task to the scheduler task list.
    task_type: demolition_resume, resource_check, queue_check, checkup
    village:   village dict with name and id
    run_at:    unix timestamp when task should run
    data:      any extra data needed for the task
    """
    task = {
        "type":    task_type,
        "village": village,
        "run_at":  run_at,
        "data":    data or {},
    }
    with tasks_lock:
        tasks.append(task)
    save_tasks()
    run_at_str = time.strftime("%H:%M:%S", time.localtime(run_at))
    print(f"Scheduler: task added - {task_type} for {village['name']} at {run_at_str}")

def remove_task(task):
    """
    Removes a completed task from the task list.
    Called after a task has been handled by main thread.
    """
    with tasks_lock:
        if task in tasks:
            tasks.remove(task)
    save_tasks()

def get_due_tasks():
    """
    Returns all tasks that are due to run now.
    Sorted by run_at so earliest tasks run first.
    Does not remove tasks - caller is responsible for cleanup.
    """
    now = time.time()
    with tasks_lock:
        due = [t for t in tasks if t["run_at"] <= now]
    return sorted(due, key=lambda t: t["run_at"])

# ==========================================
#           DEMOLITION STATE CHECK
# ==========================================

def check_demolition_state():
    """
    Checks if saved demolition state has a timer that expired.
    Sets demolition_ready flag if timer has passed.
    Called every scheduler cycle.
    """
    if not os.path.exists(STATE_FILE):
        return
    try:
        with open(STATE_FILE, "r") as f:
            state = json.load(f)
        finish_at        = state.get("finish_at")
        levels_remaining = state.get("levels_remaining", 0)
        if levels_remaining > 0 and finish_at and time.time() >= finish_at:
            flags["demolition_ready"] = True
            print("Scheduler: demolition ready to resume!")
    except Exception:
        pass

# ==========================================
#           SCHEDULER MAIN LOOP
# ==========================================

def scheduler_loop():
    """
    Main scheduler loop running in background thread.
    Checks demolition state and due tasks every 60 seconds.
    Never touches Chrome - only sets flags.
    Main thread reads flags at top of each menu loop.
    Stops cleanly when stop_event is set.
    """
    ok("Scheduler: started.")
    load_tasks()

    while not stop_event.is_set():
        # Check demolition state file every cycle
        check_demolition_state()

        # Check due tasks and set appropriate flags
        due = get_due_tasks()
        for task in due:
            task_type = task["type"]
            print(f"Scheduler: task due - {task_type} for {task['village']['name']}")

            if task_type == "demolition_resume":
                flags["demolition_ready"] = True
            elif task_type == "resource_check":
                flags["resources_needed"] = True
            elif task_type == "queue_check":
                flags["queue_empty"] = True
            elif task_type == "checkup":
                flags["checkup_due"] = True

            remove_task(task)

        # Sleep 60 seconds but check stop event every second
        for _ in range(60):
            if stop_event.is_set():
                break
            time.sleep(1)

    print("Scheduler: stopped.")

# ==========================================
#           PUBLIC API
# ==========================================

def start_scheduler():
    """
    Starts the scheduler in a background daemon thread.
    Daemon thread dies automatically when main program exits.
    Safe to call once after login.
    """
    thread = threading.Thread(target=scheduler_loop, daemon=True)
    thread.start()
    return thread

def stop_scheduler():
    """
    Signals the scheduler thread to stop cleanly.
    Call before bot exits if needed.
    """
    stop_event.set()
    print("Scheduler: stop signal sent.")

def check_flags(driver, abort_flag):
    """
    Called by main thread at top of every menu loop.
    Checks all scheduler flags and triggers appropriate actions.
    Resets flags after handling so they don't fire twice.
    Never blocks - checks and acts immediately then returns.
    """
    from destroyer import resume_demolition
    from village_checkup import run_village_checkup
    from village_builder_engine import get_all_villages

    if flags["demolition_ready"]:
        print("\nScheduler: resuming demolition...")
        flags["demolition_ready"] = False
        resume_demolition(driver, abort_flag)

    if flags["checkup_due"]:
        print("\nScheduler: running scheduled checkup...")
        flags["checkup_due"] = False
        villages = get_all_villages(driver)
        run_village_checkup(driver, villages)

    if flags["resources_needed"]:
        print("\nScheduler: resource check triggered - use menu option 5 to send resources.")
        flags["resources_needed"] = False

    if flags["queue_empty"]:
        print("\nScheduler: a village queue is empty - consider running a build cycle.")
        flags["queue_empty"] = False

def schedule_demolition_resume(village, finish_at):
    """
    Convenience function to schedule a demolition resume task.
    Called by destroyer after queuing a demolition.
    village:   village dict with name and id
    finish_at: unix timestamp when demolition completes
    """
    add_task("demolition_resume", village, finish_at)

def schedule_checkup(interval_minutes=60):
    """
    Schedules a recurring village checkup task.
    Default interval is 60 minutes.
    Called once after login to set up automatic checkups.
    """
    run_at = time.time() + (interval_minutes * 60)
    add_task("checkup", {"name": "all", "id": "all"}, run_at)
    print(f"Scheduler: checkup scheduled in {interval_minutes} minutes.")
