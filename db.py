import os
from dotenv import load_dotenv
import mariadb
from datetime import datetime 

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

def get_date():
    timestamp = datetime.now().replace(microsecond=0)

    return timestamp


def is_message_unique(message):
    # Connect to database
    conn = connect_db()
    cursor = conn.cursor()

    # Check if message already exists
    query = "SELECT message FROM counts WHERE message = ?"
    cursor.execute(query, (message,))

    rows = cursor.fetchall()
    
    # Return if message exists
    return not len(rows) > 0

message = "war is peace, freedom is slaveryy, ignorance is strength"
print(is_message_unique(message))