from flask import Flask, render_template_string, request, jsonify, session, redirect, url_for
import google.generativeai as genai
import PyPDF2
import docx
import re
import os
import sqlite3
import hashlib
import secrets
from werkzeug.utils import secure_filename
from datetime import datetime

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv is optional for production

app = Flask(__name__)

# ============ SECURE CONFIGURATION ============
# Get sensitive data from environment variables
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_urlsafe(32))
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

# Validate API key exists
if not GEMINI_API_KEY:
    raise ValueError(
        "GEMINI_API_KEY not found!\n"
        "Please create a .env file with: GEMINI_API_KEY=your_key_here\n"
        "Or set environment variable: export GEMINI_API_KEY=your_key_here"
    )

app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file

# Create uploads folder if not exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Configure Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

ALLOWED_EXTENSIONS = {'pdf', 'docx', 'txt'}

# ============ DATABASE FUNCTIONS ============
def init_db():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS interviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        skills TEXT,
        resume_text TEXT,
        score INTEGER,
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )''')
    conn.commit()
    conn.close()

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def create_user(name, email, password):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (name, email, password) VALUES (?, ?, ?)",
                  (name, email, hash_password(password)))
        conn.commit()
        user_id = c.lastrowid
        conn.close()
        return user_id, True
    except sqlite3.IntegrityError:
        conn.close()
        return None, False

def verify_user(email, password):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT id, name, email FROM users WHERE email = ? AND password = ?",
              (email, hash_password(password)))
    user = c.fetchone()
    conn.close()
    return user

def save_interview(user_id, skills, resume_text, score):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("INSERT INTO interviews (user_id, skills, resume_text, score) VALUES (?, ?, ?, ?)",
              (user_id, skills, resume_text[:1000], score))
    conn.commit()
    conn.close()

def get_user_interviews(user_id):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT id, skills, score, date FROM interviews WHERE user_id = ? ORDER BY date DESC", (user_id,))
    interviews = c.fetchall()
    conn.close()
    return interviews

def get_interview_by_id(interview_id, user_id):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("SELECT id, skills, resume_text, score, date FROM interviews WHERE id = ? AND user_id = ?", 
              (interview_id, user_id))
    interview = c.fetchone()
    conn.close()
    return interview

def delete_interview_by_id(interview_id, user_id):
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute("DELETE FROM interviews WHERE id = ? AND user_id = ?", (interview_id, user_id))
    conn.commit()
    conn.close()

# Initialize database
init_db()

# ============ FILE HANDLING ============
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_text_from_pdf(filepath):
    text = ""
    with open(filepath, 'rb') as file:
        reader = PyPDF2.PdfReader(file)
        for page in reader.pages:
            text += page.extract_text()
    return text

def extract_text_from_docx(filepath):
    doc = docx.Document(filepath)
    return ' '.join([paragraph.text for paragraph in doc.paragraphs])

def extract_text_from_txt(filepath):
    with open(filepath, 'r', encoding='utf-8') as file:
        return file.read()

def extract_skills_from_resume(text):
    prompt = f"""Extract technical skills from this resume. Return ONLY a comma-separated list of skills (no extra text, no numbering).

Resume text: {text[:3000]}

Skills found:"""
    
    try:
        response = model.generate_content(prompt)
        skills = response.text.strip()
        skills = re.sub(r'[^\w\s#,+-]', '', skills)
        return skills
    except Exception as e:
        print(f"Error extracting skills: {e}")
        tech_keywords = ['Python', 'Java', 'JavaScript', 'React', 'Angular', 'Vue', 'Node.js', 
                        'SQL', 'MongoDB', 'AWS', 'Docker', 'Kubernetes', 'Git', 'Django', 
                        'Flask', 'Spring', 'C++', 'C#', 'PHP', 'Ruby', 'Go', 'Rust', 
                        'TensorFlow', 'PyTorch', 'Machine Learning', 'AI', 'Data Science']
        found_skills = [skill for skill in tech_keywords if skill.lower() in text.lower()]
        return ', '.join(found_skills[:10]) if found_skills else 'General Programming'

# ============ HTML TEMPLATES ============
LOGIN_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>Login - AI Interview System</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .container {
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            width: 90%;
            max-width: 450px;
            padding: 40px;
            animation: slideUp 0.5s ease;
        }
        @keyframes slideUp {
            from { transform: translateY(50px); opacity: 0; }
            to { transform: translateY(0); opacity: 1; }
        }
        h1 { color: #333; margin-bottom: 10px; font-size: 32px; }
        .subtitle { color: #666; margin-bottom: 30px; }
        input {
            width: 100%;
            padding: 14px;
            margin: 10px 0;
            border: 2px solid #e0e0e0;
            border-radius: 10px;
            font-size: 16px;
            transition: border-color 0.3s;
        }
        input:focus { outline: none; border-color: #667eea; }
        button {
            width: 100%;
            padding: 14px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 10px;
            font-size: 16px;
            font-weight: bold;
            cursor: pointer;
            margin-top: 10px;
        }
        button:hover { transform: translateY(-2px); }
        .link { text-align: center; margin-top: 20px; color: #666; }
        .link a { color: #667eea; text-decoration: none; font-weight: bold; }
        .error { background: #fee; color: #c33; padding: 10px; border-radius: 8px; margin-bottom: 15px; text-align: center; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Welcome Back! 👋</h1>
        <div class="subtitle">Login to continue your interview journey</div>
        {% if error %}
        <div class="error">{{ error }}</div>
        {% endif %}
        <form method="POST">
            <input type="email" name="email" placeholder="Email address" required>
            <input type="password" name="password" placeholder="Password" required>
            <button type="submit">Login 🚀</button>
        </form>
        <div class="link">Don't have an account? <a href="/signup">Sign up now</a></div>
    </div>
</body>
</html>
'''

