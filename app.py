# app.py
import os
import sqlite3
from flask import Flask, render_template, request, redirect, url_for
from dotenv import load_dotenv

# -----------------------------------------------------------------------------
# 1) Load environment variables from .env
# -----------------------------------------------------------------------------
load_dotenv()  # Do NOT change this line

DB_FILE     = os.environ.get("DB_FILE", "library.db")  # SQLite database filename
SECRET_KEY  = os.environ.get("SECRET_KEY", "dev_secret_key")  # For Flask sessions

# -----------------------------------------------------------------------------
# 2) Create Flask app
# -----------------------------------------------------------------------------
app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY

# -----------------------------------------------------------------------------
# 3) Helper: get a new SQLite connection
# -----------------------------------------------------------------------------
def get_db_connection():
    """
    Opens a new SQLite3 connection and returns it.
    """
    conn = sqlite3.connect(DB_FILE)
    # Return rows as dictionaries (if you prefer), or you can fetch as tuples.
    conn.row_factory = sqlite3.Row
    return conn

# -----------------------------------------------------------------------------
# 4) Helper functions to fetch authors & categories (for dropdown lists)
# -----------------------------------------------------------------------------
def fetch_all_authors():
    """
    Returns a list of tuples: (AuthorID, FullName) sorted by FullName.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT AuthorID, FullName FROM Authors ORDER BY FullName;")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    # Convert sqlite3.Row to simple tuples
    return [(row["AuthorID"], row["FullName"]) for row in rows]

def fetch_all_categories():
    """
    Returns a list of tuples: (CategoryID, CategoryName) sorted by CategoryName.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT CategoryID, CategoryName FROM Categories ORDER BY CategoryName;")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [(row["CategoryID"], row["CategoryName"]) for row in rows]

# -----------------------------------------------------------------------------
# 5) Main route: search & filter form, plus results
# -----------------------------------------------------------------------------
@app.route("/search", methods=["GET"])
def search():
    # Read GET parameters from the request URL
    title_query     = request.args.get("title", "").strip()
    author_id_str   = request.args.get("author_id", "").strip()
    category_id_str = request.args.get("category_id", "").strip()
    sort_by         = request.args.get("sort_by", "").strip()
    sort_dir        = request.args.get("sort_dir", "asc").strip().lower()

    # Fetch dropdown options
    authors    = fetch_all_authors()
    categories = fetch_all_categories()

    # Build dynamic WHERE clauses
    where_clauses = []
    params        = []

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

    # Base SELECT (note: using SQLite‐compatible GROUP_CONCAT here)
    base_query = """
        SELECT 
          b.BookID,
          b.title,
          b.ean_isbn13,
          b.upc_isbn10,
          b.description,
          b.publisher,
          b.publish_date,
          GROUP_CONCAT(DISTINCT a.FullName)  AS Authors,
          GROUP_CONCAT(DISTINCT c.CategoryName) AS Categories
        FROM Books b
        LEFT JOIN BookAuthors ba ON ba.BookID = b.BookID
        LEFT JOIN Authors a     ON a.AuthorID = ba.AuthorID
        LEFT JOIN BookCategories bc ON bc.BookID = b.BookID
        LEFT JOIN Categories c      ON c.CategoryID = bc.CategoryID
    """

    # If any filters exist, append them:
    if where_clauses:
        sql = (
            base_query
            + " WHERE " + " AND ".join(where_clauses)
            + " GROUP BY b.BookID"
        )
    else:
        sql = base_query + " GROUP BY b.BookID"

    # Append ORDER BY clause. Default to title ASC if nothing else:
    if sort_by in ("title", "description", "publisher", "publish_date") and sort_dir in ("asc", "desc"):
        sql += f" ORDER BY b.{sort_by} {sort_dir.upper()};"
    else:
        sql += " ORDER BY b.title ASC;"

    # === Debug: print SQL & params to console (optional) ===
    print("=== DEBUG SQL ===")
    print(sql)
    print("=== DEBUG PARAMS ===")
    print(params)

    results = []
    # Only query if at least one filter is present (or you could always run it,
    # but we follow your existing logic)
    if title_query or author_id_str.isdigit() or category_id_str.isdigit():
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(sql, params)
        fetched = cursor.fetchall()
        # Convert Row objects to dicts or tuples as you like. Here, we'll send them to Jinja as dicts:
        results = [dict(row) for row in fetched]
        print("=== DEBUG RESULTS ROWCOUNT ===", len(results))
        cursor.close()
        conn.close()

    return render_template(
        "search.html",
        authors=authors,
        categories=categories,
        results=results,
        form_data={
            "title":        title_query,
            "author_id":    author_id_str,
            "category_id":  category_id_str,
            "sort_by":      sort_by,
            "sort_dir":     sort_dir,
        }
    )

