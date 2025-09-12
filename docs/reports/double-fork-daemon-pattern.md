# Double Fork Daemon Pattern Explanation

## Why We Do Double Fork in `daemonize()` Function

The double fork technique is used to create a proper daemon process that's completely detached from the terminal and parent process. Here's why we need **both** forks:

### First Fork (Lines 340-346)
```python
pid = os.fork()
if pid > 0:
    # Parent process, exit
    sys.exit(0)
```

**Purpose:** Detach from the original parent process
- Creates a child process that's no longer tied to the original parent
- The original parent exits, so the child becomes an orphan
- This allows the process to run independently of the terminal session

### Session Leader Creation (Lines 348-351)
```python
os.chdir("/")
os.setsid()
os.umask(0)
```

**Purpose:** Create a new session and process group
- `os.setsid()` makes the process a session leader
- This detaches it from any controlling terminal
- Changes working directory to root to avoid blocking filesystem unmounts

### Second Fork (Lines 354-361)
```python
pid = os.fork()
if pid > 0:
    # Parent process, exit
    sys.exit(0)
```

**Purpose:** Prevent the daemon from ever acquiring a controlling terminal again
- Session leaders can potentially acquire controlling terminals
- By forking again, the final process is **not** a session leader
- This guarantees the daemon can never accidentally get a controlling terminal

## Why Both Forks Are Necessary

1. **First fork:** Detaches from original parent and terminal session
2. **Second fork:** Ensures the daemon can never reacquire a controlling terminal

Without the second fork, the daemon could potentially:
- Reacquire a controlling terminal if it opens `/dev/tty`
- Receive terminal signals (SIGHUP, SIGINT) unexpectedly
- Not be a "true" daemon according to Unix standards

## The Complete Daemon Pattern Flow

```
Original Process
    ↓
First Fork
    ↓
Parent Exits ← → Child Continues
                    ↓
                os.setsid() - Become Session Leader
                    ↓
                Second Fork
                    ↓
                Parent Exits ← → Final Daemon Process
                                    ↓
                                Redirect stdin/stdout/stderr
                                    ↓
                                Write PID File
```

## Benefits of This Pattern

- **Complete detachment:** Process runs independently of any terminal
- **No controlling terminal:** Cannot accidentally acquire terminal control
- **Proper orphan handling:** Init process becomes the parent
- **Signal isolation:** Protected from terminal-related signals
- **Filesystem safety:** Won't block unmounting of filesystems

This double fork pattern ensures the Gromozeka bot runs as a proper background daemon that won't be affected by terminal closures or session changes. It's a time-tested Unix technique for creating robust background services.

## References

- Advanced Programming in the UNIX Environment by W. Richard Stevens
- Unix Network Programming by W. Richard Stevens
- The Linux Programming Interface by Michael Kerrisk