SIGNUP_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>Sign Up - AI Interview System</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .container {
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            width: 90%;
            max-width: 450px;
            padding: 40px;
            animation: slideUp 0.5s ease;
        }
        @keyframes slideUp {
            from { transform: translateY(50px); opacity: 0; }
            to { transform: translateY(0); opacity: 1; }
        }
        h1 { color: #333; margin-bottom: 10px; font-size: 32px; }
        .subtitle { color: #666; margin-bottom: 30px; }
        input {
            width: 100%;
            padding: 14px;
            margin: 10px 0;
            border: 2px solid #e0e0e0;
            border-radius: 10px;
            font-size: 16px;
            transition: border-color 0.3s;
        }
        input:focus { outline: none; border-color: #667eea; }
        button {
            width: 100%;
            padding: 14px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 10px;
            font-size: 16px;
            font-weight: bold;
            cursor: pointer;
            margin-top: 10px;
        }
        button:hover { transform: translateY(-2px); }
        .link { text-align: center; margin-top: 20px; color: #666; }
        .link a { color: #667eea; text-decoration: none; font-weight: bold; }
        .error { background: #fee; color: #c33; padding: 10px; border-radius: 8px; margin-bottom: 15px; text-align: center; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Create Account ✨</h1>
        <div class="subtitle">Start your AI-powered interview practice</div>
        {% if error %}
        <div class="error">{{ error }}</div>
        {% endif %}
        <form method="POST">
            <input type="text" name="name" placeholder="Full name" required>
            <input type="email" name="email" placeholder="Email address" required>
            <input type="password" name="password" placeholder="Password" required>
            <button type="submit">Sign Up 🎯</button>
        </form>
        <div class="link">Already have an account? <a href="/login">Login</a></div>
    </div>
</body>
</html>
'''

DASHBOARD_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>Dashboard - AI Interview System</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; }
        .navbar { background: white; padding: 20px 40px; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        .logo { font-size: 24px; font-weight: bold; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .logout-btn { background: #ff4757; color: white; padding: 10px 20px; border-radius: 8px; text-decoration: none; }
        .container { max-width: 1200px; margin: 50px auto; padding: 20px; }
        .welcome-card { background: white; border-radius: 20px; padding: 40px; text-align: center; margin-bottom: 30px; box-shadow: 0 10px 30px rgba(0,0,0,0.2); animation: slideUp 0.5s ease; }
        @keyframes slideUp { from { transform: translateY(30px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }
        .welcome-card h1 { color: #333; margin-bottom: 10px; }
        .welcome-card p { color: #666; font-size: 18px; }
        .feature-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 30px; margin-top: 30px; }
        .feature-card { background: white; border-radius: 15px; padding: 30px; text-align: center; transition: transform 0.3s; cursor: pointer; box-shadow: 0 5px 20px rgba(0,0,0,0.1); }
        .feature-card:hover { transform: translateY(-10px); }
        .feature-icon { font-size: 48px; margin-bottom: 20px; }
        .feature-card h3 { color: #333; margin-bottom: 10px; }
        .btn { display: inline-block; padding: 12px 30px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; text-decoration: none; border-radius: 8px; margin-top: 20px; }
    </style>
</head>
<body>
    <div class="navbar">
        <div class="logo">🎤 AI Interview System</div>
        <a href="/logout" class="logout-btn">Logout</a>
    </div>
    <div class="container">
        <div class="welcome-card">
            <h1>Welcome, {{ name }}! 👋</h1>
            <p>Ready to ace your next interview? Let's practice with AI!</p>
        </div>
        <div class="feature-grid">
            <div class="feature-card" onclick="location.href='/upload-resume'">
                <div class="feature-icon">📄</div>
                <h3>Upload Resume</h3>
                <p>Upload your resume and let AI extract your skills automatically</p>
                <span class="btn">Get Started →</span>
            </div>
            <div class="feature-card" onclick="location.href='/upload-resume'">
                <div class="feature-icon">🎯</div>
                <h3>Practice Interview</h3>
                <p>AI-powered mock interviews tailored to your skills</p>
                <span class="btn">Start Practice →</span>
            </div>
            <div class="feature-card" onclick="location.href='/history'">
                <div class="feature-icon">📊</div>
                <h3>Track Progress</h3>
                <p>Review your performance and improve over time</p>
                <span class="btn">View History →</span>
            </div>
        </div>
    </div>
</body>
</html>
'''

UPLOAD_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>Upload Resume - AI Interview System</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; }
        .navbar { background: white; padding: 20px 40px; display: flex; justify-content: space-between; align-items: center; }
        .logo { font-size: 24px; font-weight: bold; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .back-btn { background: #667eea; color: white; padding: 10px 20px; border-radius: 8px; text-decoration: none; }
        .container { max-width: 800px; margin: 50px auto; padding: 20px; }
        .upload-card { background: white; border-radius: 20px; padding: 40px; box-shadow: 0 20px 60px rgba(0,0,0,0.3); animation: slideUp 0.5s ease; }
        @keyframes slideUp { from { transform: translateY(30px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }
        h1 { color: #333; }
        .subtitle { color: #666; margin-bottom: 30px; }
        .upload-area { border: 2px dashed #667eea; border-radius: 15px; padding: 40px; text-align: center; margin: 20px 0; cursor: pointer; }
        .upload-area:hover { background: #f8f9ff; }
        input[type="file"] { display: none; }
        button { width: 100%; padding: 14px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border: none; border-radius: 10px; font-size: 16px; font-weight: bold; cursor: pointer; margin-top: 20px; }
        .error { background: #fee; color: #c33; padding: 10px; border-radius: 8px; margin-bottom: 15px; text-align: center; }
    </style>
</head>
<body>
    <div class="navbar">
        <div class="logo">🎤 AI Interview System</div>
        <a href="/dashboard" class="back-btn">← Back</a>
    </div>
    <div class="container">
        <div class="upload-card">
            <h1>Upload Your Resume 📄</h1>
            <div class="subtitle">We'll extract your skills using AI</div>
            {% if error %}
            <div class="error">{{ error }}</div>
            {% endif %}
            <form method="POST" enctype="multipart/form-data">
                <div class="upload-area" onclick="document.getElementById('fileInput').click()">
                    <div style="font-size: 48px;">📁</div>
                    <p>Click to upload or drag and drop</p>
                    <p style="color:#667eea;">PDF, DOCX, or TXT (Max 16MB)</p>
                    <input type="file" name="resume" id="fileInput" accept=".pdf,.docx,.txt">
                </div>
                <button type="submit">Extract Skills →</button>
            </form>
        </div>
    </div>
</body>
</html>
'''

SKILLS_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>Skills Detected - AI Interview System</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; }
        .navbar { background: white; padding: 20px 40px; display: flex; justify-content: space-between; align-items: center; }
        .logo { font-size: 24px; font-weight: bold; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .back-btn { background: #667eea; color: white; padding: 10px 20px; border-radius: 8px; text-decoration: none; }
        .container { max-width: 900px; margin: 50px auto; padding: 20px; }
        .skills-card { background: white; border-radius: 20px; padding: 40px; box-shadow: 0 20px 60px rgba(0,0,0,0.3); animation: slideUp 0.5s ease; }
        @keyframes slideUp { from { transform: translateY(30px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }
        .skill-tag { display: inline-block; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 8px 16px; border-radius: 20px; margin: 5px; font-size: 14px; }
        .skills-container { background: #f8f9fa; border-radius: 15px; padding: 20px; margin: 20px 0; }
        .resume-preview { background: #f8f9fa; border-radius: 15px; padding: 20px; margin: 20px 0; max-height: 300px; overflow-y: auto; }
        input { width: 100%; padding: 12px; border: 2px solid #e0e0e0; border-radius: 8px; margin-top: 10px; }
        button { width: 100%; padding: 14px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border: none; border-radius: 10px; font-size: 16px; font-weight: bold; cursor: pointer; margin-top: 20px; }
    </style>
</head>
<body>
    <div class="navbar">
        <div class="logo">🎤 AI Interview System</div>
        <a href="/dashboard" class="back-btn">← Back</a>
    </div>
    <div class="container">
        <div class="skills-card">
            <h1>🔍 Skills Detected</h1>
            <div class="subtitle">AI has analyzed your resume and found these skills</div>
            <div class="skills-container" id="skillsContainer">
                {% for skill in skills.split(',') %}
                <span class="skill-tag">{{ skill.strip() }}</span>
                {% endfor %}
            </div>
            <div>
                <label>Edit skills if needed:</label>
                <input type="text" id="skillsInput" value="{{ skills }}">
            </div>
            <div class="resume-preview">
                <h3>📄 Resume Preview</h3>
                <p>{{ resume_preview }}...</p>
            </div>
            <button onclick="startInterview()">🎯 Start AI Interview</button>
        </div>
    </div>
    <script>
        function startInterview() {
            const skills = document.getElementById('skillsInput').value;
            fetch('/start-interview', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({skills: skills})
            })
            .then(response => response.json())
            .then(data => {
                if (data.questions) {
                    localStorage.setItem('interviewQuestions', JSON.stringify(data.questions));
                    window.location.href = '/interview-page';
                } else {
                    alert('Error starting interview. Please try again.');
                }
            })
            .catch(error => alert('Error: ' + error));
        }
    </script>
</body>
</html>
'''

INTERVIEW_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>AI Interview - Gemini Powered</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; }
        .navbar { background: white; padding: 20px 40px; display: flex; justify-content: space-between; align-items: center; }
        .logo { font-size: 24px; font-weight: bold; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .exit-btn { background: #ff4757; color: white; padding: 10px 20px; border-radius: 8px; text-decoration: none; }
        .container { max-width: 900px; margin: 30px auto; padding: 20px; }
        .interview-card { background: white; border-radius: 20px; padding: 40px; box-shadow: 0 20px 60px rgba(0,0,0,0.3); animation: slideUp 0.5s ease; }
        @keyframes slideUp { from { transform: translateY(30px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }
        .progress { background: #e0e0e0; border-radius: 10px; height: 10px; margin-bottom: 30px; overflow: hidden; }
        .progress-bar { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); height: 100%; transition: width 0.3s ease; }
        .question-box { background: #f8f9fa; border-radius: 15px; padding: 30px; margin: 20px 0; border-left: 5px solid #667eea; }
        .question-text { font-size: 20px; color: #333; line-height: 1.6; }
        textarea { width: 100%; padding: 15px; border: 2px solid #e0e0e0; border-radius: 10px; font-size: 16px; font-family: inherit; resize: vertical; min-height: 180px; margin: 20px 0; }
        .button-group { display: flex; gap: 15px; margin: 20px 0; }
        button { flex: 1; padding: 12px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border: none; border-radius: 10px; font-size: 16px; font-weight: bold; cursor: pointer; }
        .feedback-box { background: #d4edda; padding: 20px; border-radius: 10px; margin: 20px 0; border-left: 4px solid #28a745; }
        .loading { text-align: center; padding: 20px; color: #667eea; font-weight: bold; }
        .result-box { text-align: center; }
        .final-score { font-size: 48px; font-weight: bold; margin: 20px 0; }
    </style>
</head>
<body>
    <div class="navbar">
        <div class="logo">🎤 AI Interview Session</div>
        <a href="/dashboard" class="exit-btn" onclick="return confirm('Exit interview? Progress will be lost.')">Exit</a>
    </div>
    <div class="container">
        <div class="interview-card">
            <div class="progress"><div class="progress-bar" id="progressBar" style="width: 0%"></div></div>
            <div id="questionSection">
                <div class="question-box"><div class="question-text" id="question"></div></div>
                <textarea id="answer" placeholder="Type your answer here..."></textarea>
                <div class="button-group">
                    <button onclick="submitAnswer()">📝 Submit Answer</button>
                    <button onclick="nextQuestion()" id="nextBtn" disabled>⏩ Next Question</button>
                </div>
                <div id="feedback"></div>
            </div>
            <div id="loadingSection" style="display:none;"><div class="loading">🤖 Processing with Gemini AI...</div></div>
            <div id="resultSection" style="display:none;" class="result-box">
                <h2>🎉 Interview Complete!</h2>
                <div class="final-score" id="finalScore"></div>
                <div id="finalSummary"></div>
                <button onclick="location.href='/dashboard'">🏠 Return to Dashboard</button>
            </div>
        </div>
    </div>
    <script>
        let questions = JSON.parse(localStorage.getItem('interviewQuestions') || '[]');
        let currentIndex = 0, answers = [], scores = [];
        if (questions.length === 0) { alert('No questions found.'); window.location.href = '/upload-resume'; }
        function updateProgress() { document.getElementById('progressBar').style.width = ((currentIndex)/questions.length)*100 + '%'; }
        function showQuestion() {
            if (currentIndex < questions.length) {
                document.getElementById('question').innerHTML = questions[currentIndex];
                document.getElementById('answer').value = '';
                document.getElementById('feedback').innerHTML = '';
                document.getElementById('nextBtn').disabled = true;
                updateProgress();
            } else { endInterview(); }
        }
        async function submitAnswer() {
            let answer = document.getElementById('answer').value;
            if (!answer.trim()) { alert('Please provide an answer!'); return; }
            document.getElementById('questionSection').style.display = 'none';
            document.getElementById('loadingSection').style.display = 'block';
            try {
                let response = await fetch('/evaluate-answer', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({question: questions[currentIndex], answer: answer})
                });
                let data = await response.json();
                answers.push(answer); scores.push(data.score);
                document.getElementById('loadingSection').style.display = 'none';
                document.getElementById('questionSection').style.display = 'block';
                document.getElementById('feedback').innerHTML = `<div class="feedback-box"><strong>📊 Feedback:</strong><br>${data.feedback}<br><br><strong>⭐ Score: ${data.score}/100</strong></div>`;
                document.getElementById('nextBtn').disabled = false;
            } catch(e) { alert('Error evaluating answer.'); location.reload(); }
        }
        function nextQuestion() { if (answers.length <= currentIndex) { alert('Submit answer first!'); return; } currentIndex++; showQuestion(); }
        async function endInterview() {
            let totalScore = scores.reduce((a,b)=>a+b,0)/scores.length;
            await fetch('/complete-interview', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({score:Math.round(totalScore)})});
            document.getElementById('questionSection').style.display = 'none';
            document.getElementById('resultSection').style.display = 'block';
            document.getElementById('finalScore').innerHTML = Math.round(totalScore)+'/100';
            let summary = totalScore>=80 ? '🌟 Excellent performance!' : (totalScore>=60 ? '👍 Good job! Keep practicing!' : '💪 Good effort! Review and try again!');
            document.getElementById('finalSummary').innerHTML = '<p>'+summary+'</p>';
        }
        showQuestion();
    </script>
</body>
</html>
'''

HISTORY_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>Interview History - AI Interview System</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; }
        .navbar { background: white; padding: 20px 40px; display: flex; justify-content: space-between; align-items: center; }
        .logo { font-size: 24px; font-weight: bold; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .back-btn { background: #667eea; color: white; padding: 10px 20px; border-radius: 8px; text-decoration: none; }
        .container { max-width: 1200px; margin: 50px auto; padding: 20px; }
        .history-card { background: white; border-radius: 20px; padding: 40px; box-shadow: 0 20px 60px rgba(0,0,0,0.3); animation: slideUp 0.5s ease; }
        @keyframes slideUp { from { transform: translateY(30px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }
        h1 { color: #333; margin-bottom: 10px; }
        .subtitle { color: #666; margin-bottom: 30px; }
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 30px; }
        .stat-card { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 15px; text-align: center; }
        .stat-number { font-size: 36px; font-weight: bold; }
        .stat-label { font-size: 14px; opacity: 0.9; margin-top: 5px; }
        .interview-item { background: #f8f9fa; border-radius: 15px; padding: 20px; margin-bottom: 15px; transition: transform 0.2s; }
        .interview-item:hover { transform: translateX(5px); background: #f0f0f0; }
        .interview-date { color: #667eea; font-weight: bold; margin-bottom: 10px; }
        .interview-skills { margin-bottom: 10px; }
        .skill-badge { display: inline-block; background: #e0e0e0; padding: 4px 12px; border-radius: 15px; font-size: 12px; margin-right: 5px; }
        .interview-score { display: inline-block; background: #28a745; color: white; padding: 5px 15px; border-radius: 20px; font-weight: bold; }
        .score-low { background: #dc3545; }
        .score-medium { background: #ffc107; color: #333; }
        .score-high { background: #28a745; }
        .no-data { text-align: center; padding: 40px; color: #666; }
        .btn-view { background: #667eea; color: white; border: none; padding: 8px 20px; border-radius: 8px; cursor: pointer; margin-top: 10px; margin-right: 10px; }
        .delete-btn { background: #dc3545; color: white; border: none; padding: 8px 15px; border-radius: 8px; cursor: pointer; margin-top: 10px; }
    </style>
</head>
<body>
    <div class="navbar">
        <div class="logo">🎤 AI Interview System</div>
        <a href="/dashboard" class="back-btn">← Back to Dashboard</a>
    </div>
    <div class="container">
        <div class="history-card">
            <h1>📊 Interview History</h1>
            <div class="subtitle">Track your progress and improve over time</div>
            <div class="stats-grid" id="statsGrid">
                <div class="stat-card"><div class="stat-number" id="totalInterviews">0</div><div class="stat-label">Total Interviews</div></div>
                <div class="stat-card"><div class="stat-number" id="avgScore">0</div><div class="stat-label">Average Score</div></div>
                <div class="stat-card"><div class="stat-number" id="bestScore">0</div><div class="stat-label">Best Score</div></div>
                <div class="stat-card"><div class="stat-number" id="improvement">0</div><div class="stat-label">Improvement %</div></div>
            </div>
            <div id="historyList"></div>
        </div>
    </div>
    <script>
        function loadHistory() {
            fetch('/get-history')
                .then(response => response.json())
                .then(data => {
                    if (data.interviews && data.interviews.length > 0) {
                        displayInterviews(data.interviews);
                        displayStats(data.interviews);
                    } else {
                        document.getElementById('historyList').innerHTML = '<div class="no-data">📭 No interviews yet. Take your first interview to see history!</div>';
                    }
                })
                .catch(error => {
                    document.getElementById('historyList').innerHTML = '<div class="no-data">Error loading history. Please try again.</div>';
                });
        }
        function displayStats(interviews) {
            const total = interviews.length;
            const avg = Math.round(interviews.reduce((sum, i) => sum + i.score, 0) / total);
            const best = Math.max(...interviews.map(i => i.score));
            const first = interviews[interviews.length-1]?.score || 0;
            const last = interviews[0]?.score || 0;
            const improvement = first > 0 ? Math.round(((last - first) / first) * 100) : 0;
            document.getElementById('totalInterviews').innerText = total;
            document.getElementById('avgScore').innerText = avg;
            document.getElementById('bestScore').innerText = best;
            document.getElementById('improvement').innerText = (improvement > 0 ? '+' : '') + improvement;
        }
        function displayInterviews(interviews) {
            const container = document.getElementById('historyList');
            container.innerHTML = interviews.map(interview => {
                let scoreClass = interview.score >= 70 ? 'score-high' : (interview.score >= 50 ? 'score-medium' : 'score-low');
                return `<div class="interview-item">
                    <div class="interview-date">📅 ${new Date(interview.date).toLocaleString()}</div>
                    <div class="interview-skills"><strong>Skills:</strong> ${interview.skills.split(',').slice(0,5).map(s => `<span class="skill-badge">${s.trim()}</span>`).join('')}</div>
                    <div><span class="interview-score ${scoreClass}">⭐ Score: ${interview.score}/100</span><br>
                    <button class="btn-view" onclick="viewDetails(${interview.id})">View Details</button>
                    <button class="delete-btn" onclick="deleteInterview(${interview.id})">Delete</button></div>
                </div>`;
            }).join('');
        }
        function viewDetails(id) { window.location.href = `/interview-details/${id}`; }
        function deleteInterview(id) {
            if (confirm('Are you sure you want to delete this interview record?')) {
                fetch(`/delete-interview/${id}`, { method: 'DELETE' }).then(() => loadHistory());
            }
        }
        loadHistory();
    </script>
</body>
</html>
'''

DETAILS_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>Interview Details - AI Interview System</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; }
        .navbar { background: white; padding: 20px 40px; display: flex; justify-content: space-between; align-items: center; }
        .logo { font-size: 24px; font-weight: bold; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .back-btn { background: #667eea; color: white; padding: 10px 20px; border-radius: 8px; text-decoration: none; }
        .container { max-width: 900px; margin: 50px auto; padding: 20px; }
        .details-card { background: white; border-radius: 20px; padding: 40px; box-shadow: 0 20px 60px rgba(0,0,0,0.3); animation: slideUp 0.5s ease; }
        @keyframes slideUp { from { transform: translateY(30px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }
        .score-circle { width: 150px; height: 150px; border-radius: 50%; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); margin: 20px auto; display: flex; align-items: center; justify-content: center; }
        .score-number { font-size: 48px; font-weight: bold; color: white; }
        .resume-preview { background: #f8f9fa; padding: 20px; border-radius: 15px; margin-top: 20px; max-height: 300px; overflow-y: auto; }
        h2 { color: #333; margin-top: 20px; }
        .info { margin: 10px 0; }
    </style>
</head>
<body>
    <div class="navbar">
        <div class="logo">🎤 AI Interview System</div>
        <a href="/history" class="back-btn">← Back to History</a>
    </div>
    <div class="container">
        <div class="details-card">
            <div style="text-align: center;">
                <h1>📝 Interview Details</h1>
                <div class="score-circle"><div class="score-number" id="score">--</div></div>
            </div>
            <div class="info"><strong>📅 Date:</strong> <span id="date"></span></div>
            <div class="info"><strong>🎯 Skills:</strong> <span id="skills"></span></div>
            <h2>📄 Resume Preview</h2>
            <div class="resume-preview" id="resumePreview"></div>
        </div>
    </div>
    <script>
        const id = window.location.pathname.split('/').pop();
        fetch(`/get-interview/${id}`)
            .then(res => res.json())
            .then(data => {
                document.getElementById('score').innerText = data.score;
                document.getElementById('date').innerText = new Date(data.date).toLocaleString();
                document.getElementById('skills').innerHTML = data.skills.split(',').map(s => `<span style="background:#e0e0e0;padding:4px 12px;border-radius:15px;margin:2px;display:inline-block;">${s.trim()}</span>`).join('');
                document.getElementById('resumePreview').innerHTML = '<p>' + (data.resume_text || 'No resume preview available') + '</p>';
            });
    </script>
</body>
</html>
'''

# ============ ROUTES ============
@app.route('/')
def home():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        user_id, success = create_user(name, email, password)
        if success:
            session['user_id'] = user_id
            session['user_name'] = name
            return redirect(url_for('upload_resume'))
        else:
            return render_template_string(SIGNUP_HTML, error='Email already exists!')
    return render_template_string(SIGNUP_HTML)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = verify_user(email, password)
        if user:
            session['user_id'] = user[0]
            session['user_name'] = user[1]
            return redirect(url_for('dashboard'))
        else:
            return render_template_string(LOGIN_HTML, error='Invalid email or password!')
    return render_template_string(LOGIN_HTML)

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template_string(DASHBOARD_HTML, name=session.get('user_name'))

@app.route('/upload-resume', methods=['GET', 'POST'])
def upload_resume():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        if 'resume' not in request.files:
            return render_template_string(UPLOAD_HTML, error='No file uploaded')
        file = request.files['resume']
        if file.filename == '':
            return render_template_string(UPLOAD_HTML, error='No file selected')
        if file and allowed_file(file.filename):
            filename = secure_filename(f"{session['user_id']}_{file.filename}")
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            ext = filename.rsplit('.', 1)[1].lower()
            if ext == 'pdf':
                text = extract_text_from_pdf(filepath)
            elif ext == 'docx':
                text = extract_text_from_docx(filepath)
            else:
                text = extract_text_from_txt(filepath)
            skills = extract_skills_from_resume(text)
            session['resume_text'] = text[:5000]
            session['skills'] = skills
            return render_template_string(SKILLS_HTML, skills=skills, resume_preview=text[:500])
        else:
            return render_template_string(UPLOAD_HTML, error='Invalid file type. Use PDF, DOCX, or TXT')
    return render_template_string(UPLOAD_HTML)

@app.route('/start-interview', methods=['POST'])
def start_interview():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    skills = request.json.get('skills', session.get('skills', 'General Programming'))
    prompt = f"Generate 5 technical interview questions for {skills}. Return only numbered list 1-5."
    try:
        response = model.generate_content(prompt)
        questions_text = response.text
        questions = []
        for line in questions_text.split('\n'):
            line = line.strip()
            if line and re.match(r'^\d+\.', line):
                questions.append(re.sub(r'^\d+\.\s*', '', line))
        if len(questions) < 3:
            questions = [f"Explain a core concept in {skills.split(',')[0]}?"] + ["Describe a challenging project.", "How do you solve problems?"]
        return jsonify({'questions': questions[:5]})
    except Exception as e:
        print(f"Error generating questions: {e}")
        return jsonify({'questions': ["Explain your technical expertise.", "Describe a challenging project.", "How do you learn new technologies?", "Tell me about teamwork.", "Where do you see yourself?"]})

@app.route('/evaluate-answer', methods=['POST'])
def evaluate_answer():
    data = request.json
    question = data.get('question')
    answer = data.get('answer')
    prompt = f"Evaluate: Q:{question} A:{answer}. Give score/100 and brief feedback. Format: SCORE: (number) | FEEDBACK: (text)"
    try:
        response = model.generate_content(prompt)
        result = response.text
        score_match = re.search(r'SCORE:\s*(\d+)', result)
        score = int(score_match.group(1)) if score_match else 70
        feedback_match = re.search(r'FEEDBACK:\s*(.+?)(?=$)', result, re.IGNORECASE)
        feedback = feedback_match.group(1) if feedback_match else "Good answer!"
        return jsonify({'score': score, 'feedback': feedback})
    except Exception as e:
        print(f"Error evaluating answer: {e}")
        score = min(90, max(50, len(answer)//10))
        return jsonify({'score': score, 'feedback': "Answer recorded. " + ("Excellent!" if len(answer)>100 else "Try more details.")})

@app.route('/complete-interview', methods=['POST'])
def complete_interview():
    if 'user_id' in session:
        data = request.json
        score = data.get('score', 0)
        save_interview(session['user_id'], session.get('skills', ''), session.get('resume_text', ''), score)
        return jsonify({'message': 'Saved!'})
    return jsonify({'error': 'Not logged in'}), 401

@app.route('/interview-page')
def interview_page():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template_string(INTERVIEW_HTML)

@app.route('/history')
def history_page():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template_string(HISTORY_HTML)

@app.route('/get-history')
def get_history():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    interviews = get_user_interviews(session['user_id'])
    interview_list = []
    for i in interviews:
        interview_list.append({
            'id': i[0],
            'skills': i[1],
            'score': i[2],
            'date': i[3]
        })
    return jsonify({'interviews': interview_list})

@app.route('/get-interview/<int:interview_id>')
def get_interview(interview_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    interview = get_interview_by_id(interview_id, session['user_id'])
    if interview:
        return jsonify({
            'id': interview[0],
            'skills': interview[1],
            'resume_text': interview[2],
            'score': interview[3],
            'date': interview[4]
        })
    return jsonify({'error': 'Not found'}), 404

@app.route('/delete-interview/<int:interview_id>', methods=['DELETE'])
def delete_interview_route(interview_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    delete_interview_by_id(interview_id, session['user_id'])
    return jsonify({'message': 'Deleted!'})

@app.route('/interview-details/<int:interview_id>')
def interview_details(interview_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template_string(DETAILS_HTML)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    print("\n" + "="*60)
    print("🎤 AI INTERVIEW SYSTEM - SECURE VERSION")
    print("="*60)
    print("✅ Server: http://127.0.0.1:5000")
    print("✅ Features: Login/Signup | Resume Upload | AI Interview | History Tracking")
    print("✅ Security: No hardcoded API keys - Using environment variables")
    print("="*60 + "\n")
    app.run(debug=True, port=5000)