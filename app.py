# app.py
import os
import sqlite3
import numpy as np
from flask import Flask, render_template, request, redirect, url_for
from dotenv import load_dotenv

# -----------------------------------------------------------------------------
# 1) Load environment variables from .env
# -----------------------------------------------------------------------------
load_dotenv()  # do NOT remove

DB_FILE     = os.environ.get("DB_FILE", "library.db")
SECRET_KEY  = os.environ.get("SECRET_KEY", "dev_secret_key")

# -----------------------------------------------------------------------------
# 2) Create Flask app
# -----------------------------------------------------------------------------
app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY

# -----------------------------------------------------------------------------
# 3) Helper: get a new SQLite connection
# -----------------------------------------------------------------------------
def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

# -----------------------------------------------------------------------------
# 4) Load/Initialize a smaller Sentence‐Transformer model + embeddings
# -----------------------------------------------------------------------------
# Switch to a more compact model (e.g. parabhrase‐albert‐small‐v2), which uses far less memory.
# You can experiment with any of the smaller models listed here:
# https://www.sbert.net/docs/pretrained_models.html
from sentence_transformers import SentenceTransformer, util

MODEL_NAME = os.environ.get("SENTENCE_MODEL", "paraphrase-albert-small-v2")
model = SentenceTransformer(MODEL_NAME)

book_ids        = []
book_embeddings = None

def build_book_embeddings():
    global book_ids, book_embeddings

    conn = get_db_connection()
    cur  = conn.cursor()
    cur.execute("SELECT BookID, description FROM Books;")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    descriptions = []
    book_ids     = []
    for r in rows:
        book_ids.append(r["BookID"])
        descriptions.append(r["description"] or "")

    # Compute embeddings (PyTorch tensor) once at startup
    book_embeddings = model.encode(
        descriptions,
        convert_to_tensor=True,
        show_progress_bar=False
    )

# Build all‐book embeddings at startup
build_book_embeddings()

# -----------------------------------------------------------------------------
# 5) Helper functions for dropdowns
# -----------------------------------------------------------------------------
def fetch_all_authors():
    conn = get_db_connection()
    cur  = conn.cursor()
    cur.execute("SELECT AuthorID, FullName FROM Authors ORDER BY FullName;")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [(row["AuthorID"], row["FullName"]) for row in rows]

