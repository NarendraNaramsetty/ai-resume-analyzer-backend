from rest_framework import viewsets, status, generics
from rest_framework.decorators import action
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.authtoken.models import Token
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404
from django.http import StreamingHttpResponse
from django.db import connection
import os
import logging
import hmac
import hashlib
import json
import time
from django.utils import timezone
from datetime import timedelta
from django.core.mail import send_mail
from django.conf import settings

from .models import Analysis, Profile, Resume, JobDescription, Notification, LinkedInProfile
from .serializers import AnalysisSerializer, UserSerializer, ProfileSerializer, ResumeSerializer, JobDescriptionSerializer, NotificationSerializer
from .parser import parse_resume_content
import requests
from services.ollama_service import OllamaService
from services.cache_service import check_limit, find_cached_analysis

from api.db_helpers import (
    get_cover_letter, save_cover_letter, get_generated_reports, save_generated_report,
    get_interview_questions, save_interview_question, get_learning_roadmap, save_roadmap_item,
    get_salary_estimates, save_salary_estimate, get_similar_jobs, save_similar_job,
    get_resume_suggestions, save_resume_suggestion, get_chat_sessions, create_chat_session,
    get_chat_messages, save_chat_message
)
from api.billing_helpers import (
    get_all_plans, get_plan_by_id, get_active_subscription,
    ensure_free_subscription, upgrade_subscription,
    create_payment, update_payment_proof, get_user_payments, verify_payment,
    create_verified_payment
)
from services.pdf_service import generate_ats_pdf

logger = logging.getLogger(__name__)



