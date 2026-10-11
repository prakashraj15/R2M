import pytest

from mock_agent import memory


@pytest.fixture(autouse=True)
def clean_memory():
    memory.reset_all()
    yield
    memory.reset_all()
