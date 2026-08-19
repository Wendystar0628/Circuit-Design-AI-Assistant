import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run_import_probe(source: str) -> dict:
    marker = "IMPORT_BOUNDARY_RESULT="
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(source)],
        cwd=PROJECT_ROOT,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, (
        f"import probe failed with {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    payload_line = next(
        (line for line in result.stdout.splitlines() if line.startswith(marker)),
        None,
    )
    assert payload_line is not None, f"missing import probe payload: {result.stdout}"
    return json.loads(payload_line[len(marker):])


def test_importing_application_service_does_not_bootstrap_or_configure_runtime():
    payload = _run_import_probe(
        """
        import json
        import os
        import sys

        runtime_keys = (
            "SPICE_LIB_DIR",
            "SPICE_SCRIPTS",
            "TRANSFORMERS_OFFLINE",
            "HF_HUB_OFFLINE",
            "HF_HUB_DISABLE_SYMLINKS_WARNING",
        )
        before = {key: os.environ.get(key) for key in runtime_keys}

        assert "application.bootstrap" not in sys.modules
        import application.pending_workspace_edit_service

        after = {key: os.environ.get(key) for key in runtime_keys}
        print("IMPORT_BOUNDARY_RESULT=" + json.dumps({
            "bootstrap_loaded": "application.bootstrap" in sys.modules,
            "runtime_environment_changed": before != after,
        }))
        """
    )

    assert payload == {
        "bootstrap_loaded": False,
        "runtime_environment_changed": False,
    }


def test_package_initializers_do_not_eagerly_load_barrel_members():
    payload = _run_import_probe(
        """
        import json
        import sys

        import application
        import domain.llm

        print("IMPORT_BOUNDARY_RESULT=" + json.dumps({
            "session_state_loaded": "application.session_state" in sys.modules,
            "session_state_projector_loaded": (
                "application.session_state_projector" in sys.modules
            ),
            "llm_executor_loaded": "domain.llm.llm_executor" in sys.modules,
            "bootstrap_loaded": "application.bootstrap" in sys.modules,
        }))
        """
    )

    assert payload == {
        "session_state_loaded": False,
        "session_state_projector_loaded": False,
        "llm_executor_loaded": False,
        "bootstrap_loaded": False,
    }


def test_application_tasks_package_does_not_eagerly_construct_file_watcher():
    payload = _run_import_probe(
        """
        import json
        import sys

        import application.tasks
        package_loaded_watcher = "application.tasks.file_watch_task" in sys.modules

        import application.tasks.file_watch_task
        print("IMPORT_BOUNDARY_RESULT=" + json.dumps({
            "package_loaded_watcher": package_loaded_watcher,
            "concrete_watcher_loaded": (
                "application.tasks.file_watch_task" in sys.modules
            ),
        }))
        """
    )

    assert payload == {
        "package_loaded_watcher": False,
        "concrete_watcher_loaded": True,
    }
