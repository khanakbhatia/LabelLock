from tests.conftest import validate_examples


def test_openapi_enums_and_examples_are_consistent():
    assert validate_examples.validate_all() == []
