"""Data-access layer for the GTM assistant.

Thin wrappers over the systems of record: the CRM (product offerings), the
enrichment/intent providers (prospect engagement history, account details, and
tech stack), and the prospect-profile cache. The agent's tools call these
functions rather than touching storage directly.

The underlying records live in ``gtm_records``.
"""

from langsmith import traceable

from .gtm_records import OFFERINGS, PROSPECTS, REP_IDS

__all__ = [
    "get_offering", "get_prospect_record", "update_prospect_info",
    "fetch_engagement_history", "fetch_account_details", "fetch_tech_stack",
    "get_profile_from_db", "save_profile_to_db",
    "get_rep", "SAFE_PROSPECT_FIELDS", "safe_prospect_fields",
]

SAFE_PROSPECT_FIELDS = (
    "name", "email", "annual_revenue", "enrichment_source", "disqualified",
)
_PROFILE_ENRICHMENT_FIELDS = (
    "engagement_history", "account_details", "tech_stack",
)

# Built prospect profiles are cached in memory (keyed by prospect_id) so repeat
# lookups within a run are served without rebuilding.
_PROFILES = {}

# ---------------------------------------------------------------------------
# Public data-access functions
# ---------------------------------------------------------------------------
def get_offering(offering_id):
    "Return the offering record for offering_id from the CRM, or None if not found."
    return OFFERINGS.get(offering_id)


def get_prospect_record(prospect_id):
    "Return the source prospect record for prospect_id, or None if not found."
    return PROSPECTS.get(prospect_id)


def safe_prospect_fields(record):
    "Return only prospect fields approved for model context."
    return {key: record[key] for key in SAFE_PROSPECT_FIELDS if key in record}


def get_rep(rep):
    "Return the rep directory record for a rep_id or name (case-insensitive), or None if not found."
    needle = (rep or "").strip().lower()
    for record in REP_IDS:
        if needle in (record["rep_id"].lower(), record["name"].lower()):
            return record
    return None


@traceable(run_type="tool", name="fetch_engagement_history")
def fetch_engagement_history(prospect_id):
    return PROSPECTS[prospect_id]["engagement_history"]


@traceable(run_type="tool", name="fetch_account_details")
def fetch_account_details(prospect_id):
    return PROSPECTS[prospect_id]["account_details"]


@traceable(run_type="tool", name="fetch_tech_stack")
def fetch_tech_stack(prospect_id):
    return PROSPECTS[prospect_id]["tech_stack"]


@traceable(run_type="tool", name="get_profile_from_db")
def get_profile_from_db(prospect_id):
    "Look up a stored prospect profile. Returns {'prospect_profile': record|None}."
    profile = _PROFILES.get(prospect_id)
    if profile is None:
        return {"prospect_profile": None}
    profile = _safe_profile(prospect_id, profile)
    _PROFILES[prospect_id] = profile
    return {"prospect_profile": profile}


@traceable(run_type="tool", name="save_profile_to_db")
def save_profile_to_db(prospect_id, profile):
    "Persist a prospect profile to the profile store."
    _PROFILES[prospect_id] = _safe_profile(prospect_id, profile)
    return {"saved": True}


def _safe_profile(prospect_id, profile):
    safe = {"prospect_id": prospect_id, **safe_prospect_fields(profile)}
    safe.update({
        key: profile[key]
        for key in _PROFILE_ENRICHMENT_FIELDS
        if key in profile
    })
    return safe


def update_prospect_info(prospect_id, technology):
    "Add a technology to a prospect's source-of-truth record."
    record = PROSPECTS.get(prospect_id)
    if record is None:
        return {"updated": False, "found": False}
    tech_stack = list(record["tech_stack"])
    if technology not in tech_stack:
        tech_stack.append(technology)
    return {"updated": True, "found": True, "tech_stack": tech_stack}
