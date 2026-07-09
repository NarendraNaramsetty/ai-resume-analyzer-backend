import os
import re
import time
import json
import logging
import requests

logger = logging.getLogger(__name__)

class BaseAIService:
    def analyze_resume(self, resume_text: str, jd_text: str) -> dict:
        raise NotImplementedError

    def optimize_resume(self, resume_text: str, jd_text: str) -> dict:
        raise NotImplementedError

class OllamaService(BaseAIService):
    def __init__(self):
        # Read from environment variables, defaulting to local Ollama instance
        self.base_url = os.getenv("OLLAMA_API_URL", "http://localhost:11434").rstrip("/")
        self.model = os.getenv("OLLAMA_MODEL", "llama3")
        # Local model execution might be slow depending on user hardware, so set a generous timeout
        self.timeout = int(os.getenv("OLLAMA_TIMEOUT", "120"))

    def _call_ollama(self, prompt: str, system_prompt: str = None, json_mode: bool = True) -> str:
        """Call local Ollama generation API endpoint."""
        url = f"{self.base_url}/api/generate"
        headers = {"Content-Type": "application/json"}
        
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.2,
                "seed": 42
            }
        }
        
        if system_prompt:
            payload["system"] = system_prompt
            
        if json_mode:
            payload["format"] = "json"

        try:
            logger.info(f"Calling local Ollama API url={url} model={self.model}")
            response = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
            response.raise_for_status()
            res_data = response.json()
            raw_response = res_data.get("response", "")
            return raw_response
            
        except requests.exceptions.Timeout as e:
            logger.error(f"Ollama request timed out: {e}")
            raise Exception("Local AI model (Ollama) request timed out. Please check if your local machine is overloaded.")
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Ollama connection error: {e}")
            raise Exception("Could not connect to Ollama. Please make sure Ollama is running locally (run 'ollama serve') and Llama 3 model is downloaded.")
        except Exception as e:
            logger.error(f"Ollama unexpected error: {e}")
            raise Exception(f"Local AI Service Error: {str(e)}")

    def _extract_json_object(self, text: str) -> str:
        """Extract first {...} block or [...] block from raw response."""
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return text[start : end + 1]
        
        # Try array
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1 and end > start:
            return text[start : end + 1]
        return text

    def _sanitize_json_string(self, raw: str) -> str:
        """Strip markdown fences, JS comments, trailing commas."""
        s = raw.strip()
        if s.startswith("```"):
            lines = s.splitlines()
            lines = lines[1:] if lines[0].startswith("```") else lines
            lines = lines[:-1] if lines and lines[-1].startswith("```") else lines
            s = "\n".join(lines).strip()
        s = re.sub(r"//[^\n]*", "", s)
        s = re.sub(r"/\*.*?\*/", "", s, flags=re.DOTALL)
        s = re.sub(r",\s*([}\]])", r"\1", s)
        return s.strip()

    def _parse_json(self, raw: str) -> dict | list:
        extracted = self._extract_json_object(raw)
        sanitized = self._sanitize_json_string(extracted)
        return json.loads(sanitized)

    # ── Analysis (primary — full context) ────────────────────────────────────────
    def analyze_resume(self, resume_text: str, jd_text: str) -> dict:
        resume_text = (resume_text or "")[:4000]
        jd_text = (jd_text or "")[:3000]

        system_prompt = (
            "You are an expert ATS system, HR recruiter, and senior software engineering interviewer. "
            "Analyze the candidate's resume against the job description. "
            "You must return ONLY a valid JSON object. Do not output any preamble, markdown fences, comments, or explanations."
        )

        prompt = f"""Analyze the resume below against the job description and return the result as a structured JSON object.

RESUME:
{resume_text}

JOB DESCRIPTION:
{jd_text}

Return exactly this JSON structure:
{{
  "professional_summary": "A concise professional summary of the candidate (approx. 100 words).",
  "ats_score": 75,
  "technical_skills": ["Python", "SQL"],
  "missing_skills": ["Docker", "Kubernetes"],
  "strengths": ["strength1", "strength2", "strength3", "strength4", "strength5"],
  "weaknesses": ["weakness1", "weakness2", "weakness3", "weakness4", "weakness5"],
  "suggestions": ["improvement1", "improvement2"],
  "recommended_roles": [
    {{"role": "Data Scientist", "score": 85}},
    {{"role": "ML Engineer", "score": 80}}
  ],
  "verdict": "High Potential Match",
  "technical_questions": ["q1", "q2", "q3", "q4", "q5", "q6", "q7", "q8", "q9", "q10"],
  "hr_questions": ["h1", "h2", "h3", "h4", "h5"],
  "project_questions": ["p1", "p2", "p3", "p4", "p5"],
  "experience_analysis": {{"score": 80, "summary": "Detailed experience analysis."}},
  "project_analysis": [
    {{"projectName": "Project A", "relevance": 85, "whyItMatches": "Relevance description."}}
  ],
  "radar_data": [
    {{"category": "Programming", "current": 80, "required": 90}},
    {{"category": "Cloud", "current": 50, "required": 80}},
    {{"category": "Databases", "current": 70, "required": 85}},
    {{"category": "ML/AI", "current": 85, "required": 90}},
    {{"category": "DevOps", "current": 40, "required": 70}}
  ]
}}

Rules:
- verdict: one of "Excellent Match", "High Potential Match", "Moderate Match", "Weak Match", "Not Suitable"
- strengths and weaknesses: exactly 5 items each
- technical_questions: exactly 10 items
- hr_questions: exactly 5 items
- project_questions: exactly 5 items
- radar_data: exactly 5 categories relevant to the job description
"""

        for attempt in range(2):
            try:
                raw = self._call_ollama(prompt, system_prompt=system_prompt, json_mode=True)
                parsed = self._parse_json(raw)
                
                # Verify required keys from prompt instructions to ensure safety
                required_keys = [
                    "professional_summary", "ats_score", "technical_skills", "missing_skills",
                    "strengths", "weaknesses", "suggestions", "recommended_roles"
                ]
                missing = [k for k in required_keys if k not in parsed]
                if missing:
                    raise KeyError(f"Missing keys from Ollama response: {missing}")
                return parsed
            except Exception as e:
                logger.warning(f"analyze_resume attempt {attempt+1} failed: {e}")
                if attempt == 1:
                    raise Exception(f"Local AI analysis failed after multiple retries. Details: {str(e)}")

    # ── Optimize resume ──────────────────────────────────────────────────────────
    def optimize_resume(self, resume_text: str, jd_text: str) -> dict:
        resume_text = (resume_text or "")[:4000]
        jd_text = (jd_text or "")[:3000]

        system_prompt = (
            "You are an expert ATS system and resume optimization engineer. "
            "You must return ONLY a valid JSON object. Do not output any preamble or comments."
        )

        prompt = f"""Rewrite the resume to align with the job description.

RESUME:
{resume_text}

JOB DESCRIPTION:
{jd_text}

Return this JSON format:
{{
  "optimized_summary": "ATS-friendly rewritten professional summary.",
  "optimized_projects": ["Bullet 1 with metrics.", "Bullet 2 with tools."],
  "optimized_skills": ["Category: Skill1, Skill2", "Category2: SkillA"],
  "ats_improvement_score": 15
}}"""

        for attempt in range(2):
            try:
                raw = self._call_ollama(prompt, system_prompt=system_prompt, json_mode=True)
                parsed = self._parse_json(raw)
                for k in ["optimized_summary", "optimized_projects", "optimized_skills", "ats_improvement_score"]:
                    if k not in parsed:
                        raise KeyError(f"Missing key: {k}")
                return parsed
            except Exception as e:
                logger.warning(f"optimize_resume attempt {attempt+1} failed: {e}")
                if attempt == 1:
                    raise Exception(f"Local AI optimization failed: {str(e)}")

    # ── Cover letter ──────────────────────────────────────────────────────────────
    def generate_cover_letter(
        self, resume_text: str, jd_text: str, company_name: str, job_role: str,
        candidate_name: str = "", ats_score: int = 0, matched_skills: list = None
    ) -> str:
        if matched_skills and ats_score:
            context = (
                f"Candidate: {candidate_name or 'Applicant'}\n"
                f"ATS Score: {ats_score}/100\n"
                f"Key Skills: {', '.join(matched_skills[:12])}\n"
                f"Role: {job_role} at {company_name}"
            )
        else:
            context = f"Resume:\n{(resume_text or '')[:2000]}\nJob: {job_role} at {company_name}\nJD:\n{(jd_text or '')[:1500]}"

        system_prompt = "You are a professional hiring consultant and copywriter. Return ONLY valid JSON."
        prompt = f"""Write a professional cover letter based on this details:
{context}

Return exactly this JSON format:
{{
  "cover_letter": "Dear Hiring Team,\\n\\n[Full letter text here...]"
}}"""

        for attempt in range(2):
            try:
                raw = self._call_ollama(prompt, system_prompt=system_prompt, json_mode=True)
                parsed = self._parse_json(raw)
                if isinstance(parsed, dict) and "cover_letter" in parsed:
                    return parsed["cover_letter"]
                return str(parsed)
            except Exception as e:
                logger.warning(f"generate_cover_letter attempt {attempt+1} failed: {e}")
                if attempt == 1:
                    raise Exception(f"Local AI failed to generate cover letter: {str(e)}")

    # ── Learning roadmap ──────────────────────────────────────────────────────────
    def generate_learning_roadmap(self, missing_skills: list, jd_text: str, target_role: str = "") -> list:
        skills_str = ", ".join(missing_skills[:15])
        context = f"Target Role: {target_role}\nSkills to learn: {skills_str}"

        system_prompt = "You are a senior tech training coordinator. Return ONLY a valid JSON list."
        prompt = f"""Create a step-by-step learning roadmap for:
{context}

Return exactly this JSON list format:
[
  {{
    "skill_name": "Skill Name",
    "learning_order": 1,
    "estimated_days": 10,
    "learning_resource": "Recommended learning resource link/name"
  }}
]"""

        for attempt in range(2):
            try:
                raw = self._call_ollama(prompt, system_prompt=system_prompt, json_mode=True)
                parsed = self._parse_json(raw)
                if isinstance(parsed, list):
                    return parsed
                if isinstance(parsed, dict) and "roadmap" in parsed:
                    return parsed["roadmap"]
                return []
            except Exception as e:
                logger.warning(f"generate_learning_roadmap attempt {attempt+1} failed: {e}")
                if attempt == 1:
                    return []

    # ── Salary estimates ──────────────────────────────────────────────────────────
    def generate_salary_estimates(self, role: str, country: str, experience_level: str, skill_set: list) -> dict:
        skills_str = ", ".join(skill_set[:10])
        system_prompt = "You are an HR compensation expert. Return ONLY valid JSON."
        prompt = f"""Provide salary estimate range in USD for:
Role: {role}
Location: {country or 'United States'}
Level: {experience_level or 'Mid-level'}
Skills: {skills_str}

Return exactly this JSON format:
{{
  "role_name": "{role}",
  "country": "{country or 'United States'}",
  "experience_level": "{experience_level or 'Mid-level'}",
  "min_salary": 90000,
  "avg_salary": 120000,
  "max_salary": 150000
}}"""

        for attempt in range(2):
            try:
                raw = self._call_ollama(prompt, system_prompt=system_prompt, json_mode=True)
                parsed = self._parse_json(raw)
                if isinstance(parsed, dict):
                    return parsed
            except Exception as e:
                logger.warning(f"generate_salary_estimates attempt {attempt+1} failed: {e}")

        return {
            "role_name": role, "country": country or "United States",
            "experience_level": experience_level or "Mid-level",
            "min_salary": 80000, "avg_salary": 110000, "max_salary": 140000
        }

    # ── Similar jobs ──────────────────────────────────────────────────────────────
    def generate_similar_jobs(self, role: str, skill_set: list) -> list:
        skills_str = ", ".join(skill_set[:10])
        system_prompt = "You are an expert recruitment advisor. Return ONLY a valid JSON list."
        prompt = f"""Recommend 3 similar job roles for:
Primary Role: {role}
Core Skills: {skills_str}

Return exactly this JSON list format:
[
  {{
    "role_name": "Similar Job Title",
    "match_percentage": 85,
    "company_name": "Example Companies"
  }}
]"""

        for attempt in range(2):
            try:
                raw = self._call_ollama(prompt, system_prompt=system_prompt, json_mode=True)
                parsed = self._parse_json(raw)
                if isinstance(parsed, list):
                    return parsed
                return []
            except Exception as e:
                logger.warning(f"generate_similar_jobs attempt {attempt+1} failed: {e}")
                if attempt == 1:
                    return []

    # ── Resume suggestions ────────────────────────────────────────────────────────
    def generate_resume_suggestions(self, resume_text: str, jd_text: str, missing_skills: list = None, target_role: str = "") -> list:
        if missing_skills is not None:
            context = (
                f"Target Role: {target_role}\n"
                f"Missing Skills: {', '.join(missing_skills[:15])}\n"
                f"Resume snippet:\n{(resume_text or '')[:800]}"
            )
        else:
            context = f"Resume:\n{(resume_text or '')[:1500]}\nJD:\n{(jd_text or '')[:1000]}"

        system_prompt = "You are a professional resume auditor. Return ONLY a valid JSON list."
        prompt = f"""Provide actionable resume improvement suggestions based on:
{context}

Return exactly this JSON list format:
[
  {{
    "suggestion_type": "Keywords",
    "suggestion_text": "Add keyword details here.",
    "priority": "High"
  }}
]

Note: suggestion_type must be one of: Keywords, Technologies, Certifications, Structure
priority must be one of: High, Medium, Low"""

        for attempt in range(2):
            try:
                raw = self._call_ollama(prompt, system_prompt=system_prompt, json_mode=True)
                parsed = self._parse_json(raw)
                if isinstance(parsed, list):
                    return parsed
                return []
            except Exception as e:
                logger.warning(f"generate_resume_suggestions attempt {attempt+1} failed: {e}")
                if attempt == 1:
                    return []

    # ── Career coach chat ─────────────────────────────────────────────────────────
    def generate_chat_reply_stream(
        self, chat_history: list, user_message: str, resume_text: str, jd_text: str,
        candidate_name: str = "", ats_score: int = 0, matched_skills: list = None,
        missing_skills: list = None, target_role: str = ""
    ):
        """Streams reply word-by-word via Ollama stream parameter."""
        url = f"{self.base_url}/api/generate"
        
        if ats_score and matched_skills is not None:
            context_block = (
                f"Candidate Name: {candidate_name or 'Applicant'}\n"
                f"Target Role: {target_role}\n"
                f"ATS Score: {ats_score}/100\n"
                f"Matched Skills: {', '.join(matched_skills[:12])}\n"
                f"Missing Skills: {', '.join(missing_skills[:10])}"
            )
        else:
            context_block = (
                f"Resume Content:\n{(resume_text or '')[:1500]}\n"
                f"Job Requirements:\n{(jd_text or '')[:1000]}"
            )

        history_text = ""
        for msg in chat_history[-10:]:
            label = "User" if msg["role"] == "user" else "Coach"
            history_text += f"{label}: {msg['message']}\n"

        system_prompt = "You are a supportive, knowledgeable AI Career Coach. Help the user optimize their career, interview prep, and tech skills."
        prompt = (
            f"Use this context:\n\n{context_block}\n\n"
            f"Chat History:\n{history_text}\n"
            f"User message: {user_message}\n"
            f"Coach reply:"
        )

        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system_prompt,
            "stream": True,
            "options": {
                "temperature": 0.5
            }
        }

        try:
            logger.info("Streaming chatbot response from local Ollama...")
            response = requests.post(url, json=payload, timeout=self.timeout, stream=True)
            response.raise_for_status()
            
            for line in response.iter_lines():
                if line:
                    chunk = json.loads(line.decode("utf-8"))
                    text = chunk.get("response", "")
                    if text:
                        yield text
                    if chunk.get("done", False):
                        break
        except requests.exceptions.ConnectionError:
            yield "Error: Could not connect to local Ollama service. Please verify that Ollama is running ('ollama serve')."
        except Exception as e:
            yield f"Error during local chatbot inference: {str(e)}"
