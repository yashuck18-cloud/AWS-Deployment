import os
import json
import requests
from flask import Flask, render_template, request, redirect, url_for
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

app = Flask(__name__)

# Supabase Config
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Ollama Config
OLLAMA_URL = os.getenv("OLLAMA_URL")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY in .env")

# Initialize Supabase Client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

@app.route("/") 
def index():
    # Fetch DB data using Supabase library
    response = supabase.table("students").select("*").order("id").execute()
    students = response.data if response.data else []
    return render_template("index.html", students=students)


@app.route("/add", methods=["GET", "POST"])
def add_student():
    if request.method == "POST":
        name = request.form.get("name")
        email = request.form.get("email")
        course = request.form.get("course")

        if name and email and course:
            supabase.table("students").insert({
                "name": name,
                "email": email,
                "course": course
            }).execute()

        return redirect(url_for("index"))

    return render_template("add.html")


@app.route("/edit/<int:student_id>", methods=["GET", "POST"])
def edit_student(student_id):
    if request.method == "POST":
        name = request.form.get("name")
        email = request.form.get("email")
        course = request.form.get("course")

        supabase.table("students").update({
            "name": name,
            "email": email,
            "course": course
        }).eq("id", student_id).execute()

        return redirect(url_for("index"))

    response = supabase.table("students").select("*").eq("id", student_id).single().execute()
    student = response.data
    return render_template("edit.html", student=student)


@app.route("/delete/<int:student_id>")
def delete_student(student_id):
    supabase.table("students").delete().eq("id", student_id).execute()
    return redirect(url_for("index"))

# AI Route using Ollama
@app.route("/ai/analyze/<int:student_id>")
def analyze_student(student_id):
    # Fetch student data using Supabase library
    response = supabase.table("students").select("*").eq("id", student_id).single().execute()
    if not response.data:
        return "Student not found", 404
    
    student = response.data
    prompt = f"Analyze this student profile and suggest a career path: Name: {student['name']}, Course: {student['course']}"
    
    # Call Ollama
    ollama_payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False
    }
    
    try:
        ollama_response = requests.post(
            f"{OLLAMA_URL}/api/generate", 
            json=ollama_payload,
            timeout=30
        )
        ollama_response.raise_for_status()
        analysis = ollama_response.json().get("response", "No response from AI")
    except requests.exceptions.ConnectionError:
        analysis = f"⚠️ Ollama server not running at {OLLAMA_URL}. Please start Ollama."
    except requests.exceptions.Timeout:
        analysis = "⚠️ Ollama request timed out."
    except requests.exceptions.HTTPError as e:
        analysis = f"⚠️ Ollama error: {e.response.status_code}. Check if model '{OLLAMA_MODEL}' is available."
    except Exception as e:
        analysis = f"Error: {str(e)}"
    
    # Re-fetch students for index page
    index_response = supabase.table("students").select("*").order("id").execute()
    return render_template("index.html", students=index_response.data, analysis=analysis, analyzed_id=student_id)

# NEW: AI Query Route for general questions
@app.route("/ask-ai", methods=["POST"])
def ask_ai():
    """
    Fetches all database records and sends them to Ollama 
    along with the user's question.
    """
    # 1. Get user question from request body
    data = request.get_json()
    user_question = data.get("question")
    
    if not user_question:
        return {"answer": "Please provide a question."}, 400

    try:
        # 2. Fetch all records from Supabase table 'students'
        response = supabase.table("students").select("*").execute()
        records = response.data if response.data else []
        
        # 3. Convert records to JSON string
        database_json = json.dumps(records, indent=2)

        # 4. Build the dynamic prompt for Ollama
        prompt = f"""You are a DATABASE QUERY ASSISTANT inside my Flask CRUD app.

STRICT RULES:
1. Answer ONLY using the database records provided below.
2. DO NOT use external knowledge.
3. DO NOT guess or generate fake data.
4. If the answer is not present in the records, reply EXACTLY: Data not found in database.
5. Keep answers short, clear, and directly based on the data.

RESPONSE FORMAT:
* If multiple results -> list them (Name, Email).
* If single result -> return that record clearly (Name, Email, Course).
* If asking count -> return number only with explanation.
* If asking names -> return only names.

Database Records:
{database_json}

User Question:
{user_question}
"""

        # 5. Call local Ollama API
        ollama_payload = {
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False
        }
        
        ollama_response = requests.post(
            f"{OLLAMA_URL}/api/generate", 
            json=ollama_payload,
            timeout=30
        )
        ollama_response.raise_for_status()
        
        # 6. Extract answer from Ollama response
        answer = ollama_response.json().get("response", "").strip()
        
        if not answer:
            answer = "Data not found in database."
        
        return {"answer": answer}
    
    except requests.exceptions.ConnectionError as e:
        error_msg = f"⚠️ Cannot connect to Ollama at {OLLAMA_URL}. Is it running? (Error: {str(e)})"
        print(f"Connection Error: {error_msg}")
        return {"answer": error_msg}, 503
    
    except requests.exceptions.Timeout:
        error_msg = "⚠️ Ollama took too long to respond. Try again."
        print(f"Timeout Error: {error_msg}")
        return {"answer": error_msg}, 504
    
    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code if hasattr(e, 'response') else 'Unknown'
        error_msg = f"⚠️ Ollama server error ({status_code}). Check if model '{OLLAMA_MODEL}' is installed."
        print(f"HTTP Error: {error_msg}")
        return {"answer": error_msg}, 502
    
    except Exception as e:
        error_msg = f"⚠️ Unexpected error: {str(e)}"
        print(f"General Error: {error_msg}")
        return {"answer": error_msg}, 500


if __name__ == "__main__":
    app.run(debug=True)