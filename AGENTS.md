# Agent Instructions

## Runtime Reloads

When you change code that is used by the running daemon, tray icon, background
workers, control socket, web server, or any other long-lived process, do not stop
at editing files and running tests. Reload or restart the affected running
process unless the user explicitly asks you not to.

After restarting, verify that the live process is using the new code. For
MyWhispr this usually means checking `http://127.0.0.1:16666/api/status`, the
daemon PID/uptime, and the daemon logs. If the change is user-visible, verify the
visible behavior too, such as the tray icon/menu or web UI.

If you cannot safely reload the daemon, say that clearly and explain what is
still running old code. Do not tell the user a daemon/tray change is working
until the running process has actually been reloaded and checked.
