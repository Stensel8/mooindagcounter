from flask import Flask, render_template, request, redirect, url_for, send_from_directory, jsonify
from datetime import datetime 
import time
import mariadb
import os
import requests
from dotenv import load_dotenv

# Global Variables
app = Flask(__name__)

load_dotenv("./.env")

# Help Functions
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

def save_counter(counter, message, timestamp, client_ip):
    conn = connect_db()
    cursor = conn.cursor()

    query = "INSERT INTO counts (id, message, timestamp, client_ip) VALUES (%s, %s, %s, %s)"
    cursor.execute(query, (counter, message, timestamp, client_ip))
    conn.commit()

    cursor.close()
    conn.close()

def get_counter(id):
    conn = connect_db()
    cursor = conn.cursor()

    query = "SELECT * FROM counts WHERE id = %s"
    cursor.execute(query, (id,))

    result = cursor.fetchone()
    cursor.close()
    conn.close()

    return result

def get_all_counters():
    conn = connect_db()
    cursor = conn.cursor()

    query = "SELECT id, message, timestamp FROM counts ORDER BY id DESC"
    cursor.execute(query)

    result = cursor.fetchall()
    cursor.close()
    conn.close()

    return result

def get_latest_counter():

    if (conn := connect_db()):
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
    else:
        return "Database not connected!"
    
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
    
# Route Functions
@app.route('/overview')
def overview():
    # Get all data
    data = get_all_counters()  

    # Only show overview if it contains data
    if data:
        return render_template('overview.html', data=data)
    else:
        return redirect(url_for('index'))

@app.route('/increment', methods=['POST'])
def increment():
    timestamp = datetime.now().replace(microsecond=0)

    # Get current counter and increment
    counter = get_latest_counter()
    counter += 1

    # Get message from form
    message = request.form.get("message").lower()

    # Check if message is unique
    if message_exists(message):
        return render_template('index.html', counter=counter, error_message=True)

    # Collect client ip
    if not (client_ip := request.headers.get('X-Forwarded-For')):
        client_ip = request.remote_addr

    # Get list with forbidden words
    with open("banned_words.txt") as f:
        banned_words = {word.strip().lower() for word in f}

    if any(word in message for word in banned_words):
        return render_template('index.html', counter=counter, banned_word=True)
    
    # Save new record to databse
    save_counter(counter, message, timestamp, client_ip)

    # Push message to discord
    push_to_discord(counter, message, timestamp)

    return redirect(url_for('index'))

@app.route('/robots.txt')
def robots_txt():
    return send_from_directory('static', 'robots.txt', mimetype='text/plain')

@app.route('/')
def index():
    counter = get_latest_counter()
    return render_template('index.html', counter=counter)

# API Methods
@app.route('/api/counts', methods=['GET'])
def api_counts():
    counters = get_all_counters()
    
    formatted_counters = [
        {
            "count": counter[0],
            "message": counter[1],
            "date": counter[2]
        }
        for counter in counters
    ]
    return jsonify(formatted_counters)

@app.route('/api/counts/<id>', methods=["GET"])
def api_counts_id(id):
    print(get_counter(1))
    return jsonify(get_counter(id))

@app.route('/api/delete/<id>', methods=["DELETE"])
def api_remove(id):
    conn = connect_db()
    cursor = conn.cursor()

    # Query to search record
    query = "DELETE FROM counts WHERE id = %s"
    cursor.execute(query, (id,))

    query = "ALTER TABLE counts AUTO_INCREMENT = 1"
    cursor.execute(query)

    conn.commit()

    cursor.close()
    conn.close()

    return jsonify({"message": f"Record with id {id} deleted"}), 200

# Easter egg
@app.route('/api/delete/all', methods=["GET"])
def meme():
    return render_template('meme.html')

if __name__ == '__main__':
    app.run(debug=True)
    
