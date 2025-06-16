# EURES Job Scraper

This Python script automates the process of scraping job postings from the EURES portal and storing them in a local SQLite database. It uses Selenium for cookie extraction, requests for API communication, and SQLite for data storage.

## Features

- **Job Search Automation**: Fetches job postings based on predefined search criteria.
- **Cookie Management**: Automatically handles cookies and XSRF tokens for authenticated API requests.
- **Pagination Handling**: Supports fetching multiple pages of job postings.
- **Data Storage**: Saves job postings and their details in a local SQLite database.
- **Error Handling**: Automatically refreshes cookies and retries requests when tokens expire.

## Prerequisites

1. **Python 3.9+**: Ensure Python is installed on your system.
2. **Google Chrome**: The script uses Chrome for Selenium-based cookie extraction.
3. **ChromeDriver**: Download the appropriate version of ChromeDriver for your Chrome version.
4. **Python Libraries**: Install the required libraries using the command below.

## Installation

1. Clone this repository or copy the script to your local machine.
2. Install uv to manage Python dependencies:
    ```bash
    pip install uv
    ```
3. Place the `chromedriver` executable in your system's PATH or in the same directory as the script.

## Usage

1. Update the `job_title` variable in the script to specify the job title you want to search for.
2. Run the script:
    ```bash
    uv run main.py
    ```
3. The script will:
    - Fetch job postings from the EURES portal.
    - Save the job data in a SQLite database (`jobs_data.db`).

## Files

- **`main.py`**: The main script containing all the logic.
- **`cookiefile.json`**: Stores the session cookie for API requests.
- **`xsrf_token.txt`**: Stores the XSRF token for API requests.
- **`jobs_data.db`**: SQLite database where job postings are stored.

## Configuration

- **Search Criteria**: Modify the `TARGET_PAGE` URL and `make_api_request` payload to customize the search criteria (e.g., location, keywords, etc.).
- **Database Schema**: The database schema can be updated in the `setup_database` function.

## Troubleshooting

- **403 Forbidden Errors**: If you encounter frequent 403 errors, ensure that the cookies and XSRF token are being correctly extracted and saved.
- **Selenium Issues**: Ensure that ChromeDriver is compatible with your Chrome version and is correctly installed.

## License

This project is licensed under the MIT License.
