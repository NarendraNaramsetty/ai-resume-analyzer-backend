import logging
from django.db import connection

logger = logging.getLogger(__name__)

# Raw SQL operations mapping directly to existing database tables.
# Avoids generating Django migrations or altering existing tables.

def get_cover_letter(analysis_id):
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, analysis_id, cover_letter_text, created_at FROM cover_letters WHERE analysis_id = %s ORDER BY id DESC LIMIT 1", 
                [analysis_id]
            )
            row = cursor.fetchone()
            if row:
                return {
                    'id': row[0],
                    'analysis_id': row[1],
                    'cover_letter_text': row[2],
                    'created_at': row[3]
                }
    except Exception as e:
        logger.error(f"Error in get_cover_letter: {e}")
    return None

def save_cover_letter(analysis_id, cover_letter_text):
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO cover_letters (analysis_id, cover_letter_text) VALUES (%s, %s)", 
                [analysis_id, cover_letter_text]
            )
            return cursor.lastrowid
    except Exception as e:
        logger.error(f"Error in save_cover_letter: {e}")
        raise e

def get_generated_reports(analysis_id):
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, analysis_id, report_name, report_url, report_type, generated_at FROM generated_reports WHERE analysis_id = %s ORDER BY id DESC", 
                [analysis_id]
            )
            rows = cursor.fetchall()
            return [{
                'id': r[0],
                'analysis_id': r[1],
                'report_name': r[2],
                'report_url': r[3],
                'report_type': r[4],
                'generated_at': r[5]
            } for r in rows]
    except Exception as e:
        logger.error(f"Error in get_generated_reports: {e}")
    return []

def save_generated_report(analysis_id, report_name, report_url, report_type):
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO generated_reports (analysis_id, report_name, report_url, report_type) VALUES (%s, %s, %s, %s)", 
                [analysis_id, report_name, report_url, report_type]
            )
            return cursor.lastrowid
    except Exception as e:
        logger.error(f"Error in save_generated_report: {e}")
        raise e

def get_interview_questions(analysis_id):
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, analysis_id, question_type, question, difficulty, created_at FROM interview_questions WHERE analysis_id = %s ORDER BY id ASC", 
                [analysis_id]
            )
            rows = cursor.fetchall()
            return [{
                'id': r[0],
                'analysis_id': r[1],
                'question_type': r[2],
                'question': r[3],
                'difficulty': r[4],
                'created_at': r[5]
            } for r in rows]
    except Exception as e:
        logger.error(f"Error in get_interview_questions: {e}")
    return []

def save_interview_question(analysis_id, question_type, question, difficulty='Medium'):
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO interview_questions (analysis_id, question_type, question, difficulty) VALUES (%s, %s, %s, %s)", 
                [analysis_id, question_type, question, difficulty]
            )
            return cursor.lastrowid
    except Exception as e:
        logger.error(f"Error in save_interview_question: {e}")
        raise e

def get_learning_roadmap(analysis_id):
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, analysis_id, skill_name, learning_order, estimated_days, learning_resource FROM learning_roadmap WHERE analysis_id = %s ORDER BY learning_order ASC", 
                [analysis_id]
            )
            rows = cursor.fetchall()
            return [{
                'id': r[0],
                'analysis_id': r[1],
                'skill_name': r[2],
                'learning_order': r[3],
                'estimated_days': r[4],
                'learning_resource': r[5]
            } for r in rows]
    except Exception as e:
        logger.error(f"Error in get_learning_roadmap: {e}")
    return []

def save_roadmap_item(analysis_id, skill_name, learning_order, estimated_days, learning_resource=''):
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO learning_roadmap (analysis_id, skill_name, learning_order, estimated_days, learning_resource) VALUES (%s, %s, %s, %s, %s)", 
                [analysis_id, skill_name, learning_order, estimated_days, learning_resource]
            )
            return cursor.lastrowid
    except Exception as e:
        logger.error(f"Error in save_roadmap_item: {e}")
        raise e

