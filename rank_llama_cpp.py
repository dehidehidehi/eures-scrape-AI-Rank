import json
import os
from math import e
from operator import le
import re
import sqlite3
import requests
from pathlib import Path
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
from PyPDF2 import PdfReader
import configparser
from openai import OpenAI
from bs4 import BeautifulSoup
from google import genai
from pydantic import BaseModel


class ResponseStruct(BaseModel):
        score: float
        justification: str
        contact_person: str
        contact_email: str
        draft_email: str
# ----------- CONFIG -----------
def load_config(config_path="config.ini"):
    config = configparser.ConfigParser()
    config.read(config_path)
    return {
        "db_path": config.get("Paths", "DB_PATH", fallback="jobs_data.db"),
        "resume_pdf_path": config.get("Paths", "RESUME_PDF_PATH", fallback="resume.pdf"),
        "top_n_matches": config.getint("Settings", "TOP_N_MATCHES", fallback=5),
        "final_top_n": config.getint("Settings", "FINAL_TOP_N", fallback=3),
        "sbert_model_name": config.get("Models", "SBERT_MODEL_NAME", fallback="all-MiniLM-L6-v2"),
        "llama_endpoint": config.get("Paths", "LLAMA_ENDPOINT", fallback="http://localhost:8090"),
        "n_predict": config.getint("Settings", "N_PREDICT", fallback=32),
        "openai_api_key": config.get("API", "OPENAI_API_KEY", fallback=os.environ.get("OPEN_AI_API_KEY", "")),
        "openai_model": config.get("Models", "OPENAI_MODEL", fallback="gemini-2.5-flash"),
        "google_api_key": config.get("API", "OPENAI_API_KEY", fallback=""),
        "google_model": config.get("Models", "OPENAI_MODEL", fallback="gemini-2.5-flash"),
        "name": config.get("EXTRA", "NAME", fallback="Your Name"),
    }


def setup_database(config_path="config.ini"):
    config = load_config(config_path)
    conn = sqlite3.connect(config["db_path"])
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS jobs_data (
            id TEXT PRIMARY KEY,
            creationDate TEXT,
            lastModificationDate TEXT,
            score REAL DEFAULT 0,
            openai_score REAL DEFAULT 0,
            justification TEXT DEFAULT '',
            contact_person TEXT DEFAULT '',
            contact_email TEXT DEFAULT '',
            draft_email TEXT DEFAULT ''
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS job_matched (
            id TEXT PRIMARY KEY,
            match_score REAL DEFAULT 0
        )
    """)
    conn.commit()
    return conn


# ----------- UTILITIES -----------
def extract_text_from_pdf(pdf_path: str) -> str:
    reader = PdfReader(pdf_path)
    return "\n".join(page.extract_text() for page in reader.pages if page.extract_text()).strip()


def load_jobs_from_db(db_path: str, limit=10, offset=0):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT jobs.id, jobs.title, jobs.description
        FROM jobs
        LEFT JOIN job_matched ON jobs.id = job_matched.id
        WHERE job_matched.id IS NULL AND jobs.description IS NOT NULL
        LIMIT ? OFFSET ?
    """, (limit, offset))
    jobs = [{"id": row[0], "title": row[1], "description": row[2]} for row in cursor.fetchall()]
    conn.close()
    print(f"Loaded {len(jobs)} jobs from the database (offset: {offset}, limit: {limit}).")
    return jobs

# ----------- MATCHING -----------

def match_resume_to_jobs(resume_text: str, jobs: list, model_name: str, top_n: int):
    model = SentenceTransformer(model_name)
    resume_vec = model.encode(resume_text)
    job_vecs = [model.encode(job["description"]) for job in jobs]
    similarities = cosine_similarity([resume_vec], job_vecs)[0]
    top_indices = np.argsort(similarities)[::-1][:top_n]
    return [
        {**jobs[i], "score": float(similarities[i])}
        for i in top_indices
    ]




# ----------- RERANKING -----------

