"""Exercise image transport, typed responses, and review-policy boundaries."""

import base64
from copy import deepcopy
from io import BytesIO
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from PIL import Image

from app import demo_images
from assets import image_asset, inspection_request
from client import NoRedirect, evaluate_live, load_fixture
from decisions import route_inspection, validate_answers


class DecisionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.request = inspection_request(demo_images(Path(self.temporary.name)))
        self.response = load_fixture("confident")

    def answers(self):
        return validate_answers(self.request, self.response)

    def test_fixture_routes_are_explicit_and_different(self):
        self.assertEqual(route_inspection(self.answers())["route"], "accept_recommendation")
        uncertain = validate_answers(self.request, load_fixture("uncertain"))
        self.assertEqual(route_inspection(uncertain)["route"], "human_review")
        self.assertIn("fixture-only", self.response["model"])

    def test_high_selected_probability_does_not_replace_confidence(self):
        self.response["answers"]["condition"]["confidence"] = 0.1
        self.assertEqual(route_inspection(self.answers())["route"], "human_review")

    def test_high_confidence_does_not_replace_selected_probability(self):
        condition = self.response["answers"]["condition"]
        condition["confidence"] = 0.99
        condition["probabilities"] = {"intact": 0.51, "damaged": 0.46, "unclear": 0.03}
        self.assertEqual(route_inspection(self.answers())["route"], "human_review")
        condition["probabilities"] = {"intact": 0.8, "damaged": 0.2, "unclear": 0}
        self.assertEqual(route_inspection(self.answers())["route"], "accept_recommendation")
        condition["probabilities"] = {"intact": 0.7999, "damaged": 0.2001, "unclear": 0}
        self.assertEqual(route_inspection(self.answers())["route"], "human_review")

    def test_confidence_boundary(self):
        self.response["answers"]["condition"]["confidence"] = 0.8
        self.assertEqual(route_inspection(self.answers())["route"], "accept_recommendation")
        self.response["answers"]["condition"]["confidence"] = 0.7999
        self.assertEqual(route_inspection(self.answers())["route"], "human_review")

    def test_uncertain_yes_no_probability_is_reviewed(self):
        self.response["answers"]["needs_review"]["noul"] = 0.1999
        self.assertEqual(route_inspection(self.answers())["route"], "accept_recommendation")
        for probability in (0.2, 0.5, 1):
            self.response["answers"]["needs_review"]["noul"] = probability
            self.assertEqual(route_inspection(self.answers())["route"], "human_review")

    def test_invalid_choices_distributions_and_scores_are_rejected(self):
        mutations = (
            lambda value: value["answers"]["condition"].update(choice="invented"),
            lambda value: value["answers"]["condition"].update(choice="damaged"),
            lambda value: value["answers"]["condition"]["probabilities"].update(intact=0.5),
            lambda value: value["answers"]["condition"].update(confidence=float("nan")),
            lambda value: value["answers"]["condition"].update(confidence=True),
            lambda value: value["answers"]["severity"].update(score=1.5),
            lambda value: value["answers"].pop("needs_review"),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                value = deepcopy(self.response)
                mutate(value)
                with self.assertRaises(ValueError):
                    validate_answers(self.request, value)

    def test_multiple_images_have_unique_references_and_one_question_batch(self):
        self.assertEqual(len(self.request["assets"]), 2)
        self.assertEqual(len(self.request["questions"]), 3)
        references = {item["image"] for item in self.request["state"]["evidence"]}
        self.assertEqual(references, set(self.request["assets"]))

    def test_small_images_are_prepared_without_invalid_dimensions(self):
        path = Path(self.temporary.name) / "tiny.png"
        Image.new("RGB", (20, 40), "red").save(path)
        _, asset = image_asset(path)
        with Image.open(BytesIO(base64.b64decode(asset["data_base64"]))) as image:
            self.assertEqual(image.size, (280, 280))
            self.assertEqual(image.format, "JPEG")

    def test_live_adapter_sends_verified_contract_in_one_call(self):
        raw = BytesIO(json.dumps(self.response).encode())
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "test-placeholder"}), \
             patch("client._open", return_value=raw) as send:
            self.assertEqual(evaluate_live(self.request), self.response)
        self.assertEqual(send.call_count, 1)
        request = send.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.typesafe.ai/v1/systemone")
        self.assertEqual(request.get_header("Typesafe-danger-zone-images"), "true")
        self.assertEqual(json.loads(request.data), self.request)

    def test_live_key_is_required_and_http_errors_do_not_echo_body(self):
        with patch.dict(os.environ, {}, clear=True), patch("client._open") as send:
            with self.assertRaisesRegex(ValueError, "Set TYPESAFE_API_KEY"):
                evaluate_live(self.request)
            send.assert_not_called()
        error = HTTPError("https://api.typesafe.ai", 401, "secret-in-server-reason", {}, None)
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "test-placeholder"}), \
             patch("client._open", side_effect=error):
            with self.assertRaisesRegex(RuntimeError, r"^TypeSafe request failed with HTTP 401\.$"):
                evaluate_live(self.request)

    def test_redirect_and_timeout_are_fail_closed(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.invalid"))
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "test-placeholder"}), \
             patch("client._open", side_effect=TimeoutError):
            with self.assertRaisesRegex(RuntimeError, "connection failed or timed out"):
                evaluate_live(self.request)


if __name__ == "__main__":
    unittest.main()
