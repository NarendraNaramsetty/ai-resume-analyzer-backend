"""
Billing Helpers
---------------
Raw SQL helpers for plans, subscriptions, and payments tables.
No migrations — tables created manually via manage.py shell.
"""
import logging
from datetime import date, timedelta
from django.db import connection

logger = logging.getLogger(__name__)

# ── Plans ────────────────────────────────────────────────────────────────────────

def get_all_plans():
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, name, price, analysis_limit, cover_letter_limit, "
                "downloadable_reports, priority_support, ats_analysis "
                "FROM plans ORDER BY price ASC"
            )
            rows = cursor.fetchall()
            return [_plan_row(r) for r in rows]
    except Exception as e:
        logger.error(f"get_all_plans error: {e}")
        return []

def get_plan_by_id(plan_id):
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, name, price, analysis_limit, cover_letter_limit, "
                "downloadable_reports, priority_support, ats_analysis "
                "FROM plans WHERE id = %s",
                [plan_id]
            )
            row = cursor.fetchone()
            return _plan_row(row) if row else None
    except Exception as e:
        logger.error(f"get_plan_by_id error: {e}")
        return None

def get_plan_by_name(name):
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, name, price, analysis_limit, cover_letter_limit, "
                "downloadable_reports, priority_support, ats_analysis "
                "FROM plans WHERE name = %s",
                [name]
            )
            row = cursor.fetchone()
            return _plan_row(row) if row else None
    except Exception as e:
        logger.error(f"get_plan_by_name error: {e}")
        return None

def _plan_row(row):
    priority_support = bool(row[6])
    return {
        'id': row[0],
        'name': row[1],
        'price': float(row[2]),
        'monthly_analyses': row[3],     # -1 = unlimited
        'monthly_cover_letters': row[4],
        'pdf_reports': bool(row[5]),
        'priority_processing': priority_support,
        'ats_optimization': bool(row[7]),
        'support_level': 'Priority' if priority_support else 'Basic',
    }


# ── Subscriptions ────────────────────────────────────────────────────────────────

def get_active_subscription(user_id):
    """Return the user's active subscription, or None."""
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT s.id, s.user_id, s.plan_id, s.status, s.start_date, "
                "s.expiry_date, s.analyses_used, s.cover_letters_used, s.created_at, "
                "p.name, p.price, p.analysis_limit, p.cover_letter_limit, "
                "p.downloadable_reports, p.priority_support, p.ats_analysis "
                "FROM subscriptions s JOIN plans p ON s.plan_id = p.id "
                "WHERE s.user_id = %s AND s.status = 'active' "
                "ORDER BY s.id DESC LIMIT 1",
                [user_id]
            )
            row = cursor.fetchone()
            return _subscription_row(row) if row else None
    except Exception as e:
        logger.error(f"get_active_subscription error: {e}")
        return None

def ensure_free_subscription(user_id):
    """Create a Free plan subscription for a new user if none exists."""
    try:
        existing = get_active_subscription(user_id)
        if existing:
            return existing
        free_plan = get_plan_by_name('Free')
        if not free_plan:
            return None
        today = date.today()
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO subscriptions (user_id, plan_id, status, start_date, expiry_date) "
                "VALUES (%s, %s, 'active', %s, NULL) "
                "ON DUPLICATE KEY UPDATE status='active'",
                [user_id, free_plan['id'], today]
            )
        return get_active_subscription(user_id)
    except Exception as e:
        logger.error(f"ensure_free_subscription error: {e}")
        return None

def upgrade_subscription(user_id, plan_id, months=1):
    """Upgrade user to a paid plan. Deactivates current active sub first."""
    try:
        today = date.today()
        expiry = today + timedelta(days=30 * months)
        with connection.cursor() as cursor:
            # Deactivate all existing active subscriptions
            cursor.execute(
                "UPDATE subscriptions SET status='expired' WHERE user_id=%s AND status='active'",
                [user_id]
            )
            # Create new active subscription
            cursor.execute(
                "INSERT INTO subscriptions (user_id, plan_id, status, start_date, expiry_date) "
                "VALUES (%s, %s, 'active', %s, %s)",
                [user_id, plan_id, today, expiry]
            )
        return get_active_subscription(user_id)
    except Exception as e:
        logger.error(f"upgrade_subscription error: {e}")
        return None