def llama_binary_prompt(prompt: str, model_path: str, llama_path: str, n_predict: int = 32) -> str:
    url = f"{llama_path}/completion"
    payload = {"model_path": model_path, "prompt": prompt}
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=600)
        response.raise_for_status()
        return response.json().get("content", "").strip()
    except requests.exceptions.RequestException as e:
        print(f"[LLAMA API Error]: {e}")
        return "0"


def rerank_with_llama_binary(resume_text: str, jobs: list, top_n: int, model_path: str, llama_path: str):
    reranked = []
    for job in jobs:
        prompt = (
            f"Given the following resume and job description, rate how well the resume fits the job on a scale from 1 to 10.\n"
            f"Resume:\n{resume_text}\n\nJob Title: {job['title']}\nJob Description:\n{job['description']}"
        )
        output = llama_binary_prompt(prompt, model_path=model_path, llama_path=llama_path)
        try:
            score = float(output.strip().split()[0])
        except ValueError:
            score = 0
        reranked.append({**job, "llama_score": score})
    return sorted(reranked, key=lambda x: x["llama_score"], reverse=True)[:top_n]


def openai_prompt(prompt: str, api_key: str, model: str = "gemini-2.5-flash") -> str:
    """Call OpenAI API with a prompt."""


    client = OpenAI(
        api_key=api_key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
    )
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        print (f"[OpenAI Response]: {response}")
        output = response.choices[0].message.content
        return output
    except Exception as e:
        print(f"[OpenAI API Error]: {e}")
        return "0"

def rerank_with_openai(resume_text: str, jobs: list, api_key: str, model: str):
    reranked = []
    for job in jobs:
        # Clean job description to remove HTML tags and unnecessary whitespace
        job["description"] = BeautifulSoup(job["description"], "html.parser").get_text(strip=True)
        prompt = (
            f"You are a job matching assistant.\n\n"
            f"Given the following **resume** and **job description**, evaluate how well the resume fits the job. "
            f"Return a JSON with the following fields:\n"
            f"- \"score\": A score between 1 and 10 indicating match.\n"
            f"- \"justification\": A brief explanation for the score, focus on skill and experience.\n"
            f"- \"contact_person\": Name recruiter in the job description (or null if not found).\n"
            f"- \"contact_email\": Email of the recruiter (or null if not found).\n"
            f"- \"email_draft\": A professional email from ZedRecruiter, an AI agent representing {load_config().get('name', 'Your Name')}. This should be in third person as an AI agent and not as {load_config().get('name', 'Your Name')}.\n"
            f"Resume:\n{resume_text}\n\n"
            f"Job Title: {job['title']}\n\n"
            f"Job Description:\n{job['description']}\n"
        )

        output = openai_prompt(prompt, api_key=api_key, model=model)
        print(f"[OpenAI Output]: {output}")
        try:

            response = json.loads(output[output.find('{'):output.rfind('}') + 1])
            score = float(response.get("score", 0))
            job["justification"] = response.get("justification", "")
            job["contact_person"] = response.get("contact_person", "")
            job["contact_email"] = response.get("contact_email", "")
            job["draft_email"] = response.get("email_draft", "")
        except Exception as e:
            print(f"[OpenAI Response Error]: {e}")
            score = 0
            job["justification"] = ""
            job["contact_person"] = ""
            job["contact_email"] = ""
            job["draft_email"] = ""
        reranked.append({**job, "openai_score": score})
    return reranked



