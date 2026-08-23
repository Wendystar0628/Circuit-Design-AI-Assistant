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


def test_importing_application_service_does_not_configure_runtime():
    payload = _run_import_probe(
        """
        import json
        import os
        runtime_keys = (
            "SPICE_LIB_DIR",
            "SPICE_SCRIPTS",
            "TRANSFORMERS_OFFLINE",
            "HF_HUB_OFFLINE",
            "HF_HUB_DISABLE_SYMLINKS_WARNING",
        )
        before = {key: os.environ.get(key) for key in runtime_keys}

        import application.pending_workspace_edit_service

        after = {key: os.environ.get(key) for key in runtime_keys}
        print("IMPORT_BOUNDARY_RESULT=" + json.dumps({
            "runtime_environment_changed": before != after,
        }))
        """
    )

    assert payload == {
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
            "runtime_loaded": "application.runtime" in sys.modules,
            "agent_loop_loaded": "domain.llm.agent.agent_loop" in sys.modules,
        }))
        """
    )

    assert payload == {
        "session_state_loaded": False,
        "session_state_projector_loaded": False,
        "runtime_loaded": False,
        "agent_loop_loaded": False,
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


def test_application_state_and_file_services_do_not_import_desktop_ui_runtime():
    payload = _run_import_probe(
        """
        import json
        import sys

        import shared.event_bus
        import application.pending_workspace_edit_service
        import application.metric_target_service
        import application.tasks.file_watch_task

        print("IMPORT_BOUNDARY_RESULT=" + json.dumps({
            "qt_modules": sorted(name for name in sys.modules if name.startswith("PyQt")),
            "qasync_loaded": "qasync" in sys.modules,
            "presentation_modules": sorted(
                name for name in sys.modules if name == "presentation" or name.startswith("presentation.")
            ),
        }))
        """
    )

    assert payload == {
        "qt_modules": [],
        "qasync_loaded": False,
        "presentation_modules": [],
    }
