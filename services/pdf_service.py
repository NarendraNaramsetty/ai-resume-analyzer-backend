import os
import json
import logging
from django.db import connection
from django.conf import settings
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from api.db_helpers import save_generated_report, get_cover_letter

logger = logging.getLogger(__name__)

def generate_ats_pdf(analysis_id):
    """
    Fetches ATS analysis results and generates a styled PDF report inside media/reports/
    Stores the report reference in generated_reports and returns the download url path.
    """
    try:
        # Create reports output directory
        reports_dir = os.path.join(settings.MEDIA_ROOT, 'reports')
        if not os.path.exists(reports_dir):
            os.makedirs(reports_dir)

        # 1. Fetch analysis details from api_analysis
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT file_name, role, ats_score, verdict, matched_skills, missing_skills, "
                "strengths, weaknesses, improvements, recommendations, recruiter_summary, "
                "experience_analysis, project_analysis, job_suitability, skill_gap_analysis, "
                "technical_questions, hr_questions, project_questions, date "
                "FROM api_analysis WHERE id = %s", 
                [analysis_id]
            )
            row = cursor.fetchone()
            
        if not row:
            raise ValueError(f"Analysis with ID {analysis_id} not found.")

        file_name, role, ats_score, verdict, matched_skills_json, missing_skills_json, \
        strengths_json, weaknesses_json, improvements_json, recommendations_json, recruiter_summary, \
        experience_analysis_json, project_analysis_json, job_suitability_json, skill_gap_analysis_json, \
        technical_questions_json, hr_questions_json, project_questions_json, date = row

        # Parse JSON fields safely
        def safe_json_parse(val, default):
            if not val:
                return default
            if isinstance(val, (list, dict)):
                return val
            try:
                return json.loads(val)
            except Exception:
                return default

        matched_skills = safe_json_parse(matched_skills_json, [])
        missing_skills = safe_json_parse(missing_skills_json, [])
        strengths = safe_json_parse(strengths_json, [])
        weaknesses = safe_json_parse(weaknesses_json, [])
        improvements = safe_json_parse(improvements_json, [])
        recommendations = safe_json_parse(recommendations_json, [])
        experience_analysis = safe_json_parse(experience_analysis_json, {})
        project_analysis = safe_json_parse(project_analysis_json, [])
        job_suitability = safe_json_parse(job_suitability_json, {})
        skill_gap_analysis = safe_json_parse(skill_gap_analysis_json, {})
        technical_questions = safe_json_parse(technical_questions_json, [])
        hr_questions = safe_json_parse(hr_questions_json, [])
        project_questions = safe_json_parse(project_questions_json, [])

        # Fetch optional cover letter text
        cover_letter_data = get_cover_letter(analysis_id)
        cover_letter_text = cover_letter_data['cover_letter_text'] if cover_letter_data else None

        # 2. Setup PDF document
        filename = f"ats_report_{analysis_id}.pdf"
        file_path = os.path.join(reports_dir, filename)
        doc = SimpleDocTemplate(
            file_path,
            pagesize=letter,
            rightMargin=36, leftMargin=36, topMargin=40, bottomMargin=40
        )

        styles = getSampleStyleSheet()
        
        # Define clean, custom color styles
        primary_color = colors.HexColor("#0F172A")    # Sleek dark slate
        secondary_color = colors.HexColor("#22C55E")  # Green accent
        neutral_dark = colors.HexColor("#334155")     # Body text slate
        neutral_light = colors.HexColor("#F8FAFC")    # Background light gray
        border_color = colors.HexColor("#E2E8F0")

        # Custom ParagraphStyles
        title_style = ParagraphStyle(
            'DocTitle',
            parent=styles['Heading1'],
            fontName='Helvetica-Bold',
            fontSize=22,
            leading=26,
            textColor=primary_color,
            spaceAfter=6
        )
        
        subtitle_style = ParagraphStyle(
            'DocSubtitle',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=11,
            leading=14,
            textColor=neutral_dark,
            spaceAfter=20
        )

        h1_style = ParagraphStyle(
            'H1',
            parent=styles['Heading2'],
            fontName='Helvetica-Bold',
            fontSize=13,
            leading=16,
            textColor=primary_color,
            spaceBefore=14,
            spaceAfter=8,
            borderPadding=(0, 0, 2, 0),
            borderColor=secondary_color,
            borderRadius=0,
            borderWidth=0
        )

        body_style = ParagraphStyle(
            'Body',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=9.5,
            leading=13.5,
            textColor=neutral_dark,
            spaceAfter=5
        )

        bold_body_style = ParagraphStyle(
            'BoldBody',
            parent=body_style,
            fontName='Helvetica-Bold'
        )

        italic_body_style = ParagraphStyle(
            'ItalicBody',
            parent=body_style,
            fontName='Helvetica-Oblique',
            textColor=neutral_dark
        )

        bullet_style = ParagraphStyle(
            'Bullet',
            parent=body_style,
            leftIndent=15,
            firstLineIndent=-10,
            spaceAfter=4
        )

        story = []

        # Header Title
        story.append(Paragraph("ATS CANDIDATE AUDIT REPORT", title_style))
        story.append(Paragraph(f"Target Role: {role}  |  Document: {file_name}  |  Date: {date}", subtitle_style))
        
        # Meta Score Block (Table)
        score_data = [
            [
                Paragraph("<b>ATS Evaluation Score</b>", bold_body_style),
                Paragraph("<b>Recruiter Verdict</b>", bold_body_style)
            ],
            [
                Paragraph(f"<font size='28' color='#22C55E'><b>{ats_score}%</b></font>", body_style),
                Paragraph(f"<font size='14' color='#0F172A'><b>{verdict}</b></font>", body_style)
            ]
        ]
        
        score_table = Table(score_data, colWidths=[200, 340])
        score_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), neutral_light),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('PADDING', (0, 0), (-1, -1), 12),
            ('BOX', (0, 0), (-1, -1), 1, border_color),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, border_color),
        ]))
        story.append(score_table)
        story.append(Spacer(1, 15))

        # Recruiter Summary
        story.append(Paragraph("Recruiter Executive Summary", h1_style))
        story.append(Paragraph(recruiter_summary or "No executive summary available.", italic_body_style))
        story.append(Spacer(1, 10))

        # Experience Evaluation
        story.append(Paragraph("Experience Match Assessment", h1_style))
        exp_score = experience_analysis.get('score', ats_score)
        exp_summary = experience_analysis.get('summary', 'Experience analysis completed successfully.')
        
        exp_data = [
            [
                Paragraph(f"<b>Assessment Score: {exp_score}%</b>", bold_body_style),
                Paragraph(exp_summary, body_style)
            ]
        ]
        exp_table = Table(exp_data, colWidths=[150, 390])
        exp_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BACKGROUND', (0, 0), (-1, -1), neutral_light),
            ('PADDING', (0, 0), (-1, -1), 10),
            ('BOX', (0, 0), (-1, -1), 0.5, border_color),
        ]))
        story.append(exp_table)
        story.append(Spacer(1, 10))

        # Project Suitability Breakdowns
        if project_analysis:
            story.append(Paragraph("Candidate Project Relevance Breakdown", h1_style))
            proj_data = [[
                Paragraph("<b>Project Name</b>", bold_body_style),
                Paragraph("<b>Relevance Match</b>", bold_body_style),
                Paragraph("<b>Recruiter Alignment Details</b>", bold_body_style)
            ]]
            for p in project_analysis:
                proj_data.append([
                    Paragraph(p.get('projectName', 'Unnamed Project'), body_style),
                    Paragraph(f"<b>{p.get('relevance', ats_score)}%</b>", body_style),
                    Paragraph(p.get('whyItMatches', ''), body_style)
                ])
            proj_table = Table(proj_data, colWidths=[130, 80, 330])
            proj_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('BACKGROUND', (0, 0), (-1, 0), neutral_light),
                ('PADDING', (0, 0), (-1, -1), 6),
                ('GRID', (0, 0), (-1, -1), 0.5, border_color),
            ]))
            story.append(proj_table)
            story.append(Spacer(1, 10))

        # Skills Gaps
        story.append(Paragraph("Competency Alignment & Skill gaps", h1_style))
        skills_data = [
            [
                Paragraph("<b>Matched Skills</b>", bold_body_style),
                Paragraph("<b>Missing Skills / Gaps</b>", bold_body_style)
            ],
            [
                Paragraph(", ".join(matched_skills) if matched_skills else "None", body_style),
                Paragraph(", ".join(missing_skills) if missing_skills else "None", body_style)
            ]
        ]
        skills_table = Table(skills_data, colWidths=[270, 270])
        skills_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BACKGROUND', (0, 0), (-1, -1), neutral_light),
            ('PADDING', (0, 0), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 0.5, border_color),
        ]))
        story.append(skills_table)
        story.append(Spacer(1, 15))

        # Alternative fits suitability
        if job_suitability:
            primary = job_suitability.get('primary_role', {})
            alts = job_suitability.get('alternative_roles', [])
            story.append(Paragraph("Alternative Job Fits", h1_style))
            suit_text = f"Primary Fit: <b>{primary.get('role', role)}</b> ({primary.get('score', ats_score)}%). "
            if alts:
                alt_fits = [f"{a.get('role')} ({a.get('score')}%)" for a in alts]
                suit_text += "Other suitable fits: " + ", ".join(alt_fits)
            story.append(Paragraph(suit_text, body_style))
            story.append(Spacer(1, 10))

        # Learning Roadmap
        roadmap_items = skill_gap_analysis.get('recommended_learning_path', recommendations)
        if roadmap_items:
            story.append(Paragraph("Actionable Learning Roadmap", h1_style))
            for i, step in enumerate(roadmap_items):
                story.append(Paragraph(f"• <b>Step {i+1}</b>: {step}", bullet_style))
            story.append(Spacer(1, 10))

        # Core Strengths & Key Weaknesses Accordions
        feedback_data = [
            [
                Paragraph("<b>Key Candidate Strengths</b>", bold_body_style),
                Paragraph("<b>Areas of Improvement</b>", bold_body_style)
            ],
            [
                Paragraph("<br/>".join([f"• {s}" for s in strengths[:5]]), body_style),
                Paragraph("<br/>".join([f"• {w}" for w in weaknesses[:5]]), body_style)
            ]
        ]
        feedback_table = Table(feedback_data, colWidths=[270, 270])
        feedback_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BACKGROUND', (0, 0), (-1, -1), neutral_light),
            ('PADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, border_color),
        ]))
        story.append(feedback_table)
        story.append(Spacer(1, 15))

        # Interview Preparation Hub
        if technical_questions or hr_questions or project_questions:
            story.append(Paragraph("Interview Preparation Guidelines", h1_style))
            
            if technical_questions:
                story.append(Paragraph("<b>Technical Preparation Questions</b>", bold_body_style))
                for q in technical_questions[:4]:
                    story.append(Paragraph(f"- {q}", bullet_style))
                story.append(Spacer(1, 5))
                
            if hr_questions:
                story.append(Paragraph("<b>HR Behavioral Questions</b>", bold_body_style))
                for q in hr_questions[:3]:
                    story.append(Paragraph(f"- {q}", bullet_style))
                story.append(Spacer(1, 5))

            if project_questions:
                story.append(Paragraph("<b>Project Discussion Prompts</b>", bold_body_style))
                for q in project_questions[:3]:
                    story.append(Paragraph(f"- {q}", bullet_style))

        # Cover Letter
        if cover_letter_text:
            story.append(PageBreak())
            story.append(Paragraph("PERSONALIZED COVER LETTER", title_style))
            story.append(Paragraph(f"Generated for Candidate: {role} Application", subtitle_style))
            story.append(Spacer(1, 15))
            
            letter_body_style = ParagraphStyle(
                'LetterBody',
                parent=body_style,
                fontSize=10,
                leading=15,
                spaceAfter=10
            )
            # Split letter text by newlines and wrap in paragraphs
            for line in cover_letter_text.split('\n'):
                if line.strip():
                    story.append(Paragraph(line, letter_body_style))
                else:
                    story.append(Spacer(1, 8))

        # Build Document
        doc.build(story)
        
        # Save reference URL to DB
        report_url = f"/media/reports/{filename}"
        save_generated_report(analysis_id, filename, report_url, "PDF")
        
        logger.info(f"Generated PDF successfully for analysis_id={analysis_id} at {file_path}")
        return report_url

    except Exception as e:
        logger.error(f"Failed to generate ATS PDF report: {e}")
        raise e
