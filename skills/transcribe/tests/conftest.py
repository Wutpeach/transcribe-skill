import pytest


@pytest.fixture(autouse=True)
def disable_auxiliary_glossary_network_for_unit_tests(monkeypatch, request):
    if request.module.__name__.endswith("test_auxiliary_glossary"):
        return
    monkeypatch.setattr("glossary.request_auxiliary_glossary_corrections", lambda **kwargs: [])
