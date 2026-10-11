"""OpsPilot's code-owned policies. Each lives in its own file so its artifact hash covers only itself."""
from .data import DATA_001
from .deployment import DEPLOY_001
from .scaling import CAPACITY_001

ALL_POLICIES = (DEPLOY_001, CAPACITY_001, DATA_001)

__all__ = ["ALL_POLICIES", "CAPACITY_001", "DATA_001", "DEPLOY_001"]
