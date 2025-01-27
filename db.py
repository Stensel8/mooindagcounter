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

print(connect_db().server_name)
