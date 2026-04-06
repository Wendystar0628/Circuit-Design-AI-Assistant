import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from domain.simulation.models.simulation_result import SimulationResult
from shared.constants.paths import SIM_RESULTS_DIR
from shared.models.load_result import LoadResult


class SimulationResultRepository:
    def __init__(self):
        self._logger = logging.getLogger(__name__)

    def save(self, project_root: str, result: SimulationResult) -> str:
        root = Path(project_root)
        result_id = self._generate_result_id()
        result_rel_path = f"{SIM_RESULTS_DIR}/{result_id}.json"
        result_path = root / result_rel_path
        result_path.parent.mkdir(parents=True, exist_ok=True)

        result_dict = result.to_dict()
        result_dict["id"] = result_id
        content = json.dumps(result_dict, indent=2, ensure_ascii=False)
        result_path.write_text(content, encoding="utf-8")
        return result_rel_path

    def load(self, project_root: str, result_path: str) -> LoadResult[SimulationResult]:
        if not result_path:
            return LoadResult.path_empty()

        root = Path(project_root)
        file_path = root / result_path
        if not file_path.exists():
            return LoadResult.file_missing(result_path)

        try:
            content = file_path.read_text(encoding="utf-8")
            if not content.strip():
                return LoadResult.parse_error(result_path, "文件内容为空")

            data = json.loads(content)
            result = SimulationResult.from_dict(data)
            return LoadResult.ok(result, result_path)
        except json.JSONDecodeError as e:
            return LoadResult.parse_error(result_path, f"JSON 解析失败: {e}")
        except KeyError as e:
            return LoadResult.parse_error(result_path, f"缺少必需字段: {e}")
        except Exception as e:
            return LoadResult.unknown_error(result_path, str(e))

    def list(self, project_root: str, limit: int = 10) -> List[Dict[str, Any]]:
        root = Path(project_root)
        results_dir = root / SIM_RESULTS_DIR
        if not results_dir.exists():
            return []

        json_files = list(results_dir.glob("*.json"))
        json_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)

        results = []
        for file_path in json_files[:limit]:
            try:
                content = file_path.read_text(encoding="utf-8")
                data = json.loads(content)
                results.append({
                    "id": data.get("id", file_path.stem),
                    "file_path": data.get("file_path", ""),
                    "analysis_type": data.get("analysis_type", ""),
                    "success": data.get("success", False),
                    "timestamp": data.get("timestamp", ""),
                    "path": str(file_path.relative_to(root)),
                })
            except Exception as e:
                self._logger.debug(f"Failed to read simulation result summary {file_path}: {e}")
                continue
        return results

    def get_latest(self, project_root: str) -> LoadResult[SimulationResult]:
        results = self.list(project_root, limit=1)
        if results:
            return self.load(project_root, results[0]["path"])
        return LoadResult.file_missing("")

    def delete(self, project_root: str, result_path: str) -> bool:
        root = Path(project_root)
        file_path = root / result_path
        if not file_path.exists():
            return False

        try:
            file_path.unlink()
            return True
        except Exception as e:
            self._logger.error(f"删除仿真结果失败: {e}")
            return False

    def _generate_result_id(self) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        short_uuid = uuid.uuid4().hex[:8]
        return f"sim_{timestamp}_{short_uuid}"


simulation_result_repository = SimulationResultRepository()


__all__ = ["SimulationResultRepository", "simulation_result_repository"]