def fetch_all_categories():
    conn = get_db_connection()
    cur  = conn.cursor()
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
# 6) Main route: search + “mood” (NLP) query
# -----------------------------------------------------------------------------
@app.route("/search", methods=["GET"])
def search():
    # 1) Read all GET parameters, including the new “nlp” field
    title_query     = request.args.get("title", "").strip()
    author_id_str   = request.args.get("author_id", "").strip()
    category_id_str = request.args.get("category_id", "").strip()
    nlp_query       = request.args.get("nlp", "").strip()     # ← always include in form_data
    sort_by         = request.args.get("sort_by", "").strip()
    sort_dir        = request.args.get("sort_dir", "").strip().lower()

    # 2) Fetch dropdown options
    authors    = fetch_all_authors()
    categories = fetch_all_categories()

    # 3) Build normal WHERE clauses (title/author/category)
    where_clauses = []
    params        = []
    if title_query:
        where_clauses.append("(b.title LIKE ? OR b.description LIKE ?)")
        pat = f"%{title_query}%"
        params.extend([pat, pat])
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
            GROUP_CONCAT(DISTINCT a.FullName)     AS Authors,
            GROUP_CONCAT(DISTINCT c.CategoryName) AS Categories
        FROM Books b
        LEFT JOIN BookAuthors ba       ON ba.BookID = b.BookID
        LEFT JOIN Authors a           ON a.AuthorID = ba.AuthorID
        LEFT JOIN BookCategories bc   ON bc.BookID = b.BookID
        LEFT JOIN Categories c        ON c.CategoryID = bc.CategoryID
    """

    # 5) Sorting logic
    valid_sort_columns = {"title", "description", "publisher", "publish_date"}
    if sort_by not in valid_sort_columns:
        sort_by = "title"
    if sort_dir not in {"asc", "desc"}:
        sort_dir = "asc"

    # 6) If the user supplied an NLP query, do semantic retrieval
    semantic_ids = None
    if nlp_query:
        # Embed the free‐text “mood” query (PyTorch tensor)
        query_embedding = model.encode(nlp_query, convert_to_tensor=True)
        # Compute cosine similarities against all precomputed book_embeddings
        cos_scores = util.pytorch_cos_sim(query_embedding, book_embeddings)[0]
        # Pick the top 20 matches by score
        top_idxs = np.argpartition(-cos_scores.cpu().numpy(), range(20))[:20]
        # Sort those top 20 by descending cosine value
        top_sorted = sorted(
            top_idxs.tolist(),
            key=lambda i: cos_scores[i].item(),
            reverse=True
        )
        semantic_ids = [book_ids[i] for i in top_sorted]

    results = []
    conn   = get_db_connection()
    cursor = conn.cursor()

    if semantic_ids:
        # ─── A) Semantic path: only return exactly those semantic_ids, in ranked order ───
        placeholders = ", ".join("?" for _ in semantic_ids)
        # Build a CASE expression so ORDER BY preserves our ranking
        case_parts = [f"WHEN ? THEN {idx}" for idx, _ in enumerate(semantic_ids)]
        case_expr  = " ".join(case_parts)

        sql = (
            base_query
            + f" WHERE b.BookID IN ({placeholders}) "
            + " GROUP BY b.BookID "
            + f" ORDER BY CASE b.BookID {case_expr} END;"
        )

        in_params   = [int(bid) for bid in semantic_ids]
        case_params = [int(bid) for bid in semantic_ids]
        all_params  = in_params + case_params

        cursor.execute(sql, all_params)
        fetched = cursor.fetchall()
        results = [dict(row) for row in fetched]

    else:
        # ─── B) No “mood” query: do title/author/category filters ───
        if where_clauses:
            sql = (
                base_query
                + " WHERE " + " AND ".join(where_clauses)
                + f" GROUP BY b.BookID ORDER BY b.{sort_by} {sort_dir.upper()};"
            )
        else:
            sql = base_query + f" GROUP BY b.BookID ORDER BY b.{sort_by} {sort_dir.upper()};"

        # Debugging output
        print("=== DEBUG SQL ===")
        print(sql)
        print("=== DEBUG PARAMS ===")
        print(params)

        # Only execute if at least one non-NLP filter exists
        if title_query or author_id_str.isdigit() or category_id_str.isdigit():
            cursor.execute(sql, params)
            fetched = cursor.fetchall()
            results = [dict(row) for row in fetched]

    cursor.close()
    conn.close()

    # 7) Finally, render “search.html” (always include “nlp” in form_data)
    return render_template(
        "search.html",
        authors=authors,
        categories=categories,
        results=results,
        form_data={
            "title":       title_query,
            "author_id":   author_id_str,
            "category_id": category_id_str,
            "nlp":         nlp_query,   # ← must always be present
            "sort_by":     sort_by,
            "sort_dir":    sort_dir
        }
    )

# -----------------------------------------------------------------------------
# 8) Add route: identical to before, but rebuild embeddings on new book
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
        publish_date = request.form.get("publish_date", "").strip()
        author_id    = request.form.get("author_id", "").strip()
        category_id  = request.form.get("category_id", "").strip()

        if not title or not author_id.isdigit() or not category_id.isdigit():
            message = "Title, Author, and Genre are required."
            return render_template("add.html",
                                   authors=authors,
                                   categories=categories,
                                   message=message)

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
                    description or None,
                    ean_isbn13 or None,
                    upc_isbn10 or None,
                    publisher or None,
                    publish_date or None
                )
            )
            new_book_id = cursor.lastrowid

            cursor.execute(
                "INSERT INTO BookAuthors (BookID,AuthorID) VALUES (?,?);",
                (new_book_id, int(author_id))
            )
            cursor.execute(
                "INSERT INTO BookCategories (BookID,CategoryID) VALUES (?,?);",
                (new_book_id, int(category_id))
            )
            conn.commit()
            message = f"Book “{title}” was successfully added."

            # Rebuild embeddings to include the newly added description
            build_book_embeddings()
        except Exception as e:
            conn.rollback()
            message = f"Error adding book: {e}"
        finally:
            cursor.close()
            conn.close()

        return render_template("add.html",
                               authors=authors,
                               categories=categories,
                               message=message)

    return render_template("add.html",
                           authors=authors,
                           categories=categories,
                           message=None)

# -----------------------------------------------------------------------------
# 9) Home route: redirect root URL to /search
# -----------------------------------------------------------------------------
@app.route("/")
def home():
    return redirect(url_for("search"))

# -----------------------------------------------------------------------------
# 10) Run the Flask app
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=True)