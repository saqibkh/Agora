from flask import Flask, render_template, request, redirect, url_for
import csv
import os
import threading
import requests
from datetime import datetime
import time

app = Flask(__name__)

# Define our database paths
DATA_DIR = 'data'
POSTS_FILE = os.path.join(DATA_DIR, 'posts.csv')
COMMENTS_FILE = os.path.join(DATA_DIR, 'comments.csv')

# --- AUTOMATIC DATABASE INITIALIZATION ---
def init_db():
    """Creates the directories and CSVs automatically if they don't exist."""
    os.makedirs(DATA_DIR, exist_ok=True)
    
    if not os.path.exists(POSTS_FILE):
        with open(POSTS_FILE, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['id', 'title', 'body', 'author', 'timestamp'])
            
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

# --- THE AI INFERENCE ENGINE ---
def generate_ai_perspectives(post_id, post_title, post_body):
    personas = [
        {
            "name": "AI_Optimist", 
            "prompt": (
                "You are an enthusiastic, 'treat yourself' type of forum user. "
                "You believe in quality, growth, and the joy of upgrading your life. "
                "Look at the user's situation and encourage them to go for the best option "
                "that brings them happiness. Use specific examples related to their topic. "
                "Keep it under 60 words and sound like a supportive friend."
            )
        },
        {
            "name": "AI_Pessimist", 
            "prompt": (
                "You are a cynical, 'everything is a scam' type of forum user. "
                "You focus on hidden costs, depreciation, and the pointlessness of vanity. "
                "Remind the user that things break and the 'new' feeling fades. "
                "Be realistic to a fault. Keep it under 60 words and sound grumpy but grounded."
            )
        },
        {
            "name": "AI_Contrarian", 
            "prompt": (
                "You are a 'think outside the box' contrarian. "
                "Whatever the user or the general public thinks is the 'obvious' choice, "
                "you argue for a completely different alternative. "
                "Challenge their assumptions and offer a perspective they haven't considered. "
                "Keep it under 60 words and sound like a stubborn expert."
            )
        }
    ]


    # The default local address for Ollama
    OLLAMA_API_URL = "http://localhost:11434/api/generate"
    # Make sure this model matches what you pulled in Ollama (e.g., llama3, mistral, etc.)
    AI_MODEL = "llama3" 

    for persona in personas:
        # Build the exact prompt for the AI
        full_prompt = f"System: {persona['prompt']}\n\nUser Title: {post_title}\nUser Post: {post_body}\n\nResponse:"
        
        try:
            # Send the request to your 3080 Ti
            response = requests.post(OLLAMA_API_URL, json={
                "model": AI_MODEL,
                "prompt": full_prompt,
                "stream": False # We want the full text at once, not streamed
            })
            
            if response.status_code == 200:
                ai_text = response.json().get("response", "").strip()
                
                # Save the generated AI comment to the CSV database
                comment_id = str(int(datetime.now().timestamp() * 1000))
                
                new_ai_comment = {
                    'id': comment_id,
                    'post_id': post_id,
                    'author': persona['name'],
                    'body': ai_text,
                    'score': '5', # Neutral baseline score for future DPO training
                    'user_type': 'ai'
                }
                
                write_csv(COMMENTS_FILE, ['id', 'post_id', 'author', 'body', 'score', 'user_type'], new_ai_comment)
                
                # Add a tiny delay so the timestamps don't overlap exactly
                time.sleep(1)
                
        except Exception as e:
            print(f"Failed to connect to local AI for {persona['name']}. Is Ollama running? Error: {e}")

# --- WEB UI ROUTES ---
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
            'comments': post_comments
        }
        posts.append(post_data)

    return render_template('index.html', posts=posts)

@app.route('/create_post', methods=['POST'])
def create_post():
    title = request.form.get('title')
    body = request.form.get('body')
    
    post_id = str(int(datetime.timestamp(datetime.now())))
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    new_post = {
        'id': post_id,
        'title': title,
        'body': body,
        'author': 'HumanUser',
        'timestamp': timestamp
    }
    
    # 1. Save the post
    write_csv(POSTS_FILE, ['id', 'title', 'body', 'author', 'timestamp'], new_post)
    
    # 2. Trigger the AI in the background!
    # By using a thread, the web page redirects instantly while your GPU spins up.
    thread = threading.Thread(target=generate_ai_perspectives, args=(post_id, title, body))
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
