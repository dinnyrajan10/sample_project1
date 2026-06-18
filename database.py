import sqlite3

conn = sqlite3.connect("products.db")

cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS products(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    price INTEGER NOT NULL,
    category TEXT NOT NULL,
    image TEXT NOT NULL,
    status TEXT DEFAULT 'Available',
    description TEXT
)
""")

conn.commit()
conn.close()

print("Database created")