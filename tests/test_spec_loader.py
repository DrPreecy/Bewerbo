from bewerbo_tool.spec_loader import SpecValidationError, parse_workflow_spec, validate_input


def test_parse_spec_rejects_duplicate_step_ids():
    payload = {
        "name": "a",
        "version": "1",
        "input_schema": {"required": ["id"]},
        "steps": [
            {"id": "x", "type": "transform"},
            {"id": "x", "type": "emit_output"},
        ],
    }
    try:
        parse_workflow_spec(payload)
        assert False, "Expected SpecValidationError"
    except SpecValidationError:
        assert True


def test_validate_input_requires_fields():
    schema = {"required": ["item_id"]}
    try:
        validate_input(schema, {})
        assert False, "Expected SpecValidationError"
    except SpecValidationError:
        assert True
