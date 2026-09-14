import unittest

from bewerbo_tool.spec_loader import SpecValidationError, parse_workflow_spec, validate_input


class TestSpecLoader(unittest.TestCase):
    def test_parse_spec_rejects_duplicate_step_ids(self):
        """test parse spec rejects duplicate step ids."""
        payload = {
            "name": "a",
            "version": "1",
            "input_schema": {"required": ["id"]},
            "steps": [
                {"id": "x", "type": "transform"},
                {"id": "x", "type": "emit_output"},
            ],
        }
        with self.assertRaises(SpecValidationError):
            parse_workflow_spec(payload)

    def test_validate_input_requires_fields(self):
        """test validate input requires fields."""
        schema = {"required": ["item_id"]}
        with self.assertRaises(SpecValidationError):
            validate_input(schema, {})

    def test_parse_spec_rejects_non_numeric_retry_backoff(self):
        """test parse spec rejects non numeric retry backoff."""
        invalid_retries_payload = {
            "name": "a",
            "version": "1",
            "input_schema": {"required": ["id"]},
            "steps": [
                {"id": "x", "type": "transform", "retries": "not-a-number"},
            ],
        }
        with self.assertRaises(SpecValidationError):
            parse_workflow_spec(invalid_retries_payload)

        invalid_backoff_payload = {
            "name": "a",
            "version": "1",
            "input_schema": {"required": ["id"]},
            "steps": [
                {"id": "x", "type": "transform", "backoff_seconds": "not-a-number"},
            ],
        }
        with self.assertRaises(SpecValidationError):
            parse_workflow_spec(invalid_backoff_payload)

    def test_parse_spec_rejects_negative_retry_backoff(self):
        """test parse spec rejects negative retry backoff."""
        negative_retries_payload = {
            "name": "a",
            "version": "1",
            "input_schema": {"required": ["id"]},
            "steps": [
                {"id": "x", "type": "transform", "retries": -1},
            ],
        }
        with self.assertRaises(SpecValidationError):
            parse_workflow_spec(negative_retries_payload)

        negative_backoff_payload = {
            "name": "a",
            "version": "1",
            "input_schema": {"required": ["id"]},
            "steps": [
                {"id": "x", "type": "transform", "backoff_seconds": -0.1},
            ],
        }
        with self.assertRaises(SpecValidationError):
            parse_workflow_spec(negative_backoff_payload)


if __name__ == "__main__":
    unittest.main()
