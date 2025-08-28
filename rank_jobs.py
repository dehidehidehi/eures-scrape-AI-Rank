import configparser
import json
import os
import sqlite3

import numpy as np
from PyPDF2 import PdfReader
from bs4 import BeautifulSoup
from openai import OpenAI
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity


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
        "n_predict": config.getint("Settings", "N_PREDICT", fallback=32),
        "openai_api_key": config.get("API", "OPENAI_API_KEY", fallback=os.environ.get("OPENAI_API_KEY", "")),
        "openai_model": config.get("Models", "OPENAI_MODEL"),
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
            draft_email TEXT DEFAULT '',
            job_type TEXT DEFAULT '',
            employer_location TEXT DEFAULT ''
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


def load_unmatched_jobs_from_db(db_path: str, limit=10, offset=0):
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

def openai_prompt(prompt: str, api_key: str, model: str) -> str:
    """Call OpenAI API with a prompt."""

    client = OpenAI(
        api_key=api_key,
        base_url="https://api.openai.com/v1"
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
        job["description"] = BeautifulSoup(job["description"], "html.parser").get_text(strip=True)
        prompt = (
            f"You are a job matching assistant, you match jobs listings with my resume.\n\n"
            f"Given my **resume** and **job description** and the fact I am looking **only** for freelance/contract work within Europe, evaluate how well the job listing fits my resume. "
            f"Return a JSON with the following fields:\n"
            f"- \"score\": Give -1 if the job is not about programming. Give 1 if the job is about programming but is a permanant salaried position. Otherwise give score between 2 and 10 matching the job listing to my skills, I am not interested in fullstack positions or front-end web development.\n"
            f"- \"justification\": At most 2 sentences explaining the score, focus on freelancing and required skills experience.\n"
            f"- \"contact_person\": Name recruiter in the job description (or null if not found).\n"
            f"- \"contact_email\": Email of the recruiter (or null if not found).\n"
            f"- \"job_type\": ON_SITE, HYBRID, or FULLY_REMOTE, (or null if not found).\n"
            f"- \"employer_location\": Country of the employer (or null if not found).\n"
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
            job["draft_email"] = ""  # response.get("email_draft", "")
            job["job_type"] = response.get("job_type", "")
            job["employer_location"] = response.get("employer_location", "")
        except Exception as e:
            print(f"[OpenAI Response Error]: {e}")
            score = 0
            job["justification"] = ""
            job["contact_person"] = ""
            job["contact_email"] = ""
            job["draft_email"] = ""
            job["job_type"] = ""
            job["employer_location"] = ""
        reranked.append({**job, "openai_score": score})
    return reranked


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

    # print("[+] Matching resume against jobs using Sentence-BERT with pagination...")
    # offset = 0
    # limit = 10
    # while True:
    #     unmatched_jobs = load_unmatched_jobs_from_db(config["db_path"], limit=limit, offset=offset)
    #     if not unmatched_jobs:
    #         break
    #
    #     print(f"[+] Matching resume against {len(unmatched_jobs)} jobs (offset: {offset})...")
    #     matches = match_resume_to_jobs(
    #         resume_text, unmatched_jobs, config["sbert_model_name"], config["top_n_matches"]
    #     )
    #     offset += limit
    #     for job in matches:
    #         cursor.execute(
    #             "INSERT OR REPLACE INTO job_matched (id, match_score) VALUES (?, ?)",
    #             (job["id"], job["score"])
    #         )
    #     conn.commit()

    print("[+] Reranking matched jobs using OpenAI...")

    offset_matched = 0
    while True:
        paginated_jobs = load_matched_jobs_paginated(conn, limit=config["top_n_matches"], offset=offset_matched)
        if not paginated_jobs:
            break

        reranked_jobs = rerank_with_openai(
            resume_text, paginated_jobs, config["openai_api_key"], config["openai_model"]
        )

        for job in reranked_jobs:
            cursor.execute("""
                INSERT INTO jobs_data (id, creationDate, lastModificationDate, score, openai_score, justification, contact_person, contact_email, draft_email, job_type, employer_location)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    openai_score = excluded.openai_score,
                    justification = excluded.justification,
                    contact_person = excluded.contact_person,
                    contact_email = excluded.contact_email,
                    draft_email = excluded.draft_email,
                    job_type = excluded.job_type,
                    employer_location = excluded.employer_location
            """, (job["id"], job.get("creationDate", ""), job.get("lastModificationDate", ""), job.get("score", 0), job["openai_score"], job["justification"], job["contact_person"], job["contact_email"], job["draft_email"], job["job_type"], job["employer_location"]))
            conn.commit()

        offset_matched += config["top_n_matches"]

    conn.close()



if __name__ == "__main__":
    main()
