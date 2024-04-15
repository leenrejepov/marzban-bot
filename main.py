import random
import re
import sqlite3
import os
import threading
import time
from dotenv import load_dotenv

load_dotenv()
import requests
from pydrive.auth import GoogleAuth
from pydrive.drive import GoogleDrive

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler
import base64

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
BOT_TOKEN = os.getenv('BOT_TOKEN')
DOMAIN = os.getenv("DOMAIN")
DATABASE_FILE = "db.db"

gauth = GoogleAuth()
gauth.LocalWebserverAuth()

drive = GoogleDrive(gauth)
conn = sqlite3.connect(DATABASE_FILE)
c = conn.cursor()

sql_create_clients_table = """
    CREATE TABLE IF NOT EXISTS clients (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        file_id TEXT NOT NULL,
        username TEXT NOT NULL UNIQUE
    );
    """

c.execute(sql_create_clients_table)
conn.commit()
conn.close()


def extract_file_id(url):
    pattern = r'/file/d/([a-zA-Z0-9_-]+)/'
    match = re.search(pattern, url)
    if match:
        return match.group(1)
    else:
        return None


def write_dict_to_file(dict_list, filename):
    with open(filename, 'w') as file:
        for d in dict_list:
            username = d[3]
            file_id = f"https://drive.usercontent.google.com/uc?authuser=0&export=download&id={d[2]}"
            file.write(f"{username} \n{file_id}\n\n")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """
    This is help message.
    List of the available commands:
    /start - To start e bot
    /list_clients - To list all the clients
    /update_clients - To update all the clients
    /get_urls - To get all the urls
    /help - This Help message
        """
    await update.message.reply_text(text)


async def list_clients(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DATABASE_FILE)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM clients")
        client_names = cursor.fetchall()
        if client_names:
            await update.message.reply_text("Total Clients: " + str(len(client_names)))
        else:
            await update.message.reply_text("No clients found.")
    except sqlite3.Error as e:
        await update.message.reply_text(f"Error fetching client list: {e}")
    finally:
        conn.close()


async def show_client_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    client_id = int(query.data.split("_")[1])

    conn = sqlite3.connect(DATABASE_FILE)

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM clients WHERE id=?", (client_id,))
        client = cursor.fetchone()
        # Fetch client details from the database based on the client_id
        # You can customize this part to retrieve other client information
        client_info = (f"Client ID: {client[0]}\nName: {client[1]}\nDrive Url: https://drive.usercontent.google.com/uc?authuser=0&export"
                       f"=download&id={client[2]}\n Marzban username: {client[3]}")
        buttons = [
            InlineKeyboardButton("Delete", callback_data=f"delete_{client_id}"),
        ]
        reply_markup = InlineKeyboardMarkup([buttons])
        await query.edit_message_text(text=client_info, reply_markup=reply_markup)
    except sqlite3.Error as e:
        await update.message.reply_text(f"Error fetching client list: {e}")
    finally:
        conn.close()


async def handle_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    action, client_id = query.data.split("_")
    if action == "delete":
        conn = sqlite3.connect(DATABASE_FILE)
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM clients WHERE id = ?", (client_id,))
            conn.commit()
        except sqlite3.Error as e:
            print(f"Error deleting client: {e}")
        finally:
            conn.close()
        # Delete client from the database based on client_id
        # Implement your deletion logic here
        await query.answer(f"Client with ID {client_id} deleted successfully.")
    else:
        await query.answer(f"Error")

def get_token():
    with open("token.txt", "r") as f:
        token = f.read()
    return token

async def update_clients(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DATABASE_FILE)
    try:
        cursor = conn.cursor()
        res = requests.get(DOMAIN + "/api/users", headers={"Authorization": "Bearer " + get_token()})

        if res.status_code == 200:
            data = res.json()["users"]

            cursor.execute("SELECT * FROM clients")
            client_names = cursor.fetchall()
            for client in client_names:
                id, name, file_id, username = client
                found = False
                for client_item in data:
                    if client_item["username"] == username:
                        found = True
                        break
                if not found:
                    cursor.execute("DELETE FROM clients WHERE id = ?", (id,))
                    conn.commit()

            for client in data:
                name = str(random.randint(100, 1000000000000000))
                username = client["username"]

                cursor.execute("SELECT * FROM clients WHERE username=?", (username,))
                client_db = cursor.fetchone()
                if not client_db:
                    file1 = drive.CreateFile(
                        {'title': random.randint(100,
                                                 1000000000000000)})  # Create GoogleDriveFile instance with title 'Hello.txt'.
                    
                    text = ""
                    for link in client["links"]:
                        link = link.split("#")                        
                        text += link[0] + "&allowInsecure=1#" + link[1] + "\n"

                    text = base64.b64encode(text.encode()).decode()
                    file1.SetContentString(text)  # Set content of the file from given string.
                    file1.Upload()

                    permission = file1.InsertPermission({
                        'type': 'anyone',
                        'value': 'anyone',
                        'role': 'reader'})

                    file_id = extract_file_id(file1['alternateLink'])

                    cursor.execute("INSERT OR REPLACE INTO clients (name, file_id, username) VALUES (?, ?, "
                                   "?)", (name, file_id, username))
                    conn.commit()
                else:
                    id, name, file_id,  username = client_db

                    file = drive.CreateFile({'id': file_id})
                    text = ""
                    for link in client["links"]:
                        link = link.split("#")                        
                        text += link[0] + "&allowInsecure=1#" + link[1] + "\n"

                    text = base64.b64encode(text.encode()).decode()

                    if file.GetContentString() != text:
                        
                        file.SetContentString(text)
                        file.Upload()
                        await update.message.reply_text(
                            "Client with username " + str(username) + " updated successfully!")

            await update.message.reply_text("Total Clients Number: " + str(len(data)))
    except sqlite3.Error as e:
        await update.message.reply_text(f"Error fetching client list: {e}")
    finally:
        conn.close()

