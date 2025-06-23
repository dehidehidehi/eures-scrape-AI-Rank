# EURES Job Scraper, AI Matcher & Web Viewer

This Python-based system automates scraping job listings from the EURES portal, stores them in SQLite, matches them against a candidate’s resume using advanced AI models (OpenAI, Google Gemini, LLaMA), and provides a **Flask web app** to explore and filter matched jobs.

---

## 🚀 Features

### ✅ Job Scraping & Storage

* Scrapes job listings from the **EURES portal**.
* Manages cookies and XSRF tokens automatically.
* Handles **pagination** to fetch all jobs.
* Saves structured job data to a **SQLite database**.

### 📄 Resume Matching

* Extracts text from resume PDFs.
* Matches resume to jobs using a **semantic embedding model**.
* Produces top N matches.

### 🤖 AI Reranking

Rerank top job matches using LLMs:

* **LLaMA CPP** (local): Efficient binary prompt reranking.
* **Google Gemini 2.5 Flash**: Fast and detailed job-to-resume evaluation.

Each AI model provides:

* Match score (1–10)
* Justification for score
* Extracted contact person/email
* Draft email for application

### 🌐 Flask Web App

* **Paginated UI**: Browse all jobs and matched jobs.
* **Job Detail Page**: View full job details with match scores and AI-generated metadata.
* **Filtering**: Filter jobs by location and other fields.
* **Sorted View**: Display top matched jobs sorted by reranked score.

---

## 🗂 Directory Structure

```bash
├── main.py                   # EURES job scraper entrypoint
├── rank_llama_cpp.py         # AI matching & reranking logic
├── app.py                    # Flask web app
├── templates/
│   ├── index.html            # Job list view
│   └── detail.html           # Single job view
├── static/                   # CSS/JS assets (if any)
├── config.ini                # Paths and settings
├── jobs_data.db              # SQLite database
├── resume.pdf                # Resume file for matching
```

---

## ⚙ Configuration

`config.ini` example:

```ini
[Paths]
DB_PATH=jobs_data.db
RESUME_PDF_PATH=resume.pdf
LLAMA_ENDPOINT=http://localhost:8090

[Settings]
TOP_N_MATCHES=10
FINAL_TOP_N=3
N_PREDICT=32

[Models]
SBERT_MODEL_NAME=all-MiniLM-L6-v2
LLAMA_MODEL_PATH=path/to/llama/model
; OPENAI_MODEL=gemini-2.5-flash
OPENAI_MODEL=gemma-3-27b-it

[API]
OPENAI_API_KEY=your_openai_api_key

[EXTRA]
NAME= Your Name
TARGET= Desired Job Title

```

---

## 💻 Installation

1. Install Python dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Install ChromeDriver and place it in your PATH.

3. (Optional) Install `uv` if using it for running:

   ```bash
   pip install uv
   ```

---

## 🧪 Usage

### Scrape Jobs

```bash
uv run main.py
```

### Match and Rerank (Example)

```python
uv run rank_llama_cpp.py
```

### Launch Web App

```bash
uv run app.py
```

Then open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your browser.

---

## 🔍 Web App Features

* `/`: View all scraped jobs (paginated).
* `/job/<id>`: View full job details, including:

  * Description
  * AI score
  * Justification
  * Contact person/email
  * Email draft

---

## 🔧 Troubleshooting

* **403 Errors**: Clear `cookiefile.json` and `xsrf_token.txt` and retry.
* **Selenium issues**: Ensure ChromeDriver matches your Chrome version.
* **LLaMA model path errors**: Double-check model and server paths for local models.

---

## 📜 License

MIT License. Use, fork, extend freely.

---
