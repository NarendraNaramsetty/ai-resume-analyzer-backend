from rest_framework import serializers
from django.contrib.auth.models import User
from .models import Profile, Analysis, Resume, JobDescription, Notification

class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = [
            'api_keys_count', 'email_notif', 'match_alerts', 'weekly_digest',
            'login_provider', 'google_id', 'linkedin_id', 'profile_picture',
            'linkedin_profile_url', 'google_profile_url'
        ]

class UserSerializer(serializers.ModelSerializer):
    profile = ProfileSerializer(required=False)

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'profile', 'password', 'is_staff']
        extra_kwargs = {
            'password': {'write_only': True},
            'email': {'required': True}
        }

    def create(self, validated_data):
        profile_data = validated_data.pop('profile', {})
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password'],
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', '')
        )
        Profile.objects.create(user=user, **profile_data)
        return user

    def update(self, instance, validated_data):
        profile_data = validated_data.pop('profile', {})
        
        instance.email = validated_data.get('email', instance.email)
        instance.first_name = validated_data.get('first_name', instance.first_name)
        instance.last_name = validated_data.get('last_name', instance.last_name)
        instance.save()

        profile = instance.profile
        profile.email_notif = profile_data.get('email_notif', profile.email_notif)
        profile.match_alerts = profile_data.get('match_alerts', profile.match_alerts)
        profile.weekly_digest = profile_data.get('weekly_digest', profile.weekly_digest)
        profile.api_keys_count = profile_data.get('api_keys_count', profile.api_keys_count)
        
        # OAuth Fields
        profile.login_provider = profile_data.get('login_provider', profile.login_provider)
        profile.google_id = profile_data.get('google_id', profile.google_id)
        profile.linkedin_id = profile_data.get('linkedin_id', profile.linkedin_id)
        profile.profile_picture = profile_data.get('profile_picture', profile.profile_picture)
        profile.linkedin_profile_url = profile_data.get('linkedin_profile_url', profile.linkedin_profile_url)
        profile.google_profile_url = profile_data.get('google_profile_url', profile.google_profile_url)
        
        profile.save()

        return instance

class ResumeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Resume
        fields = ['id', 'file_name', 'resume_file', 'raw_text', 'uploaded_at']
        read_only_fields = ['id', 'raw_text', 'uploaded_at', 'file_name']

class JobDescriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobDescription
        fields = ['id', 'title', 'raw_text', 'uploaded_at']
        read_only_fields = ['id', 'uploaded_at']

class AnalysisSerializer(serializers.ModelSerializer):
    resume_id = serializers.PrimaryKeyRelatedField(queryset=Resume.objects.all(), source='resume', write_only=True, required=False)
    jd_id = serializers.PrimaryKeyRelatedField(queryset=JobDescription.objects.all(), source='jd', write_only=True, required=False)

    class Meta:
        model = Analysis
        fields = [
            'id', 'resume', 'jd', 'resume_id', 'jd_id', 'file_name', 'role', 
            'ats_score', 'job_match_score', 'date', 'status', 'matched_skills', 
            'missing_skills', 'suitability', 'radar_data', 'strengths', 'weaknesses', 
            'improvements', 'recommendations', 'keywords',
            'verdict', 'recruiter_summary', 'experience_analysis', 'project_analysis',
            'job_suitability', 'skill_gap_analysis', 'technical_questions', 'hr_questions',
            'project_questions'
        ]
        read_only_fields = ['id', 'resume', 'jd', 'date', 'status', 'ats_score', 'job_match_score', 'file_name', 'role']

class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ['id', 'title', 'message', 'type', 'redirect_url', 'is_read', 'created_at']