async def sign_in(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("Usage: /sign_in <username> <password>")
        return
    username, password = args[0], args[1]

    res = requests.post(DOMAIN + '/api/admin/token', data={'username': username, 'password': password})
    data = res.json()

    if data.get("access_token"):
        with open('token.txt', 'w') as f:
            f.write(data["access_token"])
        await update.message.reply_text("Sign in successful")
    else:
        await update.message.reply_text("Sign in failed")


async def help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """
This is help message.
List of the available commands:
/start - To start the bot
/list_clients - To list all the clients
/update_clients - To update all the clients from marzban
/get_urls - To get all the urls
/help - This Help message
    """
    await update.message.reply_text(text)


async def get_urls(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DATABASE_FILE)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM clients")
        client_names = cursor.fetchall()
        write_dict_to_file(client_names, 'urls-2024.txt')
        document_path = 'urls-2024.txt'  # Specify the path to your generated text file
        with open(document_path, 'rb') as document:
            chat_id = update.message.chat_id
            await context.bot.send_document(chat_id, document)
    except sqlite3.Error as e:
        await update.message.reply_text(f"Error fetching client list: {e}")
    finally:
        conn.close()


def update_clients_scheduled():
    conn = sqlite3.connect(DATABASE_FILE)
    try:
        cursor = conn.cursor()
        res = requests.get(DOMAIN + "/api/users", headers={"Authorization": "Bearer " + get_token()})

        if res.status_code == 200:
            data = res.json()["users"]

            cursor.execute("SELECT * FROM clients")
            client_names = cursor.fetchall()
            for client in client_names:
                id, name, file_id, username = client
                found = False
                for client_item in data:
                    if client_item["username"] == username:
                        found = True
                        break
                if not found:
                    cursor.execute("DELETE FROM clients WHERE id = ?", (id,))
                    conn.commit()

            for client in data:
                name = str(random.randint(100, 1000000000000000))
                username = client["username"]

                cursor.execute("SELECT * FROM clients WHERE username=?", (username,))
                client_db = cursor.fetchone()
                if not client_db:
                    file1 = drive.CreateFile(
                        {'title': random.randint(100,
                                                 1000000000000000)})  # Create GoogleDriveFile instance with title 'Hello.txt'.

                    text = ""
                    for link in client["links"]:
                        link = link.split("#")
                        text += link[0] + "&allowInsecure=1#" + link[1] + "\n"

                    text = base64.b64encode(text.encode()).decode()
                    file1.SetContentString(text)  # Set content of the file from given string.
                    file1.Upload()

                    permission = file1.InsertPermission({
                        'type': 'anyone',
                        'value': 'anyone',
                        'role': 'reader'})

                    file_id = extract_file_id(file1['alternateLink'])

                    cursor.execute("INSERT OR REPLACE INTO clients (name, file_id, username) VALUES (?, ?, "
                                   "?)", (name, file_id, username))
                    conn.commit()
                else:
                    id, name, file_id, username = client_db

                    file = drive.CreateFile({'id': file_id})
                    text = ""
                    for link in client["links"]:
                        link = link.split("#")
                        text += link[0] + "&allowInsecure=1#" + link[1] + "\n"

                    text = base64.b64encode(text.encode()).decode()

                    if file.GetContentString() != text:
                        file.SetContentString(text)
                        file.Upload()

            print("[UPDATED]")
    except sqlite3.Error as e:
        print("[ERROR]")
    finally:
        conn.close()


def run_scheduled():
    while True:
        try:
            update_clients_scheduled()
            time.sleep(3600 * 3)
        except Exception as e:
            print("[ERROR] ", e)


if __name__ == '__main__':
    schedule_thread = threading.Thread(target=run_scheduled)
    schedule_thread.start()

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    start_handler = CommandHandler('start', start)
    application.add_handler(start_handler)
    application.add_handler(CommandHandler("list_clients", list_clients))
    application.add_handler(CommandHandler("update_clients", update_clients))
    application.add_handler(CommandHandler("get_urls", get_urls))
    application.add_handler(CommandHandler("sign_in", sign_in))
    application.add_handler(CommandHandler("help", help))
    application.add_handler(CallbackQueryHandler(show_client_info, pattern=r"^view_\d+$"))
    application.add_handler(CallbackQueryHandler(handle_button_click, pattern=r"^(edit|delete)_\d+$"))

    application.run_polling(timeout=250)