def increment_usage(user_id, field='analyses_used'):
    """Increment analyses_used or cover_letters_used on the active subscription."""
    allowed = ['analyses_used', 'cover_letters_used']
    if field not in allowed:
        return
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE subscriptions SET {field} = {field} + 1 "
                "WHERE user_id = %s AND status = 'active' ORDER BY id DESC LIMIT 1",
                [user_id]
            )
    except Exception as e:
        logger.error(f"increment_usage error: {e}")

def _subscription_row(row):
    priority_support = bool(row[14])
    return {
        'id': row[0],
        'user_id': row[1],
        'plan_id': row[2],
        'status': row[3],
        'start_date': str(row[4]) if row[4] else None,
        'expiry_date': str(row[5]) if row[5] else None,
        'analyses_used': row[6],
        'cover_letters_used': row[7],
        'created_at': str(row[8]) if row[8] else None,
        'plan': {
            'id': row[2],
            'name': row[9],
            'price': float(row[10]),
            'monthly_analyses': row[11],
            'monthly_cover_letters': row[12],
            'pdf_reports': bool(row[13]),
            'priority_processing': priority_support,
            'ats_optimization': bool(row[15]),
            'support_level': 'Priority' if priority_support else 'Basic',
        }
    }


# ── Payments ─────────────────────────────────────────────────────────────────────

def create_payment(user_id, plan_id, amount):
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO payments (user_id, plan_id, amount, payment_method, status) VALUES (%s, %s, %s, 'upi', 'pending')",
                [user_id, plan_id, amount]
            )
            return cursor.lastrowid
    except Exception as e:
        logger.error(f"create_payment error: {e}")
        raise e

def create_verified_payment(user_id, plan_id, amount, transaction_id, admin_notes):
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO payments (user_id, plan_id, amount, payment_method, transaction_id, status, admin_notes, verified_at) "
                "VALUES (%s, %s, %s, 'upi', %s, 'approved', %s, NOW())",
                [user_id, plan_id, amount, transaction_id, admin_notes]
            )
            return cursor.lastrowid
    except Exception as e:
        logger.error(f"create_verified_payment error: {e}")
        raise e

def update_payment_proof(payment_id, user_id, transaction_id, screenshot_url=None):
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE payments SET transaction_id=%s, screenshot_url=%s "
                "WHERE id=%s AND user_id=%s",
                [transaction_id, screenshot_url, payment_id, user_id]
            )
        return get_payment(payment_id)
    except Exception as e:
        logger.error(f"update_payment_proof error: {e}")
        raise e

def get_payment(payment_id):
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, user_id, plan_id, amount, status, transaction_id, "
                "screenshot_url, admin_notes, created_at, verified_at "
                "FROM payments WHERE id=%s",
                [payment_id]
            )
            row = cursor.fetchone()
            return _payment_row(row) if row else None
    except Exception as e:
        logger.error(f"get_payment error: {e}")
        return None

def get_user_payments(user_id):
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT p.id, p.user_id, p.plan_id, p.amount, p.status, p.transaction_id, "
                "p.screenshot_url, p.admin_notes, p.created_at, p.verified_at, pl.name "
                "FROM payments p JOIN plans pl ON p.plan_id = pl.id "
                "WHERE p.user_id=%s ORDER BY p.id DESC",
                [user_id]
            )
            rows = cursor.fetchall()
            result = []
            for r in rows:
                item = _payment_row(r[:10])
                item['plan_name'] = r[10]
                result.append(item)
            return result
    except Exception as e:
        logger.error(f"get_user_payments error: {e}")
        return []

def verify_payment(payment_id, new_status, admin_note=''):
    """Admin action — approve or reject a payment."""
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE payments SET status=%s, admin_notes=%s WHERE id=%s",
                [new_status, admin_note, payment_id]
            )
        payment = get_payment(payment_id)
        if payment and new_status == 'approved':
            upgrade_subscription(payment['user_id'], payment['plan_id'])
        return payment
    except Exception as e:
        logger.error(f"verify_payment error: {e}")
        raise e

def _payment_row(row):
    return {
        'id': row[0],
        'user_id': row[1],
        'plan_id': row[2],
        'amount': float(row[3]) if row[3] else 0.0,
        'status': row[4],
        'transaction_id': row[5],
        'screenshot_url': row[6],
        'admin_note': row[7],
        'created_at': str(row[8]) if row[8] else None,
        'verified_at': str(row[9]) if row[9] else None,
    }