def get_salary_estimates(analysis_id):
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, analysis_id, role_name, country, experience_level, min_salary, avg_salary, max_salary FROM salary_estimates WHERE analysis_id = %s", 
                [analysis_id]
            )
            rows = cursor.fetchall()
            return [{
                'id': r[0],
                'analysis_id': r[1],
                'role_name': r[2],
                'country': r[3],
                'experience_level': r[4],
                'min_salary': float(r[5]) if r[5] is not None else 0.0,
                'avg_salary': float(r[6]) if r[6] is not None else 0.0,
                'max_salary': float(r[7]) if r[7] is not None else 0.0
            } for r in rows]
    except Exception as e:
        logger.error(f"Error in get_salary_estimates: {e}")
    return []

def save_salary_estimate(analysis_id, role_name, country, experience_level, min_salary, avg_salary, max_salary):
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO salary_estimates (analysis_id, role_name, country, experience_level, min_salary, avg_salary, max_salary) VALUES (%s, %s, %s, %s, %s, %s, %s)", 
                [analysis_id, role_name, country, experience_level, min_salary, avg_salary, max_salary]
            )
            return cursor.lastrowid
    except Exception as e:
        logger.error(f"Error in save_salary_estimate: {e}")
        raise e

def get_similar_jobs(analysis_id):
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, analysis_id, role_name, match_percentage, company_name FROM similar_jobs WHERE analysis_id = %s ORDER BY match_percentage DESC", 
                [analysis_id]
            )
            rows = cursor.fetchall()
            return [{
                'id': r[0],
                'analysis_id': r[1],
                'role_name': r[2],
                'match_percentage': r[3],
                'company_name': r[4]
            } for r in rows]
    except Exception as e:
        logger.error(f"Error in get_similar_jobs: {e}")
    return []

def save_similar_job(analysis_id, role_name, match_percentage, company_name):
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO similar_jobs (analysis_id, role_name, match_percentage, company_name) VALUES (%s, %s, %s, %s)", 
                [analysis_id, role_name, match_percentage, company_name]
            )
            return cursor.lastrowid
    except Exception as e:
        logger.error(f"Error in save_similar_job: {e}")
        raise e

def get_resume_suggestions(analysis_id):
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, analysis_id, suggestion_type, suggestion_text, priority, created_at FROM resume_suggestions WHERE analysis_id = %s ORDER BY id ASC", 
                [analysis_id]
            )
            rows = cursor.fetchall()
            return [{
                'id': r[0],
                'analysis_id': r[1],
                'suggestion_type': r[2],
                'suggestion_text': r[3],
                'priority': r[4],
                'created_at': r[5]
            } for r in rows]
    except Exception as e:
        logger.error(f"Error in get_resume_suggestions: {e}")
    return []

def save_resume_suggestion(analysis_id, suggestion_type, suggestion_text, priority='Medium'):
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO resume_suggestions (analysis_id, suggestion_type, suggestion_text, priority) VALUES (%s, %s, %s, %s)", 
                [analysis_id, suggestion_type, suggestion_text, priority]
            )
            return cursor.lastrowid
    except Exception as e:
        logger.error(f"Error in save_resume_suggestion: {e}")
        raise e

def get_chat_sessions(user_id):
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, user_id, title, created_at FROM chat_sessions WHERE user_id = %s ORDER BY id DESC", 
                [user_id]
            )
            rows = cursor.fetchall()
            return [{
                'id': r[0],
                'user_id': r[1],
                'title': r[2],
                'created_at': r[3]
            } for r in rows]
    except Exception as e:
        logger.error(f"Error in get_chat_sessions: {e}")
    return []

def create_chat_session(user_id, title):
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO chat_sessions (user_id, title) VALUES (%s, %s)", 
                [user_id, title]
            )
            return cursor.lastrowid
    except Exception as e:
        logger.error(f"Error in create_chat_session: {e}")
        raise e

def get_chat_messages(session_id):
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, session_id, role, message, created_at FROM chat_messages WHERE session_id = %s ORDER BY id ASC", 
                [session_id]
            )
            rows = cursor.fetchall()
            return [{
                'id': r[0],
                'session_id': r[1],
                'role': r[2],
                'message': r[3],
                'created_at': r[4]
            } for r in rows]
    except Exception as e:
        logger.error(f"Error in get_chat_messages: {e}")
    return []

def save_chat_message(session_id, role, message):
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO chat_messages (session_id, role, message) VALUES (%s, %s, %s)", 
                [session_id, role, message]
            )
            return cursor.lastrowid
    except Exception as e:
        logger.error(f"Error in save_chat_message: {e}")
        raise e