class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email')
        if not email:
            return Response({'email': ['This field is required.']}, status=status.HTTP_400_BAD_REQUEST)
            
        serializer = UserSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            token, _ = Token.objects.get_or_create(user=user)
            # Auto-assign Free plan
            ensure_free_subscription(user.id)
            return Response({
                'token': token.key,
                'user': UserSerializer(user).data
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')
        
        if username and '@' in username:
            try:
                user_obj = User.objects.get(email=username)
                username = user_obj.username
            except User.DoesNotExist:
                pass

        user = authenticate(username=username, password=password)
        if user:
            token, _ = Token.objects.get_or_create(user=user)
            return Response({
                'token': token.key,
                'user': UserSerializer(user).data
            }, status=status.HTTP_200_OK)
        return Response({'non_field_errors': ['Invalid credentials provided.']}, status=status.HTTP_400_BAD_REQUEST)

class UserProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)

    def put(self, request):
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        if serializer.is_valid():
            user = serializer.save()
            return Response(UserSerializer(user).data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class ResumeUploadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        resume_file = request.FILES.get('resume_file')
        if not resume_file:
            return Response({'resume_file': ['This field is required.']}, status=status.HTTP_400_BAD_REQUEST)

        # Save model
        resume = Resume(
            user=request.user,
            file_name=resume_file.name,
            resume_file=resume_file
        )
        resume.save()

        # Parse text content from saved file
        try:
            file_path = resume.resume_file.path
            raw_text = parse_resume_content(file_path)
            resume.raw_text = raw_text
            resume.save()
        except Exception as e:
            # Save fallback text just in case parsing fails
            resume.raw_text = f"Parsing fallback. File: {resume.file_name}."
            resume.save()

        serializer = ResumeSerializer(resume)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

class JobDescriptionCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        title = request.data.get('title', 'Target Role')
        raw_text = request.data.get('raw_text', '')

        if not raw_text:
            return Response({'raw_text': ['This field is required.']}, status=status.HTTP_400_BAD_REQUEST)

        jd = JobDescription(
            user=request.user,
            title=title,
            raw_text=raw_text
        )
        jd.save()

        serializer = JobDescriptionSerializer(jd)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

class AnalyzeResumeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        resume_id = request.data.get('resume_id')
        jd_id = request.data.get('jd_id')

        if not resume_id or not jd_id:
            return Response({'detail': 'Both resume_id and jd_id are required fields.'}, status=status.HTTP_400_BAD_REQUEST)

        resume = get_object_or_404(Resume, id=resume_id, user=request.user)
        jd = get_object_or_404(JobDescription, id=jd_id, user=request.user)

        # ── Feature 1: Return cached analysis if same resume+jd already processed ──
        cached_id = find_cached_analysis(request.user.id, resume.id, jd.id)
        if cached_id:
            try:
                cached = Analysis.objects.get(id=cached_id)
                logger.info(f"Cache hit: returning existing analysis id={cached_id} for user={request.user.id}")
                return Response(AnalysisSerializer(cached).data, status=status.HTTP_200_OK)
            except Analysis.DoesNotExist:
                pass  # cache stale — proceed to generate

        # ── Feature 4: Daily usage limit check ────────────────────────────────────
        allowed, msg = check_limit(request.user, 'analyses')
        if not allowed:
            return Response({'detail': msg}, status=status.HTTP_429_TOO_MANY_REQUESTS)

        # ── Call Ollama ────────────────────────────────────────────────────────────
        ollama = OllamaService()
        try:
            evaluation = ollama.analyze_resume(resume.raw_text, jd.raw_text)

            # Map the Llama3 output to the fields expected by views / model
            recruiter_summary = evaluation.get('professional_summary') or evaluation.get('recruiter_summary', '')
            ats_score = evaluation.get('ats_score', 80)
            matched_skills = evaluation.get('technical_skills') or evaluation.get('matched_skills', [])
            missing_skills = evaluation.get('missing_skills', [])
            strengths = evaluation.get('strengths', [])
            weaknesses = evaluation.get('weaknesses', [])
            improvements = evaluation.get('suggestions') or evaluation.get('resume_improvements', [])

            recommended_roles = evaluation.get('recommended_roles', [])
            legacy_suitability = recommended_roles if isinstance(recommended_roles, list) else []
            
            job_suitability = evaluation.get('job_suitability', {})
            if not job_suitability and recommended_roles:
                primary_role = recommended_roles[0] if recommended_roles else {}
                alternative_roles = recommended_roles[1:] if len(recommended_roles) > 1 else []
                job_suitability = {
                    'primary_role': primary_role,
                    'alternative_roles': alternative_roles
                }

            skill_gap_analysis = evaluation.get('skill_gap_analysis', {})
            if not skill_gap_analysis:
                skill_gap_analysis = {
                    'critical_missing_skills': missing_skills[:3],
                    'recommended_learning_path': improvements
                }
            recommended_learning_path = skill_gap_analysis.get('recommended_learning_path', [])

            keywords = []
            for skill in matched_skills:
                keywords.append({'word': skill, 'found': True, 'importance': 'High'})
            for skill in missing_skills:
                keywords.append({'word': skill, 'found': False, 'importance': 'High'})

            analysis = Analysis(
                user=request.user,
                resume=resume,
                jd=jd,
                file_name=resume.file_name,
                role=jd.title,
                ats_score=ats_score,
                job_match_score=ats_score,
                matched_skills=matched_skills,
                missing_skills=missing_skills,
                suitability=legacy_suitability,
                radar_data=evaluation.get('radar_data', []),
                strengths=strengths,
                weaknesses=weaknesses,
                improvements=improvements,
                recommendations=recommended_learning_path,
                keywords=keywords,
                verdict=evaluation.get('verdict') or (ats_score >= 80 and 'High Potential Match' or 'Moderate Match'),
                recruiter_summary=recruiter_summary,
                experience_analysis=evaluation.get('experience_analysis', {}),
                project_analysis=evaluation.get('project_analysis', []),
                job_suitability=job_suitability,
                skill_gap_analysis=skill_gap_analysis,
                technical_questions=evaluation.get('technical_questions', []),
                hr_questions=evaluation.get('hr_questions', []),
                project_questions=evaluation.get('project_questions', []),
                status='Completed'
            )
            analysis.save()

            Notification.objects.create(
                user=request.user,
                title="Analysis Complete",
                message=f"Resume analysis for \"{analysis.file_name}\" is complete with {analysis.ats_score}% score!",
                type="success",
                redirect_url="/result"
            )
            if analysis.missing_skills:
                skills_str = " and ".join(analysis.missing_skills[:2])
                Notification.objects.create(
                    user=request.user,
                    title="Missing Skills Alert",
                    message=f"Alert: \"{skills_str}\" are high-importance missing skills on your resume.",
                    type="warning",
                    redirect_url="/result"
                )

            return Response(AnalysisSerializer(analysis).data, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.error(f"AnalyzeResumeView error: {e}")
            return Response(
                {'detail': str(e) if str(e) else 'AI service is currently busy. Please try again in a few minutes.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )

class UsageLimitsView(APIView):
    """Returns today's usage vs limits for all features. Used by frontend to show quota."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from services.cache_service import get_daily_usage, _get_plan_limits, FREE_PLAN_LIMITS
        limits = _get_plan_limits(request.user)
        plan = 'pro' if limits is not FREE_PLAN_LIMITS else 'free'
        features = ['analyses', 'cover_letter', 'interview', 'roadmap']
        data = {'plan': plan}
        for f in features:
            used = get_daily_usage(request.user.id, f)
            limit = limits.get(f, 999)
            data[f] = {'used': used, 'limit': limit, 'remaining': max(0, limit - used)}
        return Response(data, status=status.HTTP_200_OK)


class OptimizeResumeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        resume_text = request.data.get('resume_text', '')
        jd_text = request.data.get('jd_text', '')

        if not resume_text or not jd_text:
            return Response({'detail': 'Both resume_text and jd_text are required fields.'}, status=status.HTTP_400_BAD_REQUEST)

        # Invoke Ollama service optimizer
        ollama = OllamaService()
        try:
            optimized_data = ollama.optimize_resume(resume_text, jd_text)
            return Response(optimized_data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'detail': f'AI Optimization processing failed: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class AnalysisViewSet(viewsets.ModelViewSet):
    serializer_class = AnalysisSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Analysis.objects.filter(user=self.request.user)

class NotificationViewSet(viewsets.ModelViewSet):
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)

    @action(detail=False, methods=['post'], url_path='mark-all-read')
    def mark_all_read(self, request):
        Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
        return Response({'status': 'all notifications marked as read'})

    @action(detail=False, methods=['delete'], url_path='clear-all')
    def clear_all(self, request):
        Notification.objects.filter(user=request.user).delete()
        return Response({'status': 'all notifications cleared'})

class CoverLetterGenerateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        analysis_id = request.data.get('analysisId')
        if not analysis_id:
            return Response({'detail': 'analysisId is required.'}, status=status.HTTP_400_BAD_REQUEST)

        analysis = get_object_or_404(Analysis, id=analysis_id, user=request.user)

        # ── Feature 3: Cache-first ─────────────────────────────────────────────
        cached = get_cover_letter(analysis.id)
        if cached:
            return Response({'cover_letter': cached['cover_letter_text']}, status=status.HTTP_200_OK)

        # ── Feature 4: Daily limit ─────────────────────────────────────────────
        allowed, msg = check_limit(request.user, 'cover_letter')
        if not allowed:
            return Response({'detail': msg}, status=status.HTTP_429_TOO_MANY_REQUESTS)

        resume = analysis.resume
        jd = analysis.jd
        if not resume or not jd:
            return Response({'detail': 'Analysis must have both a resume and job description.'}, status=status.HTTP_400_BAD_REQUEST)

        ollama = OllamaService()
        try:
            cover_letter = ollama.generate_cover_letter(
                resume_text=resume.raw_text,
                jd_text=jd.raw_text,
                company_name="Target Company",
                job_role=jd.title,
                # compact context
                candidate_name=request.user.get_full_name() or request.user.username,
                ats_score=analysis.ats_score,
                matched_skills=analysis.matched_skills,
            )
            save_cover_letter(analysis.id, cover_letter)
            return Response({'cover_letter': cover_letter}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"CoverLetterGenerateView error: {e}")
            return Response({'detail': str(e)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)


class ReportGeneratePDFView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        analysis_id = request.data.get('analysisId')
        if not analysis_id:
            return Response({'detail': 'analysisId is required.'}, status=status.HTTP_400_BAD_REQUEST)
        
        analysis = get_object_or_404(Analysis, id=analysis_id, user=request.user)
        
        try:
            report_url = generate_ats_pdf(analysis.id)
            return Response({'report_url': report_url}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'detail': f'Failed to generate PDF report: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class InterviewQuestionsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, analysis_id):
        analysis = get_object_or_404(Analysis, id=analysis_id, user=request.user)

        # ── Feature 3: Cache-first ─────────────────────────────────────────────
        questions = get_interview_questions(analysis.id)
        if questions:
            grouped = {
                'technical': [q for q in questions if q['question_type'] == 'technical'],
                'hr': [q for q in questions if q['question_type'] == 'hr'],
                'project': [q for q in questions if q['question_type'] == 'project'],
            }
            return Response(grouped, status=status.HTTP_200_OK)

        # ── Feature 4: Daily limit ─────────────────────────────────────────────
        allowed, msg = check_limit(request.user, 'interview')
        if not allowed:
            return Response({'detail': msg}, status=status.HTTP_429_TOO_MANY_REQUESTS)

        # Questions are already stored on the Analysis from the initial generation
        for q in (analysis.technical_questions or []):
            save_interview_question(analysis.id, 'technical', q, 'Medium')
        for q in (analysis.hr_questions or []):
            save_interview_question(analysis.id, 'hr', q, 'Medium')
        for q in (analysis.project_questions or []):
            save_interview_question(analysis.id, 'project', q, 'Medium')

        questions = get_interview_questions(analysis.id)
        grouped = {
            'technical': [q for q in questions if q['question_type'] == 'technical'],
            'hr': [q for q in questions if q['question_type'] == 'hr'],
            'project': [q for q in questions if q['question_type'] == 'project'],
        }
        return Response(grouped, status=status.HTTP_200_OK)


class LearningRoadmapView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, analysis_id):
        analysis = get_object_or_404(Analysis, id=analysis_id, user=request.user)

        # ── Feature 3: Cache-first ─────────────────────────────────────────────
        roadmap = get_learning_roadmap(analysis.id)
        if roadmap:
            return Response(roadmap, status=status.HTTP_200_OK)

        # ── Feature 4: Daily limit ─────────────────────────────────────────────
        allowed, msg = check_limit(request.user, 'roadmap')
        if not allowed:
            return Response({'detail': msg}, status=status.HTTP_429_TOO_MANY_REQUESTS)

        ollama = OllamaService()
        try:
            items = ollama.generate_learning_roadmap(
                missing_skills=analysis.missing_skills,
                jd_text=analysis.jd.raw_text if analysis.jd else "",
                target_role=analysis.role,
            )
            for item in items:
                save_roadmap_item(
                    analysis.id,
                    item.get('skill_name'),
                    item.get('learning_order'),
                    item.get('estimated_days'),
                    item.get('learning_resource', '')
                )
            return Response(get_learning_roadmap(analysis.id), status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"LearningRoadmapView error: {e}")
            return Response({'detail': str(e)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)


class SalaryEstimationView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, analysis_id):
        analysis = get_object_or_404(Analysis, id=analysis_id, user=request.user)

        estimates = get_salary_estimates(analysis.id)
        if estimates:
            return Response(estimates[0], status=status.HTTP_200_OK)

        ollama = OllamaService()
        try:
            est = ollama.generate_salary_estimates(
                role=analysis.role,
                country="United States",
                experience_level="Mid-level",
                skill_set=analysis.matched_skills,
            )
            save_salary_estimate(
                analysis.id,
                est.get('role_name', analysis.role),
                est.get('country', 'United States'),
                est.get('experience_level', 'Mid-level'),
                est.get('min_salary', 80000),
                est.get('avg_salary', 110000),
                est.get('max_salary', 140000)
            )
            estimates = get_salary_estimates(analysis.id)
            return Response(estimates[0] if estimates else {}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"SalaryEstimationView error: {e}")
            return Response({'detail': str(e)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)


class SimilarJobsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, analysis_id):
        analysis = get_object_or_404(Analysis, id=analysis_id, user=request.user)

        jobs = get_similar_jobs(analysis.id)
        if jobs:
            return Response(jobs, status=status.HTTP_200_OK)

        ollama = OllamaService()
        try:
            recs = ollama.generate_similar_jobs(
                role=analysis.role,
                skill_set=analysis.matched_skills,
            )
            for r in recs:
                save_similar_job(analysis.id, r.get('role_name'), r.get('match_percentage'), r.get('company_name'))
            return Response(get_similar_jobs(analysis.id), status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"SimilarJobsView error: {e}")
            return Response({'detail': str(e)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)


class ResumeSuggestionsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, analysis_id):
        analysis = get_object_or_404(Analysis, id=analysis_id, user=request.user)

        suggestions = get_resume_suggestions(analysis.id)
        if suggestions:
            grouped = {
                'high': [s for s in suggestions if s['priority'].lower() == 'high'],
                'medium': [s for s in suggestions if s['priority'].lower() == 'medium'],
                'low': [s for s in suggestions if s['priority'].lower() == 'low'],
            }
            return Response(grouped, status=status.HTTP_200_OK)

        ollama = OllamaService()
        try:
            suggs = ollama.generate_resume_suggestions(
                resume_text=analysis.resume.raw_text if analysis.resume else "",
                jd_text=analysis.jd.raw_text if analysis.jd else "",
                missing_skills=analysis.missing_skills,
                target_role=analysis.role,
            )
            for s in suggs:
                save_resume_suggestion(analysis.id, s.get('suggestion_type'), s.get('suggestion_text'), s.get('priority'))
            suggestions = get_resume_suggestions(analysis.id)
            grouped = {
                'high': [s for s in suggestions if s['priority'].lower() == 'high'],
                'medium': [s for s in suggestions if s['priority'].lower() == 'medium'],
                'low': [s for s in suggestions if s['priority'].lower() == 'low'],
            }
            return Response(grouped, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"ResumeSuggestionsView error: {e}")
            return Response({'detail': str(e)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)


class ChatSessionsListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        sessions = get_chat_sessions(request.user.id)
        return Response(sessions, status=status.HTTP_200_OK)

    def post(self, request):
        title = request.data.get('title', 'New Chat Session')
        try:
            session_id = create_chat_session(request.user.id, title)
            return Response({'id': session_id, 'title': title}, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({'detail': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ChatHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, session_id):
        messages = get_chat_messages(session_id)
        return Response(messages, status=status.HTTP_200_OK)


class ChatMessageView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        message = request.data.get('message')
        session_id = request.data.get('sessionId')
        analysis_id = request.data.get('analysisId')

        if not message or not analysis_id:
            return Response({'detail': 'message and analysisId are required fields.'}, status=status.HTTP_400_BAD_REQUEST)

        analysis = get_object_or_404(Analysis, id=analysis_id, user=request.user)
        resume = analysis.resume
        jd = analysis.jd

        if not resume or not jd:
            return Response({'detail': 'Analysis must have both a resume and a job description for chatbot context.'}, status=status.HTTP_400_BAD_REQUEST)

        if not session_id:
            session_title = f"Coach Session - {analysis.file_name}"
            session_id = create_chat_session(request.user.id, session_title)

        db_messages = get_chat_messages(session_id)
        chat_history = [{'role': m['role'], 'message': m['message']} for m in db_messages]

        def response_generator():
            ollama = OllamaService()
            coach_reply = ""
            for text_chunk in ollama.generate_chat_reply_stream(
                chat_history=chat_history,
                user_message=message,
                resume_text=resume.raw_text,
                jd_text=jd.raw_text,
                # compact context
                candidate_name=request.user.get_full_name() or request.user.username,
                ats_score=analysis.ats_score,
                matched_skills=analysis.matched_skills,
                missing_skills=analysis.missing_skills,
                target_role=analysis.role,
            ):
                coach_reply += text_chunk
                yield text_chunk

            save_chat_message(session_id, 'user', message)
            save_chat_message(session_id, 'model', coach_reply)

        return StreamingHttpResponse(response_generator(), content_type='text/plain')

# ── Billing Views ─────────────────────────────────────────────────────────────────

# Helper to enrich subscription response with flat keys
def _enrich_subscription_response(sub):
    if not sub:
        return {}
    analyses_limit = sub['plan']['monthly_analyses']
    cover_letters_limit = sub['plan']['monthly_cover_letters']
    
    analyses_remaining = -1 if analyses_limit == -1 else max(0, analyses_limit - sub['analyses_used'])
    cover_letters_remaining = -1 if cover_letters_limit == -1 else max(0, cover_letters_limit - sub['cover_letters_used'])
    
    enriched = dict(sub)
    enriched.update({
        'plan_name': sub['plan']['name'],
        'planName': sub['plan']['name'],
        'expiry_date': sub['expiry_date'],
        'expiryDate': sub['expiry_date'],
        'analyses_used': sub['analyses_used'],
        'analysesUsed': sub['analyses_used'],
        'analyses_remaining': analyses_remaining,
        'analysesRemaining': analyses_remaining,
        'cover_letters_remaining': cover_letters_remaining,
        'coverLettersRemaining': cover_letters_remaining,
    })
    return enriched


class PlansListView(APIView):
    """GET /api/plans/ — returns all available plans."""
    permission_classes = [AllowAny]

    def get(self, request):
        plans = get_all_plans()
        return Response(plans, status=status.HTTP_200_OK)


class SubscriptionCurrentView(APIView):
    """GET /api/subscription/current/ — returns user's active subscription."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        sub = get_active_subscription(request.user.id)
        if not sub:
            sub = ensure_free_subscription(request.user.id)
        if not sub:
            return Response({'detail': 'No active subscription found.'}, status=status.HTTP_404_NOT_FOUND)
        
        # Check if subscription is expiring in <= 7 days, and auto-notify
        if sub['expiry_date'] and sub['status'] == 'active':
            from datetime import datetime, date, timedelta
            try:
                if isinstance(sub['expiry_date'], str):
                    expiry_date = datetime.strptime(sub['expiry_date'].split(' ')[0], '%Y-%m-%d').date()
                elif isinstance(sub['expiry_date'], (datetime, date)):
                    expiry_date = sub['expiry_date']
                    if isinstance(expiry_date, datetime):
                        expiry_date = expiry_date.date()
                else:
                    expiry_date = None
                
                if expiry_date:
                    days_left = (expiry_date - date.today()).days
                    if 0 <= days_left <= 7:
                        already_notified = Notification.objects.filter(
                            user=request.user,
                            title="Subscription Expiring Soon",
                            created_at__gte=timezone.now() - timedelta(days=7)
                        ).exists()
                        if not already_notified:
                            Notification.objects.create(
                                user=request.user,
                                title="Subscription Expiring Soon",
                                message=f"Your {sub['plan']['name']} subscription is expiring in {days_left} days on {expiry_date}.",
                                type="warning",
                                redirect_url="/billing"
                            )
            except Exception as e:
                logger.error(f"Expiry notification check error: {e}")

        response_data = _enrich_subscription_response(sub)
        return Response(response_data, status=status.HTTP_200_OK)


class PaymentsHistoryView(APIView):
    """GET /api/payments/history/ — user's payment history."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        payments = get_user_payments(request.user.id)
        return Response(payments, status=status.HTTP_200_OK)


class PaymentCreateView(APIView):
    """POST /api/payments/create/ — initiate a payment for a plan."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        plan_id = request.data.get('plan_id')
        if not plan_id:
            return Response({'detail': 'plan_id is required.'}, status=status.HTTP_400_BAD_REQUEST)

        plan = get_plan_by_id(plan_id)
        if not plan:
            return Response({'detail': 'Plan not found.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            payment_id = create_payment(request.user.id, plan_id, plan['price'])
            payment = {'id': payment_id, 'plan': plan, 'amount': plan['price'], 'status': 'pending'}

            # Notify user
            Notification.objects.create(
                user=request.user,
                title="Payment Submitted",
                message=f"Your payment of ₹{plan['price']:.0f} for {plan['name']} plan has been submitted and is pending verification.",
                type="info",
                redirect_url="/billing"
            )
            return Response(payment, status=status.HTTP_201_CREATED)
        except Exception as e:
            logger.error(f"PaymentCreateView error: {e}")
            return Response({'detail': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



class PaymentUploadProofView(APIView):
    """POST /api/payments/upload-proof/ — upload transaction ID and screenshot."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        payment_id = request.data.get('payment_id')
        transaction_id = request.data.get('transaction_id', '')
        screenshot = request.FILES.get('screenshot')

        if not payment_id or not transaction_id:
            return Response({'detail': 'payment_id and transaction_id are required.'}, status=status.HTTP_400_BAD_REQUEST)

        screenshot_url = None
        if screenshot:
            import os
            from django.conf import settings
            upload_dir = os.path.join(settings.MEDIA_ROOT, 'payment_proofs')
            os.makedirs(upload_dir, exist_ok=True)
            file_path = os.path.join(upload_dir, f"proof_{payment_id}_{screenshot.name}")
            with open(file_path, 'wb+') as f:
                for chunk in screenshot.chunks():
                    f.write(chunk)
            screenshot_url = f"/media/payment_proofs/proof_{payment_id}_{screenshot.name}"

        try:
            payment = update_payment_proof(payment_id, request.user.id, transaction_id, screenshot_url)
            return Response(payment, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"PaymentUploadProofView error: {e}")
            return Response({'detail': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class PaymentVerifyView(APIView):
    """
    PUT /api/payments/verify/ — admin approves or rejects a payment.
    """
    permission_classes = [IsAuthenticated]

    def put(self, request):
        # Simple admin check: only superusers can verify
        if not request.user.is_staff:
            return Response({'detail': 'Admin access required.'}, status=status.HTTP_403_FORBIDDEN)

        payment_id = request.data.get('payment_id')
        new_status = request.data.get('status')  # 'approved' or 'rejected'
        admin_note = request.data.get('admin_note', '')

        if not payment_id or new_status not in ('approved', 'rejected'):
            return Response({'detail': 'payment_id and status (approved/rejected) are required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            payment = verify_payment(payment_id, new_status, admin_note)
            if not payment:
                return Response({'detail': 'Payment not found.'}, status=status.HTTP_404_NOT_FOUND)

            # Notify the user
            target_user = User.objects.filter(id=payment['user_id']).first()
            if target_user:
                if new_status == 'approved':
                    plan = get_plan_by_id(payment['plan_id'])
                    Notification.objects.create(
                        user=target_user,
                        title="Payment Approved!",
                        message=f"Your payment has been approved. Your subscription has been upgraded to {plan['name'] if plan else 'new'} plan.",
                        type="success",
                        redirect_url="/billing"
                    )
                else:
                    Notification.objects.create(
                        user=target_user,
                        title="Payment Rejected",
                        message=f"Your payment was rejected. Reason: {admin_note or 'Please contact support.'}",
                        type="error",
                        redirect_url="/billing"
                    )
            return Response(payment, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"PaymentVerifyView error: {e}")
            return Response({'detail': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AdminStatsView(APIView):
    """GET /api/admin/stats/ — return overview dashboard metrics."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not request.user.is_staff:
            return Response({'detail': 'Admin access required.'}, status=status.HTTP_403_FORBIDDEN)

        from django.db.models import Avg, Count
        from datetime import timedelta
        from django.db import connection

        # Overview Stats
        total_users = User.objects.filter(is_staff=False).count()
        total_analyses = Analysis.objects.count()
        
        total_reports = 0
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM generated_reports")
                total_reports = cursor.fetchone()[0]
        except Exception:
            pass

        active_subs = 0
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM subscriptions WHERE status='active'")
                active_subs = cursor.fetchone()[0]
        except Exception:
            pass

        total_revenue = 0.0
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT SUM(amount) FROM payments WHERE status='approved'")
                val = cursor.fetchone()[0]
                total_revenue = float(val) if val else 0.0
        except Exception:
            pass

        # Active users (logged in within last 30 days)
        active_users = User.objects.filter(
            last_login__gte=timezone.now() - timedelta(days=30)
        ).count()

        # AI API Management (Ollama Local)
        ollama_url = os.getenv("OLLAMA_API_URL", "http://localhost:11434")
        try:
            res = requests.get(ollama_url, timeout=1.5)
            api_key_status = 'Active (Local)' if res.status_code == 200 else 'Error'
        except Exception:
            api_key_status = 'Not Running'
        
        now = timezone.now()
        current_month_requests = Analysis.objects.filter(
            date__month=now.month,
            date__year=now.year
        ).count()
        remaining_requests = max(0, 1000 - current_month_requests)
        monthly_tokens = current_month_requests * 1500

        failed_analyses = Analysis.objects.filter(status='Failed').count()
        error_rate = 0.0
        if total_analyses > 0:
            error_rate = round((failed_analyses / total_analyses) * 100, 1)

        # Plan counts
        free_count = 0
        pro_count = 0
        ent_count = 0
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT plan_id, COUNT(*) FROM subscriptions WHERE status='active' GROUP BY plan_id")
                rows = cursor.fetchall()
                for r in rows:
                    if r[0] == 1: free_count = r[1]
                    elif r[0] == 2: pro_count = r[1]
                    elif r[0] == 3: ent_count = r[1]
        except Exception:
            pass

        # Expiring subscriptions (in next 30 days)
        expiring_count = 0
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM subscriptions WHERE status='active' AND expiry_date BETWEEN NOW() AND DATE_ADD(NOW(), INTERVAL 30 DAY)")
                expiring_count = cursor.fetchone()[0]
        except Exception:
            pass

        # Resume Analytics
        avg_ats = Analysis.objects.aggregate(avg=Avg('ats_score'))['avg'] or 0.0
        avg_ats = round(float(avg_ats), 1)

        # Most analyzed job roles
        top_roles = list(
            Analysis.objects.values('role')
            .annotate(count=Count('role'))
            .order_by('-count')[:5]
        )
        
        # Most common missing skills (aggregate from analyses)
        missing_skills_freq = {}
        for an in Analysis.objects.only('missing_skills'):
            if isinstance(an.missing_skills, list):
                for s in an.missing_skills:
                    if s:
                        missing_skills_freq[s] = missing_skills_freq.get(s, 0) + 1
        sorted_skills = sorted(missing_skills_freq.items(), key=lambda x: x[1], reverse=True)[:5]
        top_missing_skills = [{'skill': s[0], 'count': s[1]} for s in sorted_skills]

        # Payment transactions overview
        total_payments = 0
        pending_payments = 0
        failed_payments = 0
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT status, COUNT(*) FROM payments GROUP BY status")
                rows = cursor.fetchall()
                for r in rows:
                    total_payments += r[1]
                    if r[0] == 'pending': pending_payments = r[1]
                    elif r[0] == 'rejected': failed_payments = r[1]
        except Exception:
            pass

        # Submissions for verification (pending proofs to display)
        pending_upi_proofs = []
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT p.id, p.user_id, p.plan_id, p.amount, p.status, p.transaction_id, "
                    "p.screenshot_url, p.created_at, pl.name, u.username, u.email "
                    "FROM payments p JOIN plans pl ON p.plan_id = pl.id "
                    "JOIN auth_user u ON p.user_id = u.id "
                    "WHERE p.status='pending' ORDER BY p.id DESC"
                )
                rows = cursor.fetchall()
                for r in rows:
                    pending_upi_proofs.append({
                        'id': r[0],
                        'userId': r[1],
                        'planId': r[2],
                        'amount': float(r[3]),
                        'status': r[4],
                        'transactionId': r[5],
                        'screenshotUrl': r[6],
                        'createdAt': str(r[7]),
                        'planName': r[8],
                        'username': r[9],
                        'email': r[10]
                    })
        except Exception as e:
            logger.error(f"Error fetching pending upi proofs: {e}")

        return Response({
            'overview': {
                'totalUsers': total_users,
                'totalAnalyses': total_analyses,
                'totalReports': total_reports,
                'activeSubscriptions': active_subs,
                'totalRevenue': total_revenue,
                'activeUsers': active_users,
            },
            'api_management': {
                'provider': 'Ollama (Llama 3)',
                'status': api_key_status,
                'requestsUsed': current_month_requests,
                'quota': 1000,
                'remaining': remaining_requests,
                'tokenUsage': monthly_tokens,
                'errorRate': error_rate
            },
            'subscriptions': {
                'free': free_count,
                'pro': pro_count,
                'enterprise': ent_count,
                'expiring': expiring_count
            },
            'resume_analytics': {
                'totalUploads': total_analyses,
                'averageAts': avg_ats,
                'topRoles': top_roles,
                'topMissingSkills': top_missing_skills
            },
            'payments': {
                'totalTransactions': total_payments,
                'pendingPayments': pending_payments,
                'failedPayments': failed_payments,
                'pendingProofs': pending_upi_proofs
            }
        }, status=status.HTTP_200_OK)


class AdminUsersView(APIView):
    """GET /api/admin/users/ — list all non-admin users with query search."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not request.user.is_staff:
            return Response({'detail': 'Admin access required.'}, status=status.HTTP_403_FORBIDDEN)

        search_query = request.query_params.get('search', '').strip()
        users = User.objects.filter(is_staff=False)
        if search_query:
            from django.db.models import Q
            users = users.filter(
                Q(username__icontains=search_query) |
                Q(email__icontains=search_query) |
                Q(first_name__icontains=search_query) |
                Q(last_name__icontains=search_query)
            )

        user_list = []
        for u in users:
            sub = get_active_subscription(u.id)
            plan_name = sub['plan']['name'] if sub else 'Free'
            
            user_list.append({
                'id': u.id,
                'username': u.username,
                'email': u.email,
                'name': f"{u.first_name} {u.last_name}".strip() or u.username,
                'plan': plan_name,
                'is_active': u.is_active,
                'date_joined': u.date_joined.strftime('%Y-%m-%d'),
                'last_login': u.last_login.strftime('%Y-%m-%d %H:%M') if u.last_login else 'Never'
            })

        return Response(user_list, status=status.HTTP_200_OK)


class AdminUserActionView(APIView):
    """POST /api/admin/users/action/ — administrative controls on users."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not request.user.is_staff:
            return Response({'detail': 'Admin access required.'}, status=status.HTTP_403_FORBIDDEN)

        user_id = request.data.get('userId')
        action = request.data.get('action')  # 'suspend', 'activate', 'delete', 'upgrade_plan'
        plan_id = request.data.get('planId')

        if not user_id or not action:
            return Response({'detail': 'userId and action are required.'}, status=status.HTTP_400_BAD_REQUEST)

        target_user = get_object_or_404(User, id=user_id)

        if action == 'suspend':
            target_user.is_active = False
            target_user.save()
            return Response({'success': True, 'detail': f"User {target_user.username} suspended."})
            
        elif action == 'activate':
            target_user.is_active = True
            target_user.save()
            return Response({'success': True, 'detail': f"User {target_user.username} activated."})
            
        elif action == 'delete':
            username = target_user.username
            target_user.delete()
            return Response({'success': True, 'detail': f"User {username} deleted."})
            
        elif action == 'upgrade_plan':
            if not plan_id:
                return Response({'detail': 'planId is required for upgrade_plan action.'}, status=status.HTTP_400_BAD_REQUEST)
            sub = upgrade_subscription(target_user.id, plan_id)
            if sub:
                plan_name = sub['plan']['name']
                Notification.objects.create(
                    user=target_user,
                    title="Subscription Adjusted",
                    message=f"Your subscription plan has been updated to {plan_name} by an administrator.",
                    type="info",
                    redirect_url="/billing"
                )
                return Response({'success': True, 'detail': f"User plan updated to {plan_name}."})
            else:
                return Response({'detail': 'Failed to adjust user subscription.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({'detail': f"Unknown action: {action}"}, status=status.HTTP_400_BAD_REQUEST)


class AdminBroadcastNotificationView(APIView):
    """POST /api/admin/notifications/broadcast/ — system alert broadcasting."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not request.user.is_staff:
            return Response({'detail': 'Admin access required.'}, status=status.HTTP_403_FORBIDDEN)

        message = request.data.get('message', '').strip()
        title = request.data.get('title', 'System Announcement').strip()
        target_user_id = request.data.get('userId')

        if not message or not title:
            return Response({'detail': 'title and message are required.'}, status=status.HTTP_400_BAD_REQUEST)

        if target_user_id:
            target_user = get_object_or_404(User, id=target_user_id)
            Notification.objects.create(
                user=target_user,
                title=title,
                message=message,
                type="info",
                redirect_url="/dashboard"
            )
            return Response({'success': True, 'detail': f"Notification sent to {target_user.username}."})
        else:
            users = User.objects.filter(is_staff=False)
            notifications = []
            for u in users:
                notifications.append(Notification(
                    user=u,
                    title=title,
                    message=message,
                    type="info",
                    redirect_url="/dashboard"
                ))
            Notification.objects.bulk_create(notifications)
            return Response({'success': True, 'detail': f"Notification broadcasted to {users.count()} users."})


# ── Razorpay Payment Integration Views ─────────────────────────────────────────────

class RazorpayCreateOrderView(APIView):
    """POST /api/payment/create-order — Create Razorpay order for payment."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            import razorpay
            from dotenv import load_dotenv
            load_dotenv()

            razorpay_key_id = os.getenv('RAZORPAY_KEY_ID')
            razorpay_key_secret = os.getenv('RAZORPAY_KEY_SECRET')

            if not razorpay_key_id or not razorpay_key_secret:
                return Response({'detail': 'Razorpay credentials not configured.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            plan_id = request.data.get('plan_id')
            if not plan_id:
                return Response({'detail': 'plan_id is required.'}, status=status.HTTP_400_BAD_REQUEST)

            plan = get_plan_by_id(plan_id)
            if not plan:
                return Response({'detail': 'Plan not found.'}, status=status.HTTP_404_NOT_FOUND)

            # Convert amount to paise (Razorpay uses smallest currency unit)
            amount_in_paise = int(plan['price'] * 100)
            receipt = f"receipt_{request.user.id}_{plan_id}_{int(time.time())}"

            # Initialize Razorpay client
            client = razorpay.Client(auth=(razorpay_key_id, razorpay_key_secret))

            # Create Razorpay order
            order_data = {
                'amount': amount_in_paise,
                'currency': 'INR',
                'receipt': receipt,
                'notes': {
                    'user_id': request.user.id,
                    'plan_id': plan_id,
                    'plan_name': plan['name']
                }
            }

            razorpay_order = client.order.create(data=order_data)

            # Create pending payment record in database
            payment_id = create_payment(request.user.id, plan_id, plan['price'])

            return Response({
                'razorpay_order_id': razorpay_order['id'],
                'amount': razorpay_order['amount'],
                'currency': razorpay_order['currency'],
                'key_id': razorpay_key_id,
                'payment_id': payment_id,
                'plan': plan
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.error(f"RazorpayCreateOrderView error: {e}")
            return Response({'detail': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class RazorpayVerifyView(APIView):
    """POST /api/payment/verify — Verify Razorpay payment signature."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            import razorpay
            from dotenv import load_dotenv
            load_dotenv()

            razorpay_key_secret = os.getenv('RAZORPAY_KEY_SECRET')
            if not razorpay_key_secret:
                return Response({'detail': 'Razorpay credentials not configured.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            razorpay_order_id = request.data.get('razorpay_order_id')
            razorpay_payment_id = request.data.get('razorpay_payment_id')
            razorpay_signature = request.data.get('razorpay_signature')
            payment_id = request.data.get('payment_id')

            if not all([razorpay_order_id, razorpay_payment_id, razorpay_signature]):
                return Response({'detail': 'Missing required payment verification fields.'}, status=status.HTTP_400_BAD_REQUEST)

            # Verify signature
            client = razorpay.Client(auth=(os.getenv('RAZORPAY_KEY_ID'), razorpay_key_secret))
            params = {
                'razorpay_order_id': razorpay_order_id,
                'razorpay_payment_id': razorpay_payment_id,
                'razorpay_signature': razorpay_signature
            }

            try:
                client.utility.verify_payment_signature(params)
            except razorpay.errors.SignatureVerificationError:
                return Response({'detail': 'Invalid payment signature.'}, status=status.HTTP_400_BAD_REQUEST)

            # Fetch payment details from Razorpay
            payment_details = client.payment.fetch(razorpay_payment_id)

            if payment_details['status'] != 'captured':
                return Response({'detail': f'Payment not captured. Status: {payment_details["status"]}'}, status=status.HTTP_400_BAD_REQUEST)

            # Update payment record in database
            from api.billing_helpers import get_payment
            if payment_id:
                existing_payment = get_payment(payment_id)
                if existing_payment:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "UPDATE payments SET transaction_id=%s, status='approved', verified_at=NOW() WHERE id=%s",
                            [razorpay_payment_id, payment_id]
                        )

            # Get plan_id from Razorpay notes
            plan_id = payment_details['notes'].get('plan_id')
            if plan_id:
                # Upgrade subscription
                upgrade_subscription(request.user.id, plan_id)

                # Notify user
                plan = get_plan_by_id(plan_id)
                Notification.objects.create(
                    user=request.user,
                    title="Payment Successful!",
                    message=f"Your payment has been processed successfully. Your subscription has been upgraded to {plan['name'] if plan else 'Pro'} plan.",
                    type="success",
                    redirect_url="/billing"
                )

            return Response({
                'success': True,
                'payment_id': razorpay_payment_id,
                'order_id': razorpay_order_id,
                'status': payment_details['status']
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"RazorpayVerifyView error: {e}")
            return Response({'detail': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class RazorpayWebhookView(APIView):
    """POST /api/payment/webhook — Handle Razorpay webhooks."""
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            import razorpay
            from dotenv import load_dotenv
            load_dotenv()

            webhook_secret = os.getenv('RAZORPAY_WEBHOOK_SECRET')
            razorpay_key_secret = os.getenv('RAZORPAY_KEY_SECRET')

            if not webhook_secret or not razorpay_key_secret:
                logger.error("Razorpay webhook credentials not configured")
                return Response({'detail': 'Webhook not configured.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            # Get webhook signature
            webhook_signature = request.headers.get('X-Razorpay-Signature')
            if not webhook_signature:
                return Response({'detail': 'Missing webhook signature.'}, status=status.HTTP_400_BAD_REQUEST)

            # Verify webhook signature
            payload = request.body.decode('utf-8')
            expected_signature = hmac.new(
                bytes(webhook_secret, 'utf-8'),
                bytes(payload, 'utf-8'),
                hashlib.sha256
            ).hexdigest()

            if not hmac.compare_digest(webhook_signature, expected_signature):
                return Response({'detail': 'Invalid webhook signature.'}, status=status.HTTP_400_BAD_REQUEST)

            # Parse webhook event
            event_data = json.loads(payload)
            event_type = event_data.get('event')
            payload_data = event_data.get('payload', {}).get('payment', {}).get('entity', {})

            logger.info(f"Razorpay webhook received: {event_type}")

            if event_type == 'payment.captured':
                razorpay_payment_id = payload_data.get('id')
                notes = payload_data.get('notes', {})
                user_id = notes.get('user_id')
                plan_id = notes.get('plan_id')

                if user_id and plan_id:
                    # Update payment record
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "UPDATE payments SET transaction_id=%s, status='approved', verified_at=NOW() WHERE user_id=%s AND plan_id=%s AND status='pending' ORDER BY id DESC LIMIT 1",
                            [razorpay_payment_id, user_id, plan_id]
                        )

                    # Upgrade subscription
                    upgrade_subscription(user_id, plan_id)

                    # Notify user
                    target_user = User.objects.filter(id=user_id).first()
                    if target_user:
                        plan = get_plan_by_id(plan_id)
                        Notification.objects.create(
                            user=target_user,
                            title="Payment Successful!",
                            message=f"Your payment has been processed successfully. Your subscription has been upgraded to {plan['name'] if plan else 'Pro'} plan.",
                            type="success",
                            redirect_url="/billing"
                        )

            elif event_type == 'payment.failed':
                razorpay_payment_id = payload_data.get('id')
                notes = payload_data.get('notes', {})
                user_id = notes.get('user_id')

                if user_id:
                    # Update payment record
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "UPDATE payments SET transaction_id=%s, status='rejected' WHERE user_id=%s AND status='pending' ORDER BY id DESC LIMIT 1",
                            [razorpay_payment_id, user_id]
                        )

                    # Notify user
                    target_user = User.objects.filter(id=user_id).first()
                    if target_user:
                        Notification.objects.create(
                            user=target_user,
                            title="Payment Failed",
                            message="Your payment could not be processed. Please try again or contact support.",
                            type="error",
                            redirect_url="/billing"
                        )

            elif event_type == 'subscription.charged':
                # Handle subscription renewal if needed
                logger.info("Subscription charged event received")

            return Response({'status': 'success'}, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"RazorpayWebhookView error: {e}")
            return Response({'detail': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ── Google OAuth Authentication View ───────────────────────────────────────────────

class GoogleOAuthView(APIView):
    """POST /api/auth/google/ — Handle Google OAuth authentication."""
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            access_token = request.data.get('access_token')
            id_token_str = request.data.get('id_token') or request.data.get('credential')
            
            email = None
            given_name = ''
            family_name = ''
            profile_picture = None
            google_id = None

            if id_token_str:
                from google.oauth2 import id_token as google_id_token
                from google.auth.transport import requests as google_requests
                google_client_id = os.getenv('GOOGLE_CLIENT_ID') or os.getenv('GOOGLE_OAUTH_CLIENT_ID')
                try:
                    # Verify ID Token
                    idinfo = google_id_token.verify_oauth2_token(id_token_str, google_requests.Request(), google_client_id)
                    email = idinfo.get('email')
                    given_name = idinfo.get('given_name', '')
                    family_name = idinfo.get('family_name', '')
                    profile_picture = idinfo.get('picture')
                    google_id = idinfo.get('sub')
                except Exception as ve:
                    logger.error(f"Google ID token verification failed: {ve}")
                    return Response({'detail': f'Invalid Google ID token: {str(ve)}'}, status=status.HTTP_400_BAD_REQUEST)
            elif access_token:
                # Verify access token via userinfo endpoint
                import requests
                google_info_url = f'https://www.googleapis.com/oauth2/v3/userinfo?access_token={access_token}'
                response = requests.get(google_info_url)
                if response.status_code != 200:
                    return Response({'detail': 'Invalid Google access token.'}, status=status.HTTP_400_BAD_REQUEST)
                user_info = response.json()
                email = user_info.get('email')
                given_name = user_info.get('given_name', '')
                family_name = user_info.get('family_name', '')
                profile_picture = user_info.get('picture')
                google_id = user_info.get('sub')
            else:
                return Response({'detail': 'access_token or id_token is required.'}, status=status.HTTP_400_BAD_REQUEST)

            if not email:
                return Response({'detail': 'Email is required from Google.'}, status=status.HTTP_400_BAD_REQUEST)

            # Match user by email
            user = User.objects.filter(email=email).first()
            if not user:
                # Generate unique username
                username = email.split('@')[0]
                base_username = username
                counter = 1
                while User.objects.filter(username=username).exists():
                    username = f"{base_username}{counter}"
                    counter += 1
                
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    first_name=given_name,
                    last_name=family_name,
                    password=None
                )
                ensure_free_subscription(user.id)

            # Link/Update profile info
            profile, created = Profile.objects.get_or_create(user=user)
            profile.login_provider = 'google'
            if google_id:
                profile.google_id = google_id
            if profile_picture:
                profile.profile_picture = profile_picture
            profile.save()

            # Generate JWT tokens
            from rest_framework_simplejwt.tokens import RefreshToken
            refresh = RefreshToken.for_user(user)
            access = str(refresh.access_token)

            return Response({
                'access_token': access,
                'refresh_token': str(refresh),
                'token': access,  # compatibility for frontend
                'user': UserSerializer(user).data
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"GoogleOAuthView error: {e}")
            return Response({'detail': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ── LinkedIn OAuth Authentication View ─────────────────────────────────────────────

class LinkedInOAuthView(APIView):
    """POST /api/auth/linkedin/ — Handle LinkedIn OAuth authentication."""
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            code = request.data.get('code')
            if not code:
                return Response({'detail': 'code is required.'}, status=status.HTTP_400_BAD_REQUEST)

            client_id = os.getenv('LINKEDIN_CLIENT_ID')
            client_secret = os.getenv('LINKEDIN_CLIENT_SECRET')
            redirect_uri = os.getenv('LINKEDIN_REDIRECT_URI', 'http://localhost:5174/linkedin')

            if not client_id or not client_secret:
                return Response({'detail': 'LinkedIn OAuth is not configured on the server.'}, status=status.HTTP_400_BAD_REQUEST)

            # 1. Exchange code for access token
            import requests
            token_url = 'https://www.linkedin.com/oauth/v2/accessToken'
            data = {
                'grant_type': 'authorization_code',
                'code': code,
                'redirect_uri': redirect_uri,
                'client_id': client_id,
                'client_secret': client_secret,
            }
            headers = {'Content-Type': 'application/x-www-form-urlencoded'}
            token_res = requests.post(token_url, data=data, headers=headers)
            
            if token_res.status_code != 200:
                logger.error(f"LinkedIn token exchange failed: {token_res.text}")
                return Response({'detail': 'Failed to exchange LinkedIn code.'}, status=status.HTTP_400_BAD_REQUEST)
                
            token_data = token_res.json()
            access_token = token_data.get('access_token')
            
            # 2. Get user profile details using token (using OIDC UserInfo endpoint)
            profile_url = 'https://api.linkedin.com/v2/userinfo'
            profile_headers = {'Authorization': f'Bearer {access_token}'}
            profile_res = requests.get(profile_url, headers=profile_headers)
            
            if profile_res.status_code != 200:
                logger.error(f"LinkedIn profile fetch failed: {profile_res.text}")
                return Response({'detail': 'Failed to fetch LinkedIn profile.'}, status=status.HTTP_400_BAD_REQUEST)
                
            user_info = profile_res.json()
            linkedin_id = user_info.get('sub') # sub is unique LinkedIn ID
            email = user_info.get('email')
            first_name = user_info.get('given_name', '')
            last_name = user_info.get('family_name', '')
            profile_picture = user_info.get('picture', '')
            
            if not linkedin_id:
                return Response({'detail': 'LinkedIn ID not found in profile.'}, status=status.HTTP_400_BAD_REQUEST)
            if not email:
                return Response({'detail': 'Email is required from LinkedIn.'}, status=status.HTTP_400_BAD_REQUEST)
                
            # 3. Authenticate or create User by email
            user = User.objects.filter(email=email).first()
            if not user:
                # Generate unique username
                username = f"linkedin_{linkedin_id[:10]}"
                base_username = username
                counter = 1
                while User.objects.filter(username=username).exists():
                    username = f"{base_username}{counter}"
                    counter += 1
                    
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    first_name=first_name,
                    last_name=last_name,
                    password=None
                )
                ensure_free_subscription(user.id)
                
            # Link/Update profile info
            profile, created = Profile.objects.get_or_create(user=user)
            profile.login_provider = 'linkedin'
            profile.linkedin_id = linkedin_id
            if profile_picture:
                profile.profile_picture = profile_picture
            profile.save()

            # Ensure LinkedInProfile model (from existing codebase) is also kept/updated
            try:
                from api.models import LinkedInProfile
                lip, _ = LinkedInProfile.objects.get_or_create(user=user, linkedin_id=linkedin_id)
                lip.linkedin_email = email
                lip.profile_picture = profile_picture
                lip.access_token = access_token
                lip.save()
            except Exception as e:
                logger.error(f"Error updating LinkedInProfile legacy model: {e}")
                
            # Generate JWT tokens
            from rest_framework_simplejwt.tokens import RefreshToken
            refresh = RefreshToken.for_user(user)
            access = str(refresh.access_token)

            return Response({
                'access_token': access,
                'refresh_token': str(refresh),
                'token': access,  # compatibility for frontend
                'user': UserSerializer(user).data
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"LinkedInOAuthView error: {e}")
            return Response({'detail': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