# -----------------------------------------------------------------------------
# 6) Add route: show form to add new book / process form submission
# -----------------------------------------------------------------------------
@app.route("/add", methods=["GET", "POST"])
def add():
    authors    = fetch_all_authors()
    categories = fetch_all_categories()

    if request.method == "POST":
        # Gather form data
        title        = request.form.get("title", "").strip()
        description  = request.form.get("description", "").strip()
        ean_isbn13   = request.form.get("ean_isbn13", "").strip()
        upc_isbn10   = request.form.get("upc_isbn10", "").strip()
        publisher    = request.form.get("publisher", "").strip()
        publish_date = request.form.get("publish_date", "").strip()  # expects YYYY-MM-DD
        author_id    = request.form.get("author_id", "").strip()
        category_id  = request.form.get("category_id", "").strip()

        # Basic validation: ensure required fields are present
        if not title or not author_id.isdigit() or not category_id.isdigit():
            message = "Title, Author, and Genre are required."
            return render_template(
                "add.html", authors=authors, categories=categories, message=message
            )

        conn   = get_db_connection()
        cursor = conn.cursor()

        try:
            # 1) Insert into Books
            insert_book_sql = """
                INSERT INTO Books
                  (title, description, ean_isbn13, upc_isbn10, publisher, publish_date)
                VALUES (?, ?, ?, ?, ?, ?);
            """
            cursor.execute(
                insert_book_sql,
                (
                    title,
                    description if description else None,
                    ean_isbn13 if ean_isbn13 else None,
                    upc_isbn10 if upc_isbn10 else None,
                    publisher if publisher else None,
                    publish_date if publish_date else None
                )
            )
            new_book_id = cursor.lastrowid

            # 2) Insert into BookAuthors
            insert_ba_sql = "INSERT INTO BookAuthors (BookID, AuthorID) VALUES (?, ?);"
            cursor.execute(insert_ba_sql, (new_book_id, int(author_id)))

            # 3) Insert into BookCategories
            insert_bc_sql = "INSERT INTO BookCategories (BookID, CategoryID) VALUES (?, ?);"
            cursor.execute(insert_bc_sql, (new_book_id, int(category_id)))

            conn.commit()
            message = f"Book \"{title}\" was successfully added."
        except Exception as e:
            conn.rollback()
            message = f"Error adding book: {str(e)}"
        finally:
            cursor.close()
            conn.close()

        return render_template(
            "add.html", authors=authors, categories=categories, message=message
        )

    # If GET: simply show the “add a new book” form
    return render_template(
        "add.html", authors=authors, categories=categories, message=None
    )

# -----------------------------------------------------------------------------
# 7) Home route: redirect root URL to /search
# -----------------------------------------------------------------------------
@app.route("/")
def home():
    return redirect(url_for("search"))

# -----------------------------------------------------------------------------
# 8) Run the Flask app
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    # By default, Flask will run on port 5000. For deployment on Render (or similar),
    # Render will set $PORT automatically. We can let Flask read it if necessary.
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=True)