def push_to_discord(counter, message, timestamp):
    discord_webhook_url = os.getenv("DISCORD_WEBHOOK_URL")

    if discord_webhook_url:
        discord_data = {
            "content": f"Counter: {counter}\n"
               f"Datum: {timestamp.strftime('%d-%m-%Y')}\n"
               f"Tijd: {timestamp.strftime('%H:%M')}\n"
               f"{message.capitalize()}"
        }
        requests.post(discord_webhook_url, json=discord_data)


load_dotenv("./.env")

def connect_db():
    try:
        return mariadb.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME")
        
        )
    except mariadb.Error as e:
        # Log database error
        print(f"Fout bij het verbinden met de database: {e}")
        return None