def rerank_with_google(resume_text: str, jobs: list, api_key: str, model: str):
    reranked = []
    for job in jobs:
        # Clean job description to remove HTML tags and unnecessary whitespace
        job["description"] = BeautifulSoup(job["description"], "html.parser").get_text(strip=True)
        prompt = (
            f"You are a job matching assistant.\n\n"
            f"Given the following **resume** and **job description**, evaluate how well the resume fits the job. "
            f"Return a  A score between 1 to 10 as match.\n explanation for the score,Name of recruiter and email (or null if not found).\n ,A short, professional email from ZedRecruiter, an AI agent representing {load_config().get('name', 'Your Name')}, "
            f"Resume:\n{resume_text}\n\n"
            f"Job Title: {job['title']}\n\n"
            f"Job Description:\n{job['description']}\n"
        )

        output = google_prompt(prompt, api_key=api_key, model=model)
        print(f"[Google Output]: {output}")
        try:
            resp: ResponseStruct = output.parsed
            score = resp.score
            justification = resp.justification
            contact_person = resp.contact_person
            contact_email = resp.contact_email
            email_draft = resp.email_draft

        except Exception as e:
            print(f"[Google Response Error]: {e}")
            score = 0
            justification = ""
            contact_person = ""
            contact_email = ""
            email_draft = ""

    reranked.append({**job, "google_score": score, "justification": justification,
                     "contact_person": contact_person, "contact_email": contact_email,
                     "email_draft": email_draft})
    return reranked


def google_prompt(prompt: str, api_key: str, model: str = "gemini-2.5-flash") -> str:
    """Call Google GenAI API with a prompt."""
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
    model=model,
    contents=prompt,
    config={
        "response_mime_type": "application/json",
        "response_schema": ResponseStruct,
    },
)
    return response.text

def load_matched_jobs_paginated(conn, limit=10, offset=0):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT jm.id, jm.match_score, j.title, j.description
        FROM job_matched jm
        JOIN jobs j ON jm.id = j.id
        LEFT JOIN jobs_data jd ON jm.id = jd.id
        WHERE jd.id IS NULL
        ORDER BY jm.match_score DESC
        LIMIT ? OFFSET ?
    """, (limit, offset))
    return [{"id": row[0], "match_score": row[1], "title": row[2], "description": row[3]} for row in cursor.fetchall()]


# ----------- MAIN -----------

def main():
    config = load_config()
    setup_database()
    print("[+] Extracting resume text...")
    resume_text = extract_text_from_pdf(config["resume_pdf_path"])
    conn = sqlite3.connect(config["db_path"])
    cursor = conn.cursor()

    print("[+] Matching resume against jobs using Sentence-BERT with pagination...")
    offset = 0
    limit = 10

    while True:
        jobs = load_jobs_from_db(config["db_path"], limit=limit, offset=offset)

        if not jobs:
            break
        print(f"[+] Matching resume against {len(jobs)} jobs (offset: {offset})...")
        matches = match_resume_to_jobs(
            resume_text, jobs, config["sbert_model_name"], config["top_n_matches"]
        )
        offset += limit
        for job in matches:
            cursor.execute(
                "INSERT OR REPLACE INTO job_matched (id, match_score) VALUES (?, ?)",
                (job["id"], job["score"])
            )
        conn.commit()

    print("[+] Reranking matched jobs using OpenAI...")

    offset_matched = 0
    while True:
        paginated_jobs = load_matched_jobs_paginated(conn, limit=config["top_n_matches"], offset=offset_matched)
        if not paginated_jobs:
            break

        reranked_jobs = rerank_with_openai(
            resume_text, paginated_jobs, config["openai_api_key"], config["openai_model"]
        )

        # reranked_jobs = rerank_with_google(
        #     resume_text, paginated_jobs, config["google_api_key"], config["google_model"]
        # )
        for job in reranked_jobs:
            cursor.execute("""
                INSERT INTO jobs_data (id, creationDate, lastModificationDate, score, openai_score, justification, contact_person, contact_email, draft_email)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    openai_score = excluded.openai_score,
                    justification = excluded.justification,
                    contact_person = excluded.contact_person,
                    contact_email = excluded.contact_email,
                    draft_email = excluded.draft_email
            """, (job["id"], job.get("creationDate", ""), job.get("lastModificationDate", ""), job.get("score", 0), job["openai_score"], job["justification"], job["contact_person"], job["contact_email"], job["draft_email"]))
            conn.commit()

        offset_matched += config["top_n_matches"]

    conn.close()



if __name__ == "__main__":
    main()
