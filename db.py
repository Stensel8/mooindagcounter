import os
from dotenv import load_dotenv
import mariadb

# IM;ort environment variables from file
load_dotenv("./.env")  

# Verkrijg de omgevingsvariabelen
db_user = os.getenv("DB_USER")
db_password = os.getenv("DB_PASSWORD")
db_name = os.getenv("DB_NAME")

def connect_db():
    conn = mariadb.connect(
        host="localhost",
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME")
    )
    return conn

def get_counter(id):
    conn = connect_db()
    cursor = conn.cursor()

    query = "SELECT * FROM counts WHERE id = ?"
    cursor.execute(query, (id,))

    result = cursor.fetchone()
    cursor.close()
    conn.close()

    return result


