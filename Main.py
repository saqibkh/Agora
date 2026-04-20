from flask import Flask, render_template, request, redirect, url_for
import csv
import os
import threading
import requests
import base64
from datetime import datetime
from werkzeug.utils import secure_filename
from flask import send_from_directory
import time

app = Flask(__name__)

# Define our database paths
DATA_DIR = 'data'
POSTS_FILE = os.path.join(DATA_DIR, 'posts.csv')
COMMENTS_FILE = os.path.join(DATA_DIR, 'comments.csv')
UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# --- AUTOMATIC DATABASE INITIALIZATION ---
def init_db():
    """Creates the directories and CSVs automatically if they don't exist."""
    os.makedirs(DATA_DIR, exist_ok=True)
    
    if not os.path.exists(POSTS_FILE):
        with open(POSTS_FILE, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['id', 'title', 'body', 'author', 'timestamp', 'image_path'])
            
    if not os.path.exists(COMMENTS_FILE):
        with open(COMMENTS_FILE, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['id', 'post_id', 'author', 'body', 'score', 'user_type'])

def read_csv(filepath):
    with open(filepath, mode='r', encoding='utf-8') as file:
        return list(csv.DictReader(file))

def write_csv(filepath, fieldnames, data):
    with open(filepath, mode='a', encoding='utf-8', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writerow(data)

# Add Route to Serve Images
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# Vision Analysis Function
def analyze_image(image_path):
    print(f"DEBUG: Moondream is analyzing the image...")
    try:
        with open(image_path, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
        
        response = requests.post("http://localhost:11434/api/generate", json={
            "model": "moondream",
            # This prompt is now generic: it identifies text, objects, and context
            "prompt": (
                "Describe this image in high detail for a forum discussion. "
                "Identify all primary objects, any visible text, brands, or numbers, "
                "and the overall context or condition of what is shown. "
                "Be objective and precise."
            ),
            "images": [encoded_string],
            "stream": False
        })
        description = response.json().get("response", "").strip()
        print(f"DEBUG: Vision Analysis -> {description}")
        return description
    except Exception as e:
        print(f"Vision error: {e}")
        return "No visual context available."

def get_current_context(query):
    """Fetches real-time context. Times out after 10s to prevent hangs."""
    print(f"DEBUG: Researching '{query}' on the web...")
    try:
        # Focusing on Reddit results for that authentic forum feel
        with DDGS(timeout=10) as ddgs:
            results = [r['body'] for r in ddgs.text(f"site:reddit.com {query}", max_results=3)]
            if not results:
                return "No specific recent forum discussions found."
            return "\n".join(results)
    except Exception as e:
        print(f"DEBUG: Search skipped: {e}")
        return "Search unavailable. Using internal logic."

def generate_ai_perspectives(post_id, post_title, post_body, image_filename=None):
    image_description = ""
    if image_filename:
        full_path = os.path.join(app.config['UPLOAD_FOLDER'], image_filename)
        image_description = analyze_image(full_path)
        print(f"Vision Analysis: {image_description}")

    # 1. Start Research
    internet_context = get_current_context(post_title)

    # 2. Define Personas with specific personality 'hooks'
    personas = [
        {
            "name": "AI_Optimist", 
            "style": "supportive, enthusiastic, and focused on growth/best-case results."
        },
        {
            "name": "AI_Pessimist", 
            "style": "cynical, value-obsessed, and focused on risks or hidden downsides."
        },
        {
            "name": "AI_Contrarian", 
            "style": "unconventional, challenging, and prone to arguing against the obvious 'safe' choice."
        }
    ]

    OLLAMA_API_URL = "http://localhost:11434/api/generate"
    AI_MODEL = "gemma4:latest" # Optimized for your 12GB VRAM

    for persona in personas:
        print(f"DEBUG: {persona['name']} is thinking...")
        
        # 3. THE REASONING PROMPT (Agentic Instruction)
        # We tell the AI to think before it speaks to avoid hallucinations
        full_prompt = (
            f"SYSTEM: You are a {persona['style']} forum user.\n"
            f"DATA FROM THE ATTACHED IMAGE: {image_description}\n" # This is now the primary data source
            "You are participating in a discussion on Agora.\n\n"
            f"USER POST: {post_title} - {post_body}\n\n"
            "INSTRUCTIONS:\n"
            "1. Read the 'DATA FROM THE ATTACHED IMAGE' first. This is the evidence the user is talking about.\n"
            "2. Compare the specific GPUs shown in that data.\n"
            "3. Respond in your personality style. If the image shows one GPU winning, acknowledge those specific numbers.\n"
            "4. NEVER mention being an AI. Sound like a real tech enthusiast.\n\n"
            "FINAL RESPONSE:"
        )

        try:
            # We add a 60s timeout for the GPU inference
            response = requests.post(OLLAMA_API_URL, json={
                "model": AI_MODEL,
                "prompt": full_prompt,
                "stream": False
            }, timeout=60)
            
            if response.status_code == 200:
                ai_text = response.json().get("response", "").strip()
                
                # Cleanup: If the model blurted out its internal thinking, we strip it
                if "FINAL RESPONSE:" in ai_text:
                    ai_text = ai_text.split("FINAL RESPONSE:")[-1].strip()

                # 4. Save to Database
                comment_id = str(int(datetime.now().timestamp() * 1000))
                new_ai_comment = {
                    'id': comment_id,
                    'post_id': post_id,
                    'author': persona['name'],
                    'body': ai_text,
                    'score': '5',
                    'user_type': 'ai'
                }
                
                write_csv(COMMENTS_FILE, ['id', 'post_id', 'author', 'body', 'score', 'user_type'], new_ai_comment)
                print(f"DEBUG: {persona['name']} success.")
                
                # Tiny delay to keep timestamps unique
                time.sleep(1)
                
        except Exception as e:
            print(f"DEBUG: {persona['name']} failed: {e}")

# --- WEB UI ROUTES ---
# --- FIX 1: Update index to include image_path ---
@app.route('/')
def index():
    raw_posts = read_csv(POSTS_FILE)
    all_comments = read_csv(COMMENTS_FILE)

    posts = []
    for post in reversed(raw_posts):
        post_comments = [c for c in all_comments if c['post_id'] == post['id']]
        post_data = {
            'id': post['id'],
            'title': post['title'],
            'body': post['body'],
            'author': post['author'],
            'timestamp': post['timestamp'],
            'image_path': post.get('image_path', ''), # Added this line
            'comments': post_comments
        }
        posts.append(post_data)

    return render_template('index.html', posts=posts)

# --- FIX 2 & 3: Update create_post to handle files and threads ---
@app.route('/create_post', methods=['POST'])
def create_post():
    title = request.form.get('title')
    body = request.form.get('body')
    
    # Handle the image upload
    file = request.files.get('image')
    image_filename = ""
    
    if file and file.filename != '':
        image_filename = secure_filename(file.filename)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], image_filename))
    
    post_id = str(int(datetime.timestamp(datetime.now())))
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    new_post = {
        'id': post_id,
        'title': title,
        'body': body,
        'author': 'HumanUser',
        'timestamp': timestamp,
        'image_path': image_filename # Save filename to CSV
    }
    
    # Save the post with the image_path column
    write_csv(POSTS_FILE, ['id', 'title', 'body', 'author', 'timestamp', 'image_path'], new_post)
    
    # Pass the image_filename to the background thread
    thread = threading.Thread(target=generate_ai_perspectives, args=(post_id, title, body, image_filename))
    thread.start()

    return redirect(url_for('index'))

@app.route('/add_comment', methods=['POST'])
def add_comment():
    post_id = request.form.get('post_id')
    body = request.form.get('body')
    
    comment_id = str(int(datetime.timestamp(datetime.now())))
    
    new_comment = {
        'id': comment_id,
        'post_id': post_id,
        'author': 'HumanUser',
        'body': body,
        'score': '', 
        'user_type': 'human'
    }
    
    write_csv(COMMENTS_FILE, ['id', 'post_id', 'author', 'body', 'score', 'user_type'], new_comment)
    return redirect(url_for('index'))

if __name__ == '__main__':
    # Initialize the database before the server starts
    init_db()
    print("Agora Database Initialized. Starting server...")
    app.run(host='0.0.0.0', port=5001, debug=True)
