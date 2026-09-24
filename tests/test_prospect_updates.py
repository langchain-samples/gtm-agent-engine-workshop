import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ["LANGSMITH_TRACING"] = "false"

from gtm_agent import data_service
from gtm_agent import gtm_agent as agent_module
from gtm_agent.gtm_agent import score_prospect


class ProspectUpdateTests(unittest.TestCase):
    def setUp(self):
        data_service._PROFILES.pop("LEAD-39002", None)
        if "Terraform" in data_service.PROSPECTS["LEAD-39002"]["tech_stack"]:
            data_service.PROSPECTS["LEAD-39002"]["tech_stack"].remove("Terraform")

    def tearDown(self):
        if "Terraform" in data_service.PROSPECTS["LEAD-39002"]["tech_stack"]:
            data_service.PROSPECTS["LEAD-39002"]["tech_stack"].remove("Terraform")
        data_service._PROFILES.pop("LEAD-39002", None)

    def test_update_persists_and_invalidates_profile_cache(self):
        data_service.save_profile_to_db("LEAD-39002", {"prospect_id": "LEAD-39002"})

        result = data_service.update_prospect_info("LEAD-39002", "Terraform")

        self.assertTrue(result["updated"])
        self.assertIn("Terraform", data_service.fetch_tech_stack("LEAD-39002"))
        self.assertIsNone(data_service.get_profile_from_db("LEAD-39002")["prospect_profile"])

        duplicate = data_service.update_prospect_info("LEAD-39002", "Terraform")
        self.assertFalse(duplicate["updated"])
        self.assertTrue(duplicate["already_present"])

    def test_score_prospect_uses_saved_tech_stack(self):
        data_service.update_prospect_info("LEAD-39002", "Terraform")
        profile = {"prospect_id": "LEAD-39002", "tech_stack": []}
        offering = {
            "required_tech_stack": ["Terraform"],
            "min_annual_revenue": 1,
            "description": "Test offering",
        }

        class FakeScoringModel:
            def __init__(self):
                self.calls = []

            def invoke(self, messages):
                self.calls.append(messages)
                return type("ScoringResult", (), {"model_dump": lambda self: {}})()

        scoring_model = FakeScoringModel()
        with patch.object(agent_module, "_scoring_llm", scoring_model):
            score_prospect.invoke({"prospect_profile": profile, "offering": offering})

        user_prompt = scoring_model.calls[0][1]["content"]
        self.assertIn('"Terraform"', user_prompt)


if __name__ == "__main__":
    unittest.main()
