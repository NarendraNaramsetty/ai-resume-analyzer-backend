import re
import os

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

try:
    import docx
except ImportError:
    docx = None

# Predefined skill database for common target roles
ROLE_SKILLS = {
    'data scientist': {
        'keywords': ['python', 'sql', 'machine learning', 'deep learning', 'statistics', 'pandas', 'scikit-learn', 'numpy', 'r', 'tableau', 'matplotlib', 'seaborn', 'tensorflow', 'keras', 'pytorch'],
        'radar_categories': {
            'Programming': ['python', 'r'],
            'Cloud': ['aws', 'gcp', 'azure'],
            'Databases': ['sql', 'nosql', 'postgres', 'mongodb'],
            'Machine Learning': ['machine learning', 'deep learning', 'scikit-learn', 'tensorflow', 'pytorch'],
            'Data Engineering': ['pandas', 'numpy', 'spark', 'hadoop']
        },
        'strengths_pool': [
            'Demonstrates foundational programming experience in Python and numerical analysis libraries.',
            'Clear evidence of statistical analysis and database query capabilities (SQL).',
            'Strong background in designing and testing predictive Machine Learning models.'
        ],
        'weaknesses_pool': {
            'docker': 'Lacks containerization experience (Docker/Kubernetes) on the resume.',
            'aws': 'Minimal exposure to public cloud platforms like AWS or Google Cloud.',
            'spark': 'No mention of big data processing frameworks (Spark, Hadoop).',
            'deep learning': 'Could benefit from deeper detail on neural network architectures (Keras, TensorFlow).'
        },
        'improvements_pool': {
            'docker': 'Mention Docker containers used to package model environments.',
            'aws': 'Incorporate cloud deployment keywords (e.g., AWS EC2, S3) into your project descriptions.',
            'spark': 'Reference processing of large datasets using PySpark or Apache Spark tools.',
            'sql': 'Elaborate on complex SQL query optimizations and database schemas designed.'
        },
        'recommendations': [
            'Complete the AWS Certified Machine Learning Specialty certification.',
            'Build and document an open-source project showing model containers deployed on AWS.',
            'Participate in Kaggle data science pipelines and showcase model iterations on GitHub.'
        ]
    },
    'ml engineer': {
        'keywords': ['python', 'docker', 'tensorflow', 'pytorch', 'git', 'linux', 'kubernetes', 'mlops', 'ci/cd', 'sql', 'gcp', 'aws', 'onnx', 'mlflow', 'cuda'],
        'radar_categories': {
            'Programming': ['python', 'cuda', 'c++'],
            'Cloud': ['aws', 'gcp', 'docker'],
            'Databases': ['sql', 'postgres'],
            'Machine Learning': ['tensorflow', 'pytorch', 'mlops', 'onnx', 'mlflow'],
            'Data Engineering': ['linux', 'git', 'ci/cd', 'kubernetes']
        },
        'strengths_pool': [
            'Deep expertise in deep learning frameworks PyTorch and TensorFlow.',
            'Hands-on system deployment capabilities inside Unix / Linux environments.',
            'Familiarity with containerized workflows and deployment tooling (Docker).'
        ],
        'weaknesses_pool': {
            'kubernetes': 'No explicit demonstration of Kubernetes for scaling cluster containers.',
            'mlflow': 'Lacks model registry and lifecycle tracking tools (e.g., MLflow, Weights & Biases).',
            'ci/cd': 'No active mention of automated CI/CD deployment pipelines for ML models.',
            'sql': 'Relational database query skills could be elaborated.'
        },
        'improvements_pool': {
            'kubernetes': 'Add instances where Kubernetes pods were used to scale batch prediction API hosts.',
            'mlflow': 'Reference MLflow tracking for hyperparameters optimization during training runs.',
            'ci/cd': 'Detail integrations with GitHub Actions or Jenkins to automate docker image builds.'
        },
        'recommendations': [
            'Create a automated pipeline that rebuilds docker model containers on code push.',
            'Familiarize yourself with model optimization libraries such as TensorRT or ONNX.',
            'Deploy a model server using FastAPI and Kubernetes and document benchmarks.'
        ]
    },
    'data analyst': {
        'keywords': ['excel', 'sql', 'tableau', 'powerbi', 'python', 'r', 'statistics', 'etl', 'data warehousing', 'looker', 'analytics', 'dashboard', 'cleaning'],
        'radar_categories': {
            'Programming': ['python', 'r', 'excel'],
            'Cloud': ['aws', 'snowflake'],
            'Databases': ['sql', 'postgres', 'data warehousing'],
            'Machine Learning': ['statistics', 'analytics'],
            'Data Engineering': ['etl', 'cleaning', 'dashboard']
        },
        'strengths_pool': [
            'Excellent command of relational database querying syntax (SQL).',
            'Proven track record of designing interactive analytics dashboards (Tableau/PowerBI).',
            'Solid documentation of spreadsheet analysis techniques.'
        ],
        'weaknesses_pool': {
            'python': 'Limited scripting capabilities listed (Python/R are missing or sparse).',
            'etl': 'No clear outline of automated ETL data pipeline architectures.',
            'data warehousing': 'Could elaborate on data warehouse concepts (Snowflake, BigQuery).'
        },
        'improvements_pool': {
            'python': 'Mention automation scripts written in Python to schedule reporting feeds.',
            'etl': 'Incorporate ETL keywords explaining how database feeds are cleaned and synced.',
            'tableau': 'Detail user count metrics and impact of dashboards built for executives.'
        },
        'recommendations': [
            'Learn Python libraries (Pandas, Numpy) to transition spreadsheet analyses to code.',
            'Earn a certification in Tableau Desktop Certified Associate or Google Data Analytics.',
            'Explore data warehousing architectures using Snowflake or Google BigQuery.'
        ]
    }
}

