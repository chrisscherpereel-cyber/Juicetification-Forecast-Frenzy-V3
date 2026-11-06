"""
ff_progress.py — background, coalescing writer for durable student progress.

WHY (performance)
When Dropbox storage is configured, the app autosaves after every change. Done inline,
each save is an encrypted upload over the network (typically a few hundred ms, longer
with retries), and the student's screen cannot finish updating until it returns — on
every slider move, every checked answer, every typed response. With 30–40 students
those waits add up to a sluggish lab even though the server CPU is idle.

This writer moves the upload off the page script: the rerun finishes immediately and
a small pool of worker threads performs the upload in the background.

GUARANTEES
* Same data, same destination, same encryption — it calls the unchanged
  student_store.save(); only the timing moves.
* Coalescing: at most ONE pending save per student. If a student changes three things
  while an upload is in flight, only the newest snapshot is uploaded next (older
  intermediate states would be overwritten anyway). This also cuts Dropbox API calls.
* Per-student ordering: a student's saves never run concurrently, so an older snapshot
  can never land after (and overwrite) a newer one.
* "Save & sign out" stays synchronous and honest: it discards any queued save, waits
  for an in-flight one to finish, then writes the final snapshot itself and reports
  whether that write succeeded (see flush_save in forecast_frenzy.py).
* Bounded: one pending entry per active student and a fixed number of threads.

The one trade-off: if the server process is killed in the second or two between a
change and its upload, that change is lost (it would be re-saved on the student's next
interaction). The previous inline code had the same exposure for a save in progress
and also silently ignored upload failures.
"""

import collections
import logging
import threading

_LOG = logging.getLogger(__name__)


class ProgressWriter:
    def __init__(self, workers=3):
        self._cv = threading.Condition()
        self._pending = {}                      # key -> (fn, args)
        self._order = collections.deque()       # keys with a pending job, oldest first
        self._inflight = set()
        self.completed = 0
        self.failed = 0
        for i in range(workers):
            threading.Thread(target=self._run, name=f"progress-writer-{i}", daemon=True).start()

    def submit(self, key, fn, *args):
        """Queue fn(*args) as the latest save for `key`, replacing any not-yet-started one."""
        with self._cv:
            if key not in self._pending:
                self._order.append(key)
            self._pending[key] = (fn, args)
            self._cv.notify()

    def discard(self, key):
        """Drop a queued (not yet started) save for `key`."""
        with self._cv:
            if self._pending.pop(key, None) is not None:
                self._order.remove(key)

    def flush(self, key, timeout=30.0):
        """Block until nothing is queued or in flight for `key`. True if drained in time."""
        with self._cv:
            return self._cv.wait_for(
                lambda: key not in self._pending and key not in self._inflight, timeout)

    def _next_job(self):
        # Oldest queued key that is not already being uploaded (per-key ordering).
        for key in self._order:
            if key not in self._inflight:
                self._order.remove(key)
                return key, self._pending.pop(key)
        return None

    def _run(self):
        while True:
            with self._cv:
                job = self._next_job()
                while job is None:
                    self._cv.wait()
                    job = self._next_job()
                key, (fn, args) = job
                self._inflight.add(key)
            try:
                fn(*args)
                ok = True
            except Exception:                    # never let one failure kill the worker
                _LOG.warning("Background progress save failed for %r", key, exc_info=True)
                ok = False
            with self._cv:
                self._inflight.discard(key)
                if ok:
                    self.completed += 1
                else:
                    self.failed += 1
                self._cv.notify_all()


# One writer per server process, shared by every session (imported modules are
# initialised once). Keys are (game, student id), so sessions never share an entry.
WRITER = ProgressWriter()
