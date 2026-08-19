"""Application task package boundary.

Runtime code imports the concrete owner directly.  In particular,
``application.tasks.file_watch_task`` owns the watchdog lifecycle.  Keeping
this initializer empty prevents a package import from loading the concrete
task implementation; bootstrap imports and constructs that owner explicitly.
"""

__all__: list[str] = []
