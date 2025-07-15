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
    try:
        return mariadb.connect(
        host="localhost",
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME")
    ) 
    except mariadb.Error as e:
        # Log database error
        return f"Fout bij het verbinden met de database: {e}"

def get_all_counters():
    conn = connect_db()
    cursor = conn.cursor(dictionary=True)

    query = "SELECT id, message, timestamp FROM counts ORDER BY id DESC"
    cursor.execute(query)

    result = cursor.fetchall()
    cursor.close()
    conn.close()

    return result

counters = get_all_counters()

time = datetime.now()
date = time.date()
onlytime = time.time().replace(microsecond=0)
print(date)
print(onlytime)