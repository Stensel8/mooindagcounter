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

def message_exists(message):
    # Connect to database
    conn = connect_db()
    cursor = conn.cursor()

    # Check if message already exists
    query = "SELECT message FROM counts WHERE message = ? LIMIT 1"
    cursor.execute(query, (message,))

    result = cursor.fetchone()
    
    # Return if message exists
    return result is not None

def get_latest_counter():
    conn = connect_db()
    cursor = conn.cursor()

    query = "SELECT id FROM counts ORDER BY id DESC LIMIT 1"
    cursor.execute(query)

    result = cursor.fetchone()
    cursor.close()
    conn.close()

    if not result:
        return 0
    else:
        return result[0]

message = "war is peace, freedom is slavery, ignorance is strength"

print(message_exists(message))
print(get_latest_counter())