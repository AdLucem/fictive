import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
LLM_UTILS_ROOT = REPO_ROOT / "llm-utils"

if (LLM_UTILS_ROOT / "llm_utils").is_dir():
    llm_utils_root_str = str(LLM_UTILS_ROOT)
    if llm_utils_root_str not in sys.path:
        sys.path.insert(0, llm_utils_root_str)
