"""Run the GTM agent against a set of example rep requests.

Run from the repo root with:

    uv run python3 run.py
"""

from langsmith.run_trees import get_cached_client

from gtm_agent.gtm_agent import record_rep_feedback, run_agent
from rep_feedback import rate_reply


# (signed-in rep, request)
EXAMPLES = [
    ("rep_amills", "Can you email LEAD-12853 to schedule their demo call for next week?"),
    ("rep_jchen", "Score LEAD-71001 against OFFER-10005."),
    ("rep_dweiss", "Send LEAD-15229 an email to schedule an intro call."),
    ("rep_tkim", "First add Kafka to LEAD-71001's tech stack, then score them against OFFER-10005."),
    ("rep_jchen", "Email LEAD-18993 to set up a technical deep dive."),
    ("rep_sbrown", "Please add Kafka to LEAD-71001's profile — they mentioned it on the discovery call — then re-score against OFFER-10005."),
    ("rep_kpatel", "Please email LEAD-70001 to confirm their availability for a pricing review."),
    ("rep_mrossi", "Update LEAD-71001 with the Kafka technology and score them against the OFFER-10005 offering."),
    ("rep_lnguyen", "Shoot LEAD-71001 an email letting them know we're moving them to a trial."),
    ("rep_rgarcia", "Score LEAD-39002 against OFFER-10004."),
    ("rep_mrossi", "Email LEAD-50001 to invite them to book a demo."),
    ("rep_amills", "First add Terraform to LEAD-39002's tech stack, then score them against OFFER-10004."),
    ("rep_oadeyemi", "Can you send LEAD-50002 an email to schedule a technical deep dive?"),
    ("rep_lnguyen", "Please add Terraform to LEAD-39002's profile — it showed up in their latest enrichment data — then re-score against OFFER-10004."),
    ("rep_sbrown", "Email LEAD-50003 to send over our pricing deck."),
    ("rep_kpatel", "Update LEAD-39002 with the Terraform technology and score them against the OFFER-10004 offering."),
    ("rep_tkim", "Please email LEAD-50004 to confirm their availability for a discovery call."),
    ("rep_oadeyemi", "Score LEAD-90001 against OFFER-10007."),
    ("rep_rgarcia", "Send LEAD-50005 an email asking about their availability for an onsite workshop."),
    ("rep_dweiss", "First add Okta to LEAD-90001's tech stack, then score them against OFFER-10007."),
]


if __name__ == "__main__":
    for user_id, q in EXAMPLES:
        print(f"\n> [{user_id}] {q}")
        result = run_agent(q, user_id=user_id)
        print(result["reply"])
        score, comment = rate_reply(result["messages"])
        # Traces are shipped on a background thread, so flush before attaching
        # feedback to make sure the root run has landed in LangSmith.
        get_cached_client().flush()
        record_rep_feedback(result["run_id"], score, comment)