DEFAULT_ROLE_SKILLS = {
    'keywords': ['python', 'git', 'sql', 'docker', 'aws', 'kubernetes', 'linux', 'agile', 'rest api', 'ci/cd'],
    'radar_categories': {
        'Programming': ['python', 'javascript', 'c++'],
        'Cloud': ['aws', 'docker'],
        'Databases': ['sql', 'postgres'],
        'Machine Learning': ['statistics'],
        'Data Engineering': ['linux', 'git', 'ci/cd']
    },
    'strengths_pool': [
        'Solid knowledge of software development lifecycles and modern version control (Git).',
        'Familiarity with cloud microservices and deployment mechanisms.'
    ],
    'weaknesses_pool': {
        'docker': 'No docker containers listed.',
        'ci/cd': 'Automated testing and CI/CD pipelines are not described.'
    },
    'improvements_pool': {
        'docker': 'Integrate Docker usage in developer environment setup instructions.',
        'ci/cd': 'Detail testing suites configured in GitLab CI or GitHub Actions.'
    },
    'recommendations': [
        'Document cloud projects on GitHub detailing local setup and Docker execution.',
        'Study REST API integration and API testing tools (Postman, Cypress).'
    ]
}

def parse_resume_content(file_path):
    """
    Reads file content (supports PDF, DOCX, and text) to extract raw string content.
    """
    if not file_path or not os.path.exists(file_path):
        return ""

    ext = os.path.splitext(file_path)[1].lower()

    # 1. PDF Parser
    if ext == '.pdf' and PdfReader is not None:
        try:
            reader = PdfReader(file_path)
            text = ""
            for page in reader.pages:
                text += page.extract_text() or ""
            if text.strip():
                return text
        except Exception as e:
            print(f"pypdf extraction failed: {e}")

    # 2. DOCX Parser
    if ext in ['.docx', '.doc'] and docx is not None:
        try:
            doc = docx.Document(file_path)
            text_list = []
            for para in doc.paragraphs:
                text_list.append(para.text)
            text = "\n".join(text_list)
            if text.strip():
                return text
        except Exception as e:
            print(f"python-docx extraction failed: {e}")

    # 3. Plain Text Fallback
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            text = f.read()
            if text.strip():
                return text
    except Exception:
        pass

    # 4. Binary Fallback (ASCII scraping)
    try:
        with open(file_path, 'rb') as f:
            raw_bytes = f.read()
            return raw_bytes.decode('ascii', errors='ignore')
    except Exception:
        return ""

