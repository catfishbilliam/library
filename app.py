import os
import sqlite3
from flask import Flask, render_template, request, redirect, url_for
from dotenv import load_dotenv

# -----------------------------------------------------------------------------
# 1) Load environment variables from .env (if you have any for SECRET_KEY, etc.)
# -----------------------------------------------------------------------------
load_dotenv()

SECRET_KEY = os.environ.get("SECRET_KEY", "dev_secret_key")  # for Flask session, if needed

# -----------------------------------------------------------------------------
# 2) Create Flask app
# -----------------------------------------------------------------------------
app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY

# -----------------------------------------------------------------------------
# 3) Initialize a SQLite connection on demand
# -----------------------------------------------------------------------------
def get_db_connection():
    """
    Returns a new SQLite connection to 'library.db'. 
    If the file does not exist, it will be created when we run initialization.
    """
    conn = sqlite3.connect("library.db")
    conn.row_factory = sqlite3.Row  # So rows behave like dicts
    return conn

# -----------------------------------------------------------------------------
# 4) Helper functions to fetch authors & categories (for dropdown lists)
# -----------------------------------------------------------------------------
def fetch_all_authors():
    """
    Returns a list of (AuthorID, FullName) tuples from the Authors table.
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
    Returns a list of (CategoryID, CategoryName) tuples from the Categories table.
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
        where_clauses.append("(b.title LIKE ? OR b.description LIKE ?)")
        like_pattern = f"%{title_query}%"
        params.extend([like_pattern, like_pattern])

    if author_id_str.isdigit():
        where_clauses.append("ba.AuthorID = ?")
        params.append(int(author_id_str))

    if category_id_str.isdigit():
        where_clauses.append("bc.CategoryID = ?")
        params.append(int(category_id_str))

    base_query = """
        SELECT 
          b.BookID,
          b.title,
          b.ean_isbn13,                        
          b.upc_isbn10,                        
          b.description,                       
          b.publisher,
          b.publish_date,
          GROUP_CONCAT(DISTINCT a.FullName, ', ') AS Authors,
          GROUP_CONCAT(DISTINCT c.CategoryName, ', ') AS Categories
        FROM Books b
        LEFT JOIN BookAuthors ba ON ba.BookID = b.BookID
        LEFT JOIN Authors a     ON a.AuthorID = ba.AuthorID
        LEFT JOIN BookCategories bc ON bc.BookID = b.BookID
        LEFT JOIN Categories c      ON c.CategoryID = bc.CategoryID
    """

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