#!/usr/bin/env python3
"""
initialize_db.py

Creates (or recreates) library.db next to this script and populates it from CSVs.

Expected folder layout:

project_root/
│
├── csv_data/
│   ├── books.csv
│   ├── authors.csv
│   ├── categories.csv
│   ├── bookauthors.csv
│   └── bookcategories.csv
│
└── library_webapp/
    ├── app.py
    ├── initialize_db.py   <-- this file
    └── templates/
"""

import os
import sqlite3
import csv
import sys

# 1) Compute this script’s directory and set DB_FILE accordingly
script_dir = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(script_dir, "library.db")

# 2) Remove existing DB if present
if os.path.exists(DB_FILE):
    os.remove(DB_FILE)
    print(f"Removed existing {DB_FILE}")

# 3) Connect/create the new SQLite file
try:
    conn = sqlite3.connect(DB_FILE)
except sqlite3.OperationalError as e:
    print(f"ERROR: Cannot create or open {DB_FILE}: {e}")
    sys.exit(1)

cursor = conn.cursor()

# 4) Create tables in SQLite syntax
cursor.execute("""
CREATE TABLE Books (
    BookID INTEGER PRIMARY KEY,
    title TEXT,
    ean_isbn13 TEXT,
    upc_isbn10 TEXT,
    description TEXT,
    publisher TEXT,
    publish_date TEXT,
    page_length INTEGER
);
""")

cursor.execute("""
CREATE TABLE Authors (
    AuthorID INTEGER PRIMARY KEY,
    FullName TEXT
);
""")

cursor.execute("""
CREATE TABLE Categories (
    CategoryID INTEGER PRIMARY KEY,
    CategoryName TEXT
);
""")

cursor.execute("""
CREATE TABLE BookAuthors (
    BookID INTEGER,
    AuthorID INTEGER,
    PRIMARY KEY (BookID, AuthorID),
    FOREIGN KEY (BookID) REFERENCES Books(BookID) ON DELETE CASCADE,
    FOREIGN KEY (AuthorID) REFERENCES Authors(AuthorID) ON DELETE CASCADE
);
""")

cursor.execute("""
CREATE TABLE BookCategories (
    BookID INTEGER,
    CategoryID INTEGER,
    PRIMARY KEY (BookID, CategoryID),
    FOREIGN KEY (BookID) REFERENCES Books(BookID) ON DELETE CASCADE,
    FOREIGN KEY (CategoryID) REFERENCES Categories(CategoryID) ON DELETE CASCADE
);
""")

conn.commit()
print("Created tables in library.db")

# 5) Helper to load a CSV into a table, tolerating missing columns
def load_csv_to_table(csv_filename, table_name, columns):
    """
    Reads csv_filename (full path), inserts rows into table_name.
    - 'columns' is a list of expected column names. If a column is missing in the CSV header,
      we insert None for that column.
    """
    if not os.path.isfile(csv_filename):
        print(f"ERROR: CSV not found at {csv_filename}")
        sys.exit(1)

    with open(csv_filename, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        # We don't rely on reader.fieldnames being exactly columns, 
        # but use columns[] and default to None if missing.
        placeholders = ", ".join("?" for _ in columns)
        column_list = ", ".join(columns)
        sql = f"INSERT INTO {table_name} ({column_list}) VALUES ({placeholders});"
        count = 0
        for row in reader:
            # For each expected column name, if it's not in row, use None.
            values = []
            for col in columns:
                if col in row and row[col] != "":
                    values.append(row[col])
                else:
                    values.append(None)
            cursor.execute(sql, values)
            count += 1
        conn.commit()
        print(f"  → Inserted {count} rows into {table_name}")

# 6) Compute path to csv_data folder
project_root = os.path.dirname(script_dir)
csv_folder = os.path.join(project_root, "csv_data")

print("Loading data from CSVs...")

# 7) Load CSVs into tables, using the “columns” you expect. 
#    If a CSV lacks some columns, those values become NULL.

# Books table: if books.csv lacks 'page_length', that field becomes NULL
load_csv_to_table(
    os.path.join(csv_folder, "books.csv"),
    "Books",
    ["BookID", "title", "ean_isbn13", "upc_isbn10",
     "description", "publisher", "publish_date", "page_length"]
)

load_csv_to_table(
    os.path.join(csv_folder, "authors.csv"),
    "Authors",
    ["AuthorID", "FullName"]
)

load_csv_to_table(
    os.path.join(csv_folder, "categories.csv"),
    "Categories",
    ["CategoryID", "CategoryName"]
)

load_csv_to_table(
    os.path.join(csv_folder, "bookauthors.csv"),
    "BookAuthors",
    ["BookID", "AuthorID"]
)

load_csv_to_table(
    os.path.join(csv_folder, "bookcategories.csv"),
    "BookCategories",
    ["BookID", "CategoryID"]
)

# 8) Quick verification
cursor.execute("SELECT COUNT(*) FROM Authors;")
author_count = cursor.fetchone()[0]
cursor.execute("SELECT COUNT(*) FROM Categories;")
category_count = cursor.fetchone()[0]
cursor.execute("SELECT COUNT(*) FROM Books;")
book_count = cursor.fetchone()[0]

print(f"\nVerification:")
print(f"  - Authors table has {author_count} rows")
print(f"  - Categories table has {category_count} rows")
print(f"  - Books table has {book_count} rows")

# 9) Clean up
conn.close()
print("\nFinished initializing library.db")