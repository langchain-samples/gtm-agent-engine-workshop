import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("LANGSMITH_TRACING", "false")

from gtm_agent import gtm_agent


class GtmAgentTests(unittest.TestCase):
    def test_scoring_request_does_not_require_rep_lookup(self):
        score = {
            "score": 82,
            "max_score": 100,
            "justification": "Strong fit.",
            "rubric_breakdown": {
                "revenue_fit": 28,
                "tech_stack_match": 30,
                "segment_fit": 24,
                "component_max": 100,
            },
        }
        offering = {
            "required_tech_stack": ["CRM"],
            "min_annual_revenue": 1_000_000,
            "description": "CRM platform",
        }
        scoring_result = SimpleNamespace(model_dump=lambda: score)
        scoring_llm = SimpleNamespace(invoke=lambda messages: scoring_result)
        with patch.object(gtm_agent.data_service, "fetch_tech_stack", return_value=["CRM"]), \
                patch.object(gtm_agent, "_scoring_llm", scoring_llm), \
                patch.object(gtm_agent.data_service, "get_rep", side_effect=AssertionError):
            result = gtm_agent.score_prospect.func(
                {"prospect_id": "LEAD-39002"},
                offering,
            )

        self.assertEqual(result["score"], 82)

    def test_email_fallback_resolves_sender_without_get_current_rep(self):
        rep = {"name": "Alex Rep", "email": "alex@example.com"}
        runtime = SimpleNamespace(config={"metadata": {"user_id": "rep-1"}})
        with patch.object(gtm_agent.data_service, "get_rep", return_value=rep):
            result = gtm_agent.send_prospect_email.func(
                {"name": "Prospect", "email": "prospect@example.com"},
                "Hello",
                "Checking in.",
                runtime,
            )

        self.assertEqual(result["from"], "alex@example.com")


if __name__ == "__main__":
    unittest.main()
