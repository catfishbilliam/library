#!/usr/bin/env python3
"""
export_csvs.py

Connects to your MySQL database (Workbench) and exports the following tables as CSVs into the local
`csv_data/` directory (creating it if necessary):

    - books.csv         (BookID, title, ean_isbn13, upc_isbn10, description, publisher, publish_date)
    - authors.csv       (AuthorID, FullName)
    - categories.csv    (CategoryID, CategoryName)
    - bookauthors.csv   (BookID, AuthorID)
    - bookcategories.csv (BookID, CategoryID)

Usage:
    1) Edit the DB credentials at the top of this file (DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME).
    2) Ensure `mysql-connector-python` is installed:
         pip install mysql-connector-python
    3) Run:
         python3 export_csvs.py

After running, check `csv_data/`—it will contain the five exported CSV files.
"""

import os
import csv
import errno
import mysql.connector

# -----------------------------------------------------------------------------
# 1) DATABASE CREDENTIALS (edit these directly; no .env file needed)
# -----------------------------------------------------------------------------
DB_HOST     = "localhost"
DB_PORT     = 3306
DB_USER     = "myuser"
DB_PASSWORD = "1101955BjC"
DB_NAME     = "LibraryDB"

# -----------------------------------------------------------------------------
# 2) Directory to write CSVs into
# -----------------------------------------------------------------------------
CSV_DIR = os.path.join(os.path.dirname(__file__), "csv_data")


def ensure_csv_dir():
    """
    Create the csv_data directory if it doesn't exist.
    """
    try:
        os.makedirs(CSV_DIR, exist_ok=True)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise


def get_db_connection():
    """
    Return a new MySQL connection using mysql.connector,
    based on the hardcoded credentials above.
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


def export_table_to_csv(table_name, column_list, csv_filename):
    """
    Query the given table_name (selecting only columns in column_list),
    and write them out to csv_filename (inside CSV_DIR). The first row
    will be headers (column names).
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cols = ", ".join(column_list)
    query = f"SELECT {cols} FROM {table_name} ORDER BY {column_list[0]};"
    cursor.execute(query)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    out_path = os.path.join(CSV_DIR, csv_filename)
    with open(out_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        # Write header row
        writer.writerow(column_list)
        # Write each data row
        for row in rows:
            writer.writerow(row)

    print(f"Wrote {len(rows)} rows to {out_path}")


def main():
    print("Starting CSV export to ./csv_data ...")
    ensure_csv_dir()

    # Export books.csv
    export_table_to_csv(
        table_name="Books",
        column_list=["BookID", "title", "ean_isbn13", "upc_isbn10", "description", "publisher", "publish_date"],
        csv_filename="books.csv"
    )

    # Export authors.csv
    export_table_to_csv(
        table_name="Authors",
        column_list=["AuthorID", "FullName"],
        csv_filename="authors.csv"
    )

    # Export categories.csv
    export_table_to_csv(
        table_name="Categories",
        column_list=["CategoryID", "CategoryName"],
        csv_filename="categories.csv"
    )

    # Export bookauthors.csv
    export_table_to_csv(
        table_name="BookAuthors",
        column_list=["BookID", "AuthorID"],
        csv_filename="bookauthors.csv"
    )

    # Export bookcategories.csv
    export_table_to_csv(
        table_name="BookCategories",
        column_list=["BookID", "CategoryID"],
        csv_filename="bookcategories.csv"
    )

    print("All CSV exports complete.")


if __name__ == "__main__":
    main()