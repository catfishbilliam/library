import os
from flask import Flask, render_template, request, redirect, url_for
import mysql.connector
from mysql.connector import errorcode
from dotenv import load_dotenv

# -----------------------------------------------------------------------------
# 1) Load environment variables from .env
# -----------------------------------------------------------------------------
load_dotenv()  # pip install python-dotenv if you don't already have it

DB_HOST     = os.environ.get("DB_HOST", "localhost")
DB_PORT     = int(os.environ.get("DB_PORT", 3306))
DB_USER     = os.environ.get("DB_USER", "root")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_NAME     = os.environ.get("DB_NAME", "LibraryDB")
SECRET_KEY  = os.environ.get("SECRET_KEY", "dev_secret_key")  # for Flask session, if needed

# -----------------------------------------------------------------------------
# 2) Create Flask app
# -----------------------------------------------------------------------------
app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY

# -----------------------------------------------------------------------------
# 3) Initialize a MySQL connection (pooled) on app startup
# -----------------------------------------------------------------------------
def get_db_connection():
    """
    Returns a new MySQL connection using mysql.connector.
    """
    return mysql.connector.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
        use_unicode=True
    )

# -----------------------------------------------------------------------------
# 4) Helper functions to fetch authors & categories (for dropdown lists)
# -----------------------------------------------------------------------------
def fetch_all_authors():
    """
    Returns a list of tuples: (AuthorID, FullName)
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT AuthorID, FullName FROM Authors ORDER BY FullName;")
    authors = cursor.fetchall()
    cursor.close()
    conn.close()
    return authors

def fetch_all_categories():
    """
    Returns a list of tuples: (CategoryID, CategoryName)
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT CategoryID, CategoryName FROM Categories ORDER BY CategoryName;")
    categories = cursor.fetchall()
    cursor.close()
    conn.close()
    return categories

# -----------------------------------------------------------------------------
# 5) The main route: search & filter form, plus results
# -----------------------------------------------------------------------------
@app.route("/search", methods=["GET"])
def search():
    # Read GET parameters from the request URL
    title_query     = request.args.get("title", "").strip()
    author_id_str   = request.args.get("author_id", "").strip()
    category_id_str = request.args.get("category_id", "").strip()

    # Fetch dropdown options
    authors = fetch_all_authors()
    categories = fetch_all_categories()

    # Build WHERE clauses dynamically
    where_clauses = []
    params = []

    if title_query:
        where_clauses.append("(b.title LIKE %s OR b.description LIKE %s)")
        like_pattern = f"%{title_query}%"
        params.extend([like_pattern, like_pattern])

    if author_id_str.isdigit():
        where_clauses.append("ba.AuthorID = %s")
        params.append(int(author_id_str))

    if category_id_str.isdigit():
        where_clauses.append("bc.CategoryID = %s")
        params.append(int(category_id_str))

    # Updated SELECT: remove page_length entirely
    base_query = """
        SELECT 
          b.BookID,
          b.title,
          b.ean_isbn13,                        -- pull ISBN-13
          b.upc_isbn10,                        -- pull ISBN-10
          b.description,                       -- actual description text
          b.publisher,
          b.publish_date,
          GROUP_CONCAT(DISTINCT a.FullName SEPARATOR ', ')  AS Authors,
          GROUP_CONCAT(DISTINCT c.CategoryName SEPARATOR ', ') AS Categories
        FROM Books b
        LEFT JOIN BookAuthors ba ON ba.BookID = b.BookID
        LEFT JOIN Authors a     ON a.AuthorID = ba.AuthorID
        LEFT JOIN BookCategories bc ON bc.BookID = b.BookID
        LEFT JOIN Categories c      ON c.CategoryID = bc.CategoryID
    """

    # Append WHERE clauses if any filters exist
    if where_clauses:
        sql = base_query + " WHERE " + " AND ".join(where_clauses) + " GROUP BY b.BookID ORDER BY b.title ASC;"
    else:
        sql = base_query + " GROUP BY b.BookID ORDER BY b.title ASC;"

    # === Debug: print the final SQL and params ===
    print("=== DEBUG SQL ===")
    print(sql)
    print("=== DEBUG PARAMS ===")
    print(params)

    results = []
    # Only query if at least one filter is present
    if title_query or author_id_str.isdigit() or category_id_str.isdigit():
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(sql, params)
        results = cursor.fetchall()
        print("=== DEBUG RESULTS ROWCOUNT ===", len(results))
        cursor.close()
        conn.close()

    return render_template(
        "search.html",
        authors=authors,
        categories=categories,
        results=results,
        form_data={
            "title": title_query,
            "author_id": author_id_str,
            "category_id": category_id_str
        }
    )

# -----------------------------------------------------------------------------
# 6) Home route: redirect root URL to /search
# -----------------------------------------------------------------------------
@app.route("/")
def home():
    return redirect(url_for("search"))

# -----------------------------------------------------------------------------
# 7) Run the Flask app
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(debug=True)