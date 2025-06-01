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
    # Return rows as dictionaries (optional)
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
    cur = conn.cursor()
    cur.execute("SELECT AuthorID, FullName FROM Authors ORDER BY FullName;")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [(row["AuthorID"], row["FullName"]) for row in rows]

def fetch_all_categories():
    """
    Returns a list of tuples: (CategoryID, CategoryName) sorted by CategoryName,
    but only those categories which have at least one book assigned.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT c.CategoryID, c.CategoryName
          FROM Categories c
          JOIN BookCategories bc ON bc.CategoryID = c.CategoryID
         GROUP BY c.CategoryID
         ORDER BY c.CategoryName;
    """)
    rows = cur.fetchall()
    cur.close()
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
    sort_by         = request.args.get("sort_by",   "").strip()
    sort_dir        = request.args.get("sort_dir",  "").strip().lower()  # expect "asc" or "desc"

    # Fetch dropdown options
    authors    = fetch_all_authors()
    categories = fetch_all_categories()

    # Build WHERE clauses dynamically
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

    # Base SELECT: use SQLite‐compatible GROUP_CONCAT syntax (only one argument when using DISTINCT)
    base_query = """
        SELECT 
            b.BookID,
            b.title,
            b.ean_isbn13,
            b.upc_isbn10,
            b.description,
            b.publisher,
            b.publish_date,
            GROUP_CONCAT(DISTINCT a.FullName)       AS Authors,
            GROUP_CONCAT(DISTINCT c.CategoryName)   AS Categories
        FROM Books b
        LEFT JOIN BookAuthors ba       ON ba.BookID = b.BookID
        LEFT JOIN Authors a           ON a.AuthorID = ba.AuthorID
        LEFT JOIN BookCategories bc   ON bc.BookID = b.BookID
        LEFT JOIN Categories c        ON c.CategoryID = bc.CategoryID
    """

    # Decide on ORDER BY clause
    # Allow only certain columns to be sorted on; default to title ASC if no valid sort
    valid_sort_columns = {"title", "description", "publisher", "publish_date"}
    if sort_by not in valid_sort_columns:
        sort_by = "title"
    if sort_dir not in {"asc", "desc"}:
        sort_dir = "asc"

    # Append WHERE and GROUP BY and ORDER BY
    if where_clauses:
        sql = (
            base_query
            + " WHERE " + " AND ".join(where_clauses)
            + f" GROUP BY b.BookID ORDER BY b.{sort_by} {sort_dir.upper()};"
        )
    else:
        sql = base_query + f" GROUP BY b.BookID ORDER BY b.{sort_by} {sort_dir.upper()};"

    # === Debug: print SQL & params to console (optional) ===
    print("=== DEBUG SQL ===")
    print(sql)
    print("=== DEBUG PARAMS ===")
    print(params)

    results = []
    # Only query if at least one filter or sorting is present
    if title_query or author_id_str.isdigit() or category_id_str.isdigit():
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(sql, params)
        fetched = cursor.fetchall()
        results = [dict(row) for row in fetched]  # Convert Row to dict
        print("=== DEBUG RESULTS ROWCOUNT ===", len(results))
        cursor.close()
        conn.close()

    return render_template(
        "search.html",
        authors=authors,
        categories=categories,
        results=results,
        form_data={
            "title":       title_query,
            "author_id":   author_id_str,
            "category_id": category_id_str,
            "sort_by":     sort_by,
            "sort_dir":    sort_dir
        }
    )

# -----------------------------------------------------------------------------
# 6) Add route: show form to add new book / process form submission
# -----------------------------------------------------------------------------
@app.route("/add", methods=["GET", "POST"])
def add():
    # Fetch dropdown options (authors + categories)
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