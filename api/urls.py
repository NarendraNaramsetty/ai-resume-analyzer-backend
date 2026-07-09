from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    RegisterView, 
    LoginView, 
    UserProfileView, 
    AnalysisViewSet,
    ResumeUploadView,
    JobDescriptionCreateView,
    AnalyzeResumeView,
    OptimizeResumeView,
    NotificationViewSet,
    CoverLetterGenerateView,
    ReportGeneratePDFView,
    InterviewQuestionsView,
    LearningRoadmapView,
    SalaryEstimationView,
    SimilarJobsView,
    ResumeSuggestionsView,
    ChatSessionsListView,
    ChatHistoryView,
    ChatMessageView,
    UsageLimitsView,
    PlansListView,
    SubscriptionCurrentView,
    PaymentsHistoryView,
    PaymentCreateView,
    PaymentUploadProofView,
    PaymentVerifyView,
    AdminStatsView,
    AdminUsersView,
    AdminUserActionView,
    AdminBroadcastNotificationView,
    RazorpayCreateOrderView,
    RazorpayVerifyView,
    RazorpayWebhookView,
    GoogleOAuthView,
    LinkedInOAuthView,
)

router = DefaultRouter()
router.register('analyses', AnalysisViewSet, basename='analysis')
router.register('notifications', NotificationViewSet, basename='notification')

urlpatterns = [
    # Auth endpoints
    path('auth/register/', RegisterView.as_view(), name='register'),
    path('auth/login/', LoginView.as_view(), name='login'),
    path('auth/profile/', UserProfileView.as_view(), name='profile'),
    path('auth/google/', GoogleOAuthView.as_view(), name='google_oauth'),
    path('auth/linkedin/', LinkedInOAuthView.as_view(), name='linkedin_oauth'),
    
    # AI Analysis & Optimization endpoints
    path('resumes/', ResumeUploadView.as_view(), name='resume_upload'),
    path('jds/', JobDescriptionCreateView.as_view(), name='jd_create'),
    path('analyze/', AnalyzeResumeView.as_view(), name='analyze_resume'),
    path('optimize-resume/', OptimizeResumeView.as_view(), name='optimize_resume'),
    
    # Advanced Recruiter & Chatbot endpoints
    path('cover-letter/generate/', CoverLetterGenerateView.as_view(), name='cover_letter_generate'),
    path('report/generate-pdf/', ReportGeneratePDFView.as_view(), name='report_generate_pdf'),
    path('interview/<int:analysis_id>/', InterviewQuestionsView.as_view(), name='interview_questions'),
    path('roadmap/<int:analysis_id>/', LearningRoadmapView.as_view(), name='learning_roadmap'),
    path('salary/<int:analysis_id>/', SalaryEstimationView.as_view(), name='salary_estimation'),
    path('jobs/recommendations/<int:analysis_id>/', SimilarJobsView.as_view(), name='similar_jobs'),
    path('suggestions/<int:analysis_id>/', ResumeSuggestionsView.as_view(), name='resume_suggestions'),
    path('chat/sessions/', ChatSessionsListView.as_view(), name='chat_sessions'),
    path('chat/history/<int:session_id>/', ChatHistoryView.as_view(), name='chat_history'),
    path('chat/message/', ChatMessageView.as_view(), name='chat_message'),
    path('usage/', UsageLimitsView.as_view(), name='usage_limits'),

    # Billing & Subscription
    path('plans/', PlansListView.as_view(), name='plans_list'),
    path('subscription/current/', SubscriptionCurrentView.as_view(), name='subscription_current'),
    path('subscriptions/current/', SubscriptionCurrentView.as_view(), name='subscription_current_plural'),
    path('payments/history/', PaymentsHistoryView.as_view(), name='payments_history'),
    path('payments/create/', PaymentCreateView.as_view(), name='payment_create'),
    path('payments/upload-proof/', PaymentUploadProofView.as_view(), name='payment_upload_proof'),
    path('payments/verify/', PaymentVerifyView.as_view(), name='payment_verify'),
    
    # Admin Panel routes
    path('admin/stats/', AdminStatsView.as_view(), name='admin_stats'),
    path('admin/users/', AdminUsersView.as_view(), name='admin_users'),
    path('admin/users/action/', AdminUserActionView.as_view(), name='admin_user_action'),
    path('admin/notifications/broadcast/', AdminBroadcastNotificationView.as_view(), name='admin_broadcast_notification'),
    
    # Razorpay Payment Integration
    path('payment/create-order/', RazorpayCreateOrderView.as_view(), name='razorpay_create_order'),
    path('payment/verify/', RazorpayVerifyView.as_view(), name='razorpay_verify'),
    path('payment/webhook/', RazorpayWebhookView.as_view(), name='razorpay_webhook'),
    
    # Viewset endpoints
    path('', include(router.urls)),
]
