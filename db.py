import os
from dotenv import load_dotenv

# IM;ort environment variables from file
load_dotenv("./.env")  

# Verkrijg de omgevingsvariabelen
db_user = os.getenv("DB_USER")
db_password = os.getenv("DB_PASSWORD")
db_name = os.getenv("DB_NAME")

# Print de waarden om te controleren
print("DB_USER:", db_user)
print("DB_PASSWORD:", db_password)
print("DB_NAME:", db_name)
