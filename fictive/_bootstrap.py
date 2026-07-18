import sys
from pathlib import Path


def ensure_llm_utils_on_path() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    llm_utils_root = repo_root / "llm-utils"

    if not (llm_utils_root / "llm_utils").is_dir():
        return

    llm_utils_root_str = str(llm_utils_root)
    if llm_utils_root_str not in sys.path:
        sys.path.insert(0, llm_utils_root_str)
