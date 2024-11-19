from flask import Flask, render_template, request, redirect, url_for, send_from_directory
from datetime import datetime 
import time
import mariadb
import os
import requests
from dotenv import load_dotenv

app = Flask(__name__)

# Load environment variables
load_dotenv("./.env")

# Timestamp for last increment
last_increment_time = 0

def connect_db():
    conn = mariadb.connect(
        host="localhost",
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME")
    )
    return conn

# Laad de meest recente teller en bericht uit de database
def load_counter():
    conn = connect_db()
    cursor = conn.cursor()

    query = "SELECT id, message FROM counts ORDER BY id DESC LIMIT 1"
    cursor.execute(query)

    result = cursor.fetchone()
    cursor.close()
    conn.close()

    if not result:
        return (0, "Eerste count")
    else:
        return result

# Laad alle tellers en berichten uit de database
def load_all_counters():
    conn = connect_db()
    cursor = conn.cursor()

    query = "SELECT id, message, date FROM counts ORDER BY id DESC"
    cursor.execute(query)

    result = cursor.fetchall()
    cursor.close()
    conn.close()

    return result

# Sla nieuwe teller en bericht op in de database
def save_counter(counter, message, date):
    conn = connect_db()
    cursor = conn.cursor()

    query = "INSERT INTO counts (id, message, date) VALUES (%s, %s, %s)"
    cursor.execute(query, (counter, message, date))
    conn.commit()

    cursor.close()
    conn.close()

@app.route('/robots.txt')
def robots_txt():
    return send_from_directory('static', 'robots.txt', mimetype='text/plain')

@app.route('/')
def index():
    data = load_counter()
    counter = data[0]
    return render_template('index.html', counter=counter)

@app.route('/increment', methods=['POST'])
def increment():
    # # Cooldown
    # global last_increment_time
    # current_time = time.time()

    # if current_time - last_increment_time < 2:
    #     return redirect(url_for('index'))

    # last_increment_time = current_time

    # date
    date = datetime.now().date()

    # Get current counter and increment
    data = load_counter()
    counter = data[0]
    counter += 1

    # Get message from form
    message = request.form.get("message")

    # Save new record to databse
    save_counter(counter, message, date)

    # Set data to discordd webhook
    send_discord(counter, message)

    return redirect(url_for('index'))

# Route om alle counts en berichten te bekijken
@app.route('/overview')
def overview():
    # Get all data
    data = load_all_counters()  

    # Only show overview if it contains data
    if data:
        return render_template('overview.html', data=data)
    else:
        return redirect(url_for('index'))

def send_discord(counter, message):
    discord_webhook_url = os.getenv("DISCORD_WEBHOOK_URL")

    if discord_webhook_url:
        discord_data = {
            "content": f"Counter: {counter}\n{message.capitalize()}"
        }
        # Alternative for sending webhook data
    #     discord_data = {
    #     "embeds": [
    #         {
    #             "title": message,
    #             "description": f"**{counter}**",
    #             "fields": [
    #                 {
    #                     "name": "Message",
    #                     "value": message or "No message provided."
    #                 }
    #             ],
    #             "color": 3066993  # Optioneel: Groen kleurcode
    #         }
    #     ]
    # }
        requests.post(discord_webhook_url, json=discord_data)

if __name__ == '__main__':
    app.run(debug=True)
