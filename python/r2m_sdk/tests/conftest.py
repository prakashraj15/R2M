import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from r2m import R2MClient  # noqa: E402
from r2m.testing import FakePlatform  # noqa: E402

VENDOR = "00000000-0000-4000-8000-00000000a7a5"
CUSTOMER = "00000000-0000-4000-8000-0000000003e1"


@pytest.fixture
def platform() -> FakePlatform:
    return FakePlatform(grant_key="test-token")


@pytest.fixture
def client(platform: FakePlatform) -> R2MClient:
    c = R2MClient(token="test-token", agent_slug="opspilot", vendor_org_id=VENDOR, customer_org_id=CUSTOMER,
                  environment="production", background=False, http_transport=platform.transport)
    c.transport._backoff_s = 0  # fast retries in tests
    c.register_agent(name="OpsPilot", build_version="safe-1.0", source_digest="sha256:src",
                     artifact_digest="sha256:art")
    yield c
    c.close()