def evaluate_ats_score(resume_text, target_role):
    """
    Heuristic scoring: matches keywords, calculates scoring,
    and returns complete dictionary structure matching Frontend expectations.
    """
    role_key = target_role.lower()
    
    # Select matching skill database
    role_db = DEFAULT_ROLE_SKILLS
    for k in ROLE_SKILLS:
        if k in role_key:
            role_db = ROLE_SKILLS[k]
            break
            
    target_keywords = role_db['keywords']
    
    # 1. Match Keywords
    matched_words = []
    missing_words = []
    
    for kw in target_keywords:
        # Simple word boundary regex match
        pattern = r'\b' + re.escape(kw) + r'\b'
        if re.search(pattern, resume_text):
            matched_words.append(kw)
        else:
            missing_words.append(kw)
            
    # Calculate score base: matched ratio
    ratio = len(matched_words) / (len(target_keywords) or 1)
    # Score mapped between 45% and 95%
    ats_score = int(45 + (ratio * 50))
    if ats_score > 98:
        ats_score = 98

    # 2. Matched & Missing list capitalization
    matched_skills = [w.title() for w in matched_words]
    missing_skills = [w.title() for w in missing_words]

    # 3. Keyword metadata items
    keywords = []
    for kw in target_keywords:
        found = kw in matched_words
        importance = 'High' if kw in target_keywords[:5] else ('Medium' if kw in target_keywords[5:10] else 'Low')
        keywords.append({
            'word': kw.title(),
            'found': found,
            'importance': importance
        })

    # 4. Radar Categories Score Calculator
    radar_data = []
    for category, skills in role_db['radar_categories'].items():
        cat_matched = sum(1 for s in skills if s in matched_words)
        cat_total = len(skills) or 1
        
        # Calculate scores 0-100
        current_score = int((cat_matched / cat_total) * 100)
        # Give required score a high realistic threshold (e.g. 75-90)
        required_score = 80 if category != 'Cloud' else 70
        
        # Make sure current score is slightly offset if it is 0
        if current_score == 0 and cat_matched > 0:
            current_score = 25
            
        radar_data.append({
            'category': category,
            'current': current_score,
            'required': required_score
        })

    # 5. Suitability index scores (other alternative roles)
    suitability = []
    alternative_roles = ['Data Scientist', 'ML Engineer', 'AI Engineer', 'Data Analyst', 'Software Engineer']
    for alt in alternative_roles:
        if alt.lower() in role_key:
            score = ats_score + 8 if ats_score <= 90 else 98
        else:
            score = max(30, ats_score - 15 - (alternative_roles.index(alt) * 5))
        suitability.append({
            'role': alt,
            'score': min(98, score)
        })

    # 6. Strengths, Weaknesses, Improvements
    strengths = []
    # Pick strengths based on matched ratio
    for s in role_db['strengths_pool']:
        strengths.append(s)
        
    weaknesses = []
    improvements = []
    
    # Dynamically select weaknesses based on missing words
    for kw in missing_words:
        if kw in role_db.get('weaknesses_pool', {}):
            weaknesses.append(role_db['weaknesses_pool'][kw])
        if kw in role_db.get('improvements_pool', {}):
            improvements.append(role_db['improvements_pool'][kw])
            
    # Add defaults if empty
    if not weaknesses:
        weaknesses.append("No critical missing keywords identified. Focus on refining layout presentation.")
    if not improvements:
        improvements.append("Refine active verbs in experience descriptions to highlight business impact.")
        
    return {
        'ats_score': ats_score,
        'matched_skills': matched_skills,
        'missing_skills': missing_skills,
        'keywords': keywords,
        'radar_data': radar_data,
        'suitability': suitability,
        'strengths': strengths[:3],
        'weaknesses': weaknesses[:3],
        'improvements': improvements[:3],
        'recommendations': role_db['recommendations']
    }
