from flask import Flask, render_template, request, g
import sqlite3
import math

import configparser

def load_config(config_path="config.ini"):
    config = configparser.ConfigParser()
    config.read(config_path)
    return {
        "db_path": config.get("Paths", "DB_PATH", fallback="jobs_data.db"),
        "cookie_file": config.get("Paths", "COOKIE_FILE", fallback="cookiefile.json"),
        "xsrf_file": config.get("Paths", "XSRF_FILE", fallback="xsrf_token.txt"),
        "job_title": config.get("Settings", "TARGET")
    }
app = Flask(__name__)


DATABASE = load_config().get("db_path", "jobs_data.db")

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(error):
    if 'db' in g:
        g.db.close()

@app.route('/')
def index():
    db = get_db()
    query = request.args.get('query', '')
    sort_by = request.args.get('sort', 'match_score')
    page = int(request.args.get('page', 1))
    per_page = 10
    offset = (page - 1) * per_page

    sort_column = 'job_matched.match_score' if sort_by == 'match_score' else 'jobs_data.openai_score'

    filters = "(jobs.title LIKE ? OR jobs.id LIKE ? OR jobs_data.justification LIKE ?)"
    params = (f'%{query}%', f'%{query}%', f'%{query}%')

    total = db.execute(f'''
        SELECT COUNT(*)
        FROM jobs
        LEFT JOIN jobs_data ON jobs.id = jobs_data.id
        LEFT JOIN job_matched ON jobs.id = job_matched.id
        WHERE {filters}
    ''', params).fetchone()[0]

    jobs = db.execute(f'''
        SELECT jobs.id, jobs.title, jobs_data.openai_score, job_matched.match_score
        FROM jobs
        LEFT JOIN jobs_data ON jobs.id = jobs_data.id
        LEFT JOIN job_matched ON jobs.id = job_matched.id
        WHERE {filters}
        ORDER BY {sort_column} DESC
        LIMIT ? OFFSET ?
    ''', (*params, per_page, offset)).fetchall()

    total_pages = math.ceil(total / per_page)
    return render_template('index.html', jobs=jobs, query=query, sort_by=sort_by,
                           page=page, total_pages=total_pages)

@app.route('/job/<job_id>')
def job_detail(job_id):
    db = get_db()

    job = db.execute('SELECT * FROM jobs WHERE id = ?', (job_id,)).fetchone()
    job_data = db.execute('SELECT * FROM jobs_data WHERE id = ?', (job_id,)).fetchone()
    job_match = db.execute('SELECT * FROM job_matched WHERE id = ?', (job_id,)).fetchone()

    job_dict = dict(job) if job else {}
    job_data_dict = dict(job_data) if job_data else {}
    job_match_dict = dict(job_match) if job_match else {}
    job_dict["Nav"] = f"https://europa.eu/eures/eures-apps/searchengine/page/jv/id/{job_id}?lang=en"
    if "match_score" in job_match_dict:
        job_dict["score"] = job_match_dict["match_score"]

    return render_template('job_detail.html', job=job_dict, job_data=job_data_dict, job_match=job_match_dict)

@app.route('/stats')
def stats():
    db = get_db()
    total = db.execute('SELECT COUNT(*) FROM jobs_data').fetchone()[0]
    avg_score = db.execute('SELECT AVG(match_score) FROM job_matched').fetchone()[0]
    avg_openai = db.execute('SELECT AVG(openai_score) FROM jobs_data').fetchone()[0]
    return render_template('stats.html', total=total, avg_score=avg_score, avg_openai=avg_openai)

def init_db():
    db = sqlite3.connect(DATABASE)
    cursor = db.cursor()
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
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            creationDate TEXT,
            lastModificationDate TEXT,
            title TEXT,
            description TEXT,
            numberOfPosts INTEGER,
            locationMap TEXT,
            euresFlag TEXT,
            jobCategoriesCodes TEXT,
            positionScheduleCodes TEXT,
            positionOfferingCode TEXT,
            employer TEXT,
            availableLanguages TEXT,
            score REAL,
            details TEXT
        )
    """)
    db.commit()
    db.close()

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
