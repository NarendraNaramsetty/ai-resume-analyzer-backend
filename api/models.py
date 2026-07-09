from django.db import models
from django.contrib.auth.models import User

class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    api_keys_count = models.IntegerField(default=2)
    email_notif = models.BooleanField(default=True)
    match_alerts = models.BooleanField(default=True)
    weekly_digest = models.BooleanField(default=False)
    
    # OAuth Fields
    login_provider = models.CharField(max_length=50, default='email')
    google_id = models.CharField(max_length=255, blank=True, null=True)
    linkedin_id = models.CharField(max_length=255, blank=True, null=True)
    profile_picture = models.CharField(max_length=1000, blank=True, null=True)
    linkedin_profile_url = models.CharField(max_length=1000, blank=True, null=True)
    google_profile_url = models.CharField(max_length=1000, blank=True, null=True)

    def __str__(self):
        return f"{self.user.username}'s Profile"

class Resume(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='resumes')
    file_name = models.CharField(max_length=255)
    resume_file = models.FileField(upload_to='resumes/')
    raw_text = models.TextField(blank=True, default='')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.file_name} ({self.user.username})"

class JobDescription(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='job_descriptions')
    title = models.CharField(max_length=255)
    raw_text = models.TextField()
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title} ({self.user.username})"

class Analysis(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='analyses')
    resume = models.ForeignKey(Resume, on_delete=models.SET_NULL, null=True, blank=True, related_name='analyses')
    jd = models.ForeignKey(JobDescription, on_delete=models.SET_NULL, null=True, blank=True, related_name='analyses')
    
    file_name = models.CharField(max_length=255)
    role = models.CharField(max_length=255)
    ats_score = models.IntegerField()
    job_match_score = models.IntegerField(default=0) # Added to support Gemini analysis fields
    date = models.DateField(auto_now_add=True)
    status = models.CharField(max_length=50, default='Completed')
    
    # Store complex JSON lists and dicts
    matched_skills = models.JSONField(default=list)
    missing_skills = models.JSONField(default=list)
    suitability = models.JSONField(default=list)
    radar_data = models.JSONField(default=list)
    strengths = models.JSONField(default=list)
    weaknesses = models.JSONField(default=list)
    improvements = models.JSONField(default=list)
    recommendations = models.JSONField(default=list)
    keywords = models.JSONField(default=list)

    # Recruiter Report Fields
    verdict = models.CharField(max_length=100, default='Moderate Match')
    recruiter_summary = models.TextField(blank=True, default='')
    experience_analysis = models.JSONField(default=dict)
    project_analysis = models.JSONField(default=list)
    job_suitability = models.JSONField(default=dict)
    skill_gap_analysis = models.JSONField(default=dict)
    technical_questions = models.JSONField(default=list)
    hr_questions = models.JSONField(default=list)
    project_questions = models.JSONField(default=list)

    class Meta:
        ordering = ['-id']

    def __str__(self):
        return f"{self.file_name} - {self.role} ({self.ats_score}%)"

class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications', db_column='user_id')
    title = models.CharField(max_length=255)
    message = models.TextField()
    type = models.CharField(max_length=50, default='info')
    redirect_url = models.CharField(max_length=500, null=True, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'notifications'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} - {self.user.username}"


class LinkedInProfile(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='linkedin_profiles', db_column='user_id')
    linkedin_id = models.CharField(max_length=255, unique=True)
    linkedin_email = models.EmailField(max_length=255, null=True, blank=True)
    profile_url = models.CharField(max_length=500, null=True, blank=True)
    profile_picture = models.CharField(max_length=500, null=True, blank=True)
    access_token = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'linkedin_profiles'

    def __str__(self):
        return f"{self.user.username}'s LinkedIn Profile"



