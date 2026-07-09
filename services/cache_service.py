"""
Cache & Rate-Limit Service
--------------------------
• Analysis caching: SHA-256(resume_text + jd_text) → look up existing api_analysis row
  by (user_id, resume_id, jd_id). No schema change needed — we query the existing table.
• Daily usage limits: count api_analysis rows created today per user.
• All feature-level caches (cover letters, roadmap, etc.) already exist in db_helpers.py
  via the get_X / save_X pattern — this module just exposes the limit checks.
"""

import hashlib
import logging
from datetime import date
from django.db import connection

logger = logging.getLogger(__name__)

# ── Plan definitions ────────────────────────────────────────────────────────────
FREE_PLAN_LIMITS = {
    'analyses':    5,
    'cover_letter': 2,
    'interview':   2,
    'roadmap':     2,
}

PRO_PLAN_LIMITS = {
    'analyses':    50,
    'cover_letter': 20,
    'interview':   20,
    'roadmap':     999_999,   # effectively unlimited
}

def _get_plan_limits(user) -> dict:
    """Return limit dict based on user plan.
    We detect 'pro' via Profile.api_keys_count > 2 as a proxy flag
    (no schema change required). Adjust the condition to match your plan logic.
    """
    try:
        profile = user.profile
        if profile.api_keys_count > 2:
            return PRO_PLAN_LIMITS
    except Exception:
        pass
    return FREE_PLAN_LIMITS


# ── Usage counting ───────────────────────────────────────────────────────────────
def get_daily_usage(user_id: int, feature: str) -> int:
    """Count how many times a user used a feature today.

    Feature → table mapping (all existing tables, no changes):
      analyses      → api_analysis  (date column)
      cover_letter  → cover_letters (created_at column, joined to api_analysis for user)
      interview     → interview_questions (created_at, joined)
      roadmap       → learning_roadmap (no timestamp — count distinct analysis_id created today)
    """
    today = date.today().isoformat()
    try:
        with connection.cursor() as cursor:
            if feature == 'analyses':
                cursor.execute(
                    "SELECT COUNT(*) FROM api_analysis WHERE user_id = %s AND date = %s",
                    [user_id, today]
                )
            elif feature == 'cover_letter':
                cursor.execute(
                    """SELECT COUNT(*) FROM cover_letters cl
                       JOIN api_analysis aa ON cl.analysis_id = aa.id
                       WHERE aa.user_id = %s AND DATE(cl.created_at) = %s""",
                    [user_id, today]
                )
            elif feature == 'interview':
                cursor.execute(
                    """SELECT COUNT(DISTINCT cl.analysis_id) FROM interview_questions cl
                       JOIN api_analysis aa ON cl.analysis_id = aa.id
                       WHERE aa.user_id = %s AND DATE(cl.created_at) = %s""",
                    [user_id, today]
                )
            elif feature == 'roadmap':
                cursor.execute(
                    """SELECT COUNT(DISTINCT lr.analysis_id) FROM learning_roadmap lr
                       JOIN api_analysis aa ON lr.analysis_id = aa.id
                       WHERE aa.user_id = %s AND aa.date = %s""",
                    [user_id, today]
                )
            else:
                return 0
            row = cursor.fetchone()
            return row[0] if row else 0
    except Exception as e:
        logger.error(f"get_daily_usage error for feature={feature}: {e}")
        return 0


def check_limit(user, feature: str) -> tuple[bool, str]:
    """Returns (allowed: bool, message: str).
    Call before every AI feature. If allowed=False, return the message to client.
    """
    limits = _get_plan_limits(user)
    limit = limits.get(feature, 999_999)
    used = get_daily_usage(user.id, feature)
    if used >= limit:
        plan_name = "Pro" if limits is PRO_PLAN_LIMITS else "Free"
        return False, (
            f"Daily limit reached ({used}/{limit} {feature} today on {plan_name} plan). "
            f"{'Upgrade to Pro to continue.' if limits is FREE_PLAN_LIMITS else 'Please try again tomorrow.'}"
        )
    return True, ""


# ── Analysis cache ───────────────────────────────────────────────────────────────
def make_content_hash(resume_text: str, jd_text: str) -> str:
    """SHA-256 of truncated resume + jd text (same truncation used in GeminiService)."""
    combined = (resume_text or "")[:3500] + "|" + (jd_text or "")[:2500]
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def find_cached_analysis(user_id: int, resume_id: int, jd_id: int):
    """Look for an existing completed analysis for this user + resume + jd combination.
    Returns the api_analysis row id if found, else None.
    We match on resume_id + jd_id (same resume uploaded to same JD → same content).
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT id FROM api_analysis
                   WHERE user_id = %s AND resume_id = %s AND jd_id = %s
                   AND status = 'Completed'
                   ORDER BY id DESC LIMIT 1""",
                [user_id, resume_id, jd_id]
            )
            row = cursor.fetchone()
            return row[0] if row else None
    except Exception as e:
        logger.error(f"find_cached_analysis error: {e}")
        return None
