# app.py
import os
import sqlite3
import numpy as np
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
    conn.row_factory = sqlite3.Row
    return conn

# -----------------------------------------------------------------------------
# 4) Load/Initialize Sentence‐Transformer model + embeddings
# -----------------------------------------------------------------------------
from sentence_transformers import SentenceTransformer, util

MODEL_NAME = os.environ.get("SENTENCE_MODEL", "all-MiniLM-L6-v2")
model = SentenceTransformer(MODEL_NAME)

# These will be populated on startup:
book_ids: list[int] = []
book_embeddings = None  # a tensor or numpy array

def build_book_embeddings():
    """
    Read all book descriptions from SQLite, compute embeddings,
    and store them in global `book_embeddings` and `book_ids`.
    """
    global book_ids, book_embeddings
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT BookID, description FROM Books;")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    # If a description is NULL, replace with empty string:
    descriptions = []
    book_ids = []
    for row in rows:
        book_ids.append(row["BookID"])
        desc = row["description"] or ""
        descriptions.append(desc)

    # Compute all‐descriptions embeddings (convert_to_tensor=True yields a PyTorch tensor)
    book_embeddings = model.encode(descriptions, convert_to_tensor=True, show_progress_bar=False)

# Build embeddings once at import time (or app startup):
build_book_embeddings()

# -----------------------------------------------------------------------------
# 5) Helper functions to fetch authors & categories (for dropdown lists)
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
# 6) Main route: search & filter form, plus results (including NLP “mood” search)
# -----------------------------------------------------------------------------
@app.route("/search", methods=["GET"])
def search():
    # 1) Read GET parameters from the request URL
    title_query     = request.args.get("title", "").strip()
    author_id_str   = request.args.get("author_id", "").strip()
    category_id_str = request.args.get("category_id", "").strip()
    nlp_query       = request.args.get("nlp", "").strip()   # new free‐text “mood” field
    sort_by         = request.args.get("sort_by",   "").strip()
    sort_dir        = request.args.get("sort_dir",  "").strip().lower()  # expect "asc" or "desc"

    # 2) Fetch dropdown options
    authors    = fetch_all_authors()
    categories = fetch_all_categories()

    # 3) Build WHERE clauses for SQL if user used title/author/category filters
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

    # 4) Base SELECT (SQLite‐compatible GROUP_CONCAT)
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

    # 5) Decide on ORDER BY clause
    valid_sort_columns = {"title", "description", "publisher", "publish_date"}
    if sort_by not in valid_sort_columns:
        sort_by = "title"
    if sort_dir not in {"asc", "desc"}:
        sort_dir = "asc"

    # 6) If the user supplied an NLP query, perform a semantic retrieval
    semantic_ids = None
    if nlp_query:
        # Compute embedding for the user’s free-text query
        query_embedding = model.encode(nlp_query, convert_to_tensor=True)
        # Compute cosine‐similarities against all book_embeddings
        cos_scores = util.pytorch_cos_sim(query_embedding, book_embeddings)[0]  # shape = (num_books,)
        # Take top N results (e.g. top 20)
        top_results = np.argpartition(-cos_scores.cpu().numpy(), range(20))[:20]
        # Sort those top_results by score descending
        top_sorted = sorted(top_results.tolist(),
                            key=lambda i: cos_scores[i].item(),
                            reverse=True)
        # Extract the corresponding BookIDs in that order
        semantic_ids = [book_ids[i] for i in top_sorted]

    # 7) If semantic_ids is set, we override other filters and only return those IDs
    results = []
    conn   = get_db_connection()
    cursor = conn.cursor()

    if semantic_ids:
        # Build a parameter list (?, ?, ?, …)
        placeholders = ", ".join("?" for _ in semantic_ids)
        sql = (
            base_query
            + f" WHERE b.BookID IN ({placeholders}) "
            + f" GROUP BY b.BookID ORDER BY CASE b.BookID {' '.join(f'WHEN ? THEN {i}' for i in range(len(semantic_ids)))} END;"
        )
        # For the ranking CASE, we need to append the IDs again in the correct order
        case_params = [str(bid) for bid in semantic_ids]
        all_params = [*semantic_ids, *case_params]
        cursor.execute(sql, all_params)
        fetched = cursor.fetchall()
        results = [dict(row) for row in fetched]
    else:
        # Normal (keyword + author + category) filtering
        if where_clauses:
            sql = (
                base_query
                + " WHERE " + " AND ".join(where_clauses)
                + f" GROUP BY b.BookID ORDER BY b.{sort_by} {sort_dir.upper()};"
            )
        else:
            sql = base_query + f" GROUP BY b.BookID ORDER BY b.{sort_by} {sort_dir.upper()};"

        # Debug
        print("=== DEBUG SQL ===")
        print(sql)
        print("=== DEBUG PARAMS ===")
        print(params)

        # Only fire SQL if at least one filter present
        if title_query or author_id_str.isdigit() or category_id_str.isdigit():
            cursor.execute(sql, params)
            fetched = cursor.fetchall()
            results = [dict(row) for row in fetched]

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
            "nlp":         nlp_query,
            "sort_by":     sort_by,
            "sort_dir":    sort_dir
        }
    )

# -----------------------------------------------------------------------------
# 7) Add route: show form to add new book / process form submission
# (unchanged from before)
# -----------------------------------------------------------------------------
@app.route("/add", methods=["GET", "POST"])
def add():
    authors    = fetch_all_authors()
    categories = fetch_all_categories()

    if request.method == "POST":
        title        = request.form.get("title", "").strip()
        description  = request.form.get("description", "").strip()
        ean_isbn13   = request.form.get("ean_isbn13", "").strip()
        upc_isbn10   = request.form.get("upc_isbn10", "").strip()
        publisher    = request.form.get("publisher", "").strip()
        publish_date = request.form.get("publish_date", "").strip()  # YYYY-MM-DD
        author_id    = request.form.get("author_id", "").strip()
        category_id  = request.form.get("category_id", "").strip()

        if not title or not author_id.isdigit() or not category_id.isdigit():
            message = "Title, Author, and Genre are required."
            return render_template(
                "add.html", authors=authors, categories=categories, message=message
            )

        conn   = get_db_connection()
        cursor = conn.cursor()

        try:
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

            insert_ba_sql = "INSERT INTO BookAuthors (BookID, AuthorID) VALUES (?, ?);"
            cursor.execute(insert_ba_sql, (new_book_id, int(author_id)))

            insert_bc_sql = "INSERT INTO BookCategories (BookID, CategoryID) VALUES (?, ?);"
            cursor.execute(insert_bc_sql, (new_book_id, int(category_id)))

            conn.commit()
            message = f"Book \"{title}\" was successfully added."

            # Rebuild embeddings to include the newly added book’s description
            build_book_embeddings()
        except Exception as e:
            conn.rollback()
            message = f"Error adding book: {str(e)}"
        finally:
            cursor.close()
            conn.close()

        return render_template(
            "add.html", authors=authors, categories=categories, message=message
        )

    return render_template(
        "add.html", authors=authors, categories=categories, message=None
    )

# -----------------------------------------------------------------------------
# 8) Home route: redirect root URL to /search
# -----------------------------------------------------------------------------
@app.route("/")
def home():
    return redirect(url_for("search"))

# -----------------------------------------------------------------------------
# 9) Run the Flask app
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=True)