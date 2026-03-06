import pytest


@pytest.fixture(autouse=True)
def _clear_scaling_specs():
    from backend.engine.scoring import set_scaling_specs
    set_scaling_specs({})
    yield
    set_scaling_specs({})
