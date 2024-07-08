import random
import re
import sqlite3
import os
import threading
import time
from dotenv import load_dotenv
import json

load_dotenv()
import requests
from pydrive.auth import GoogleAuth
from pydrive.drive import GoogleDrive
from datetime import datetime

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
        username TEXT NOT NULL,
        content TEXT NOT NULL,
        user INTEGER NOT NULL,
        singbox_file TEXT
    );
    """

sql_create_users_table = """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        token TEXT NOT NULL,
        telegram_id TEXT NOT NULL
    );"""

c.execute(sql_create_clients_table)
c.execute(sql_create_users_table)
conn.commit()
conn.close()


def modify_singbox_json(data):
    # Обработка JSON
    for outbound in data.get("outbounds", []):
        if "cerberus" in outbound.get("tag", "").lower():
            if "tls" not in outbound:
                outbound["tls"] = {}
            outbound["tls"]["insecure"] = True

    if "route" in data:
        data["route"].pop("geoip", None)
        data["route"].pop("geosite", None)

        for rule in data["route"].get("rules", []):
            if "geoip" in rule and rule["geoip"] == "private":
                rule.update({
                    "ip_cidr": [
                        "10.0.0.0/8",
                        "172.16.0.0/12",
                        "192.168.0.0/16",
                        "100.64.0.0/10",
                        "127.0.0.0/8",
                        "169.254.0.0/16"
                    ],
                    "outbound": "direct"
                })
                rule.pop("geoip", None)
    if "dns" in data and "rules" in data["dns"]:
        data["dns"]["rules"] = [
            rule for rule in data["dns"]["rules"]
            if not (rule.get("geosite") == "private" and rule.get("server") == "dns_direct")
        ]

    return data


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


def write_singbox_to_file(dict_list, filename):
    with open(filename, 'w') as file:
        for d in dict_list:
            username = d[3]
            file_id = f"https://drive.usercontent.google.com/uc?authuser=0&export=download&id={d[6]}"
            file.write(f"{username} \n{file_id}\n\n")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)

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
    user_id = str(update.message.from_user.id)

    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (user_id,))
    user = cursor.fetchone()
    if not user:
        await update.message.reply_text(f"Please sign in to use")
        return
    try:
        id, token, telegram_id = user
        cursor.execute("SELECT * FROM clients WHERE user = ?", (id, ))
        client_names = cursor.fetchall()
        if client_names:
            await update.message.reply_text("Total Clients: " + str(len(client_names)))
        else:
            await update.message.reply_text("No clients found.")
    except sqlite3.Error as e:
        await update.message.reply_text(f"Error fetching client list: {e}")
    finally:
        conn.close()


def get_user(telegram_id):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
    user = cursor.fetchone()
    conn.close()
    return user


def save_or_replace_token(telegram_id, token):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
    user = cursor.fetchone()
    if user:
        cursor.execute("UPDATE users SET token=? WHERE telegram_id=?", (token, telegram_id))
    else:
        cursor.execute("INSERT INTO users (token, telegram_id) VALUES (?, ?);", (token, telegram_id))
    conn.commit()
    conn.close()


async def update_clients(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)

    conn = sqlite3.connect(DATABASE_FILE)
    try:
        user = get_user(user_id)
        if not user:
            await update.message.reply_text(f"Please sign in to use")
            return
        user_id, token, telegram_id = user

        cursor = conn.cursor()
        res = requests.get(DOMAIN + "/api/users", headers={"Authorization": "Bearer " + token})

        if res.status_code == 200:
            data = res.json()["users"]

            cursor.execute("SELECT * FROM clients WHERE user = ?", (user_id, ))
            client_names = cursor.fetchall()
            for client in client_names:
                id, name, file_id, username, content, user, singbox_file = client
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

                cursor.execute("SELECT * FROM clients WHERE username=? AND user=?", (username, user_id,))
                client_db = cursor.fetchone()
                if not client_db:
                    file1 = drive.CreateFile(
                        {'title': random.randint(100,
                                                 1000000000000000)})  # Create GoogleDriveFile instance with title 'Hello.txt'.
                    
                    # VLESS
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

                    # Sing-box
                    singbox_file_id = ""
                    singbox_url = client["subscription_url"] + "/sing-box"
                    if singbox_url:
                        res = requests.get(singbox_url)
                        if res.status_code == 200:
                            res = modify_singbox_json(res.json())
                            filename = str(random.randint(100, 1000000000000000))+".json"
                            with open(filename, 'w') as json_file:
                                json.dump(res, json_file)
                            singbox_file = drive.CreateFile()
                            singbox_file.SetContentFile(filename)
                            singbox_file.Upload()
                            if os.path.exists(filename):
                                os.remove(filename)
                            permission = singbox_file.InsertPermission({
                                'type': 'anyone',
                                'value': 'anyone',
                                'role': 'reader'})

                            singbox_file_id = extract_file_id(singbox_file['alternateLink'])

                    cursor.execute("INSERT OR REPLACE INTO clients (name, file_id, username, content, user, singbox_file) VALUES ("
                                   "?, ?, ?, ?, ?, ?)", (name, file_id, username, text, user_id, singbox_file_id))
                    conn.commit()
                else:
                    id, name, file_id, username, content, user, singbox_file_id = client_db

                    text = ""
                    for link in client["links"]:
                        link = link.split("#")
                        text += link[0] + "&allowInsecure=1#" + link[1] + "\n"

                    text = base64.b64encode(text.encode()).decode()

                    if content != text:
                        file = drive.CreateFile({'id': file_id})
                        file.SetContentString(text)
                        file.Upload()
                        
                        # Sing-box
                        singbox_url = client["subscription_url"] + "/sing-box"
                        singbox_file = None
                        if singbox_url:
                            res = requests.get(singbox_url)
                            if res.status_code == 200:
                                res = modify_singbox_json(res.json())
                                filename = str(random.randint(100, 1000000000000000))+".json"
                                with open(filename, 'w') as json_file:
                                    json.dump(res, json_file)
                                if singbox_file_id:
                                    singbox_file = drive.CreateFile({'id': singbox_file_id})
                                else:
                                    singbox_file = drive.CreateFile()
                                singbox_file.SetContentFile(filename)
                                singbox_file.Upload()
                                if os.path.exists(filename):
                                    os.remove(filename)

                        if singbox_file_id:
                            update_query = "UPDATE clients SET content = ? WHERE id = ?"
                            cursor.execute(update_query, (text, id))
                        else:
                            if singbox_file:
                                permission = singbox_file.InsertPermission({
                                'type': 'anyone',
                                'value': 'anyone',
                                'role': 'reader'})

                                singbox_file_id = extract_file_id(singbox_file['alternateLink'])
                                update_query = "UPDATE clients SET content = ?, singbox_file=? WHERE id = ?"

                                cursor.execute(update_query, (text, singbox_file_id, id))
                            else:
                                update_query = "UPDATE clients SET content = ? WHERE id = ?"
                                cursor.execute(update_query, (text, id))

                        conn.commit()

                        await update.message.reply_text(
                            "Client with username " + str(username) + " updated successfully!")

            await update.message.reply_text("Total Clients Number: " + str(len(data)))
        else:
            await update.message.reply_text("Error fetching users from given domain. Content: "+res.text)
    except sqlite3.Error as e:
        await update.message.reply_text(f"Error fetching client list: {e}")
    finally:
        conn.close()


def date_to_timestamp(date_str):
    try:
        # Parse the date string assuming "dd:mm:yyyy" format
        date_obj = datetime.strptime(date_str, "%d.%m.%Y")
        # Convert datetime object to Unix timestamp
        timestamp = int(date_obj.timestamp())
        return timestamp
    except ValueError:
        return None 

def gb_to_bytes(gb):
    bytes = gb * 1024 * 1024 * 1024
    return bytes

async def add_client(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)

    user = get_user(user_id)
    if not user:
        await update.message.reply_text(f"Please sign in to use")
        return

    id, token, telegram_id = user

    args = context.args
    if len(args) != 3:
        await update.message.reply_text("Usage: /add_client <username> <data limit> <expire date>")
        return
    
    username, data_limit, expire_date = args[0], int(args[1]), args[2]

    user = {
        "username": username,
        "proxies": {"vless": {}},
        "inbounds": {},
        "expire": date_to_timestamp(expire_date),
        "data_limit": gb_to_bytes(data_limit),
        "data_limit_reset_strategy": "no_reset", 
        "status": "active", 
    }

    res = requests.post(f"{DOMAIN}/api/user", json=user, headers={"Authorization": "Bearer " + token})

    if res.status_code == 200:
        await update.message.reply_text("Successfully added client")
    else:
        await update.message.reply_text(res.text)



async def sign_in(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)

    args = context.args
    if len(args) != 2:
        await update.message.reply_text("Usage: /sign_in <username> <password>")
        return
    username, password = args[0], args[1]

    res = requests.post(DOMAIN + '/api/admin/token', data={'username': username, 'password': password})
    data = res.json()

    if data.get("access_token"):
        save_or_replace_token(user_id, data["access_token"])
        await update.message.reply_text("Sign in successful")
    else:
        await update.message.reply_text("Sign in failed")


async def help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)

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
    user_id = str(update.message.from_user.id)

    user = get_user(user_id)
    if not user:
        await update.message.reply_text(f"Please sign in to use")
        return

    id, token, telegram_id = user

    conn = sqlite3.connect(DATABASE_FILE)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM clients WHERE user=?", (id, ))
        client_names = cursor.fetchall()
        document_path = str(telegram_id) + '.txt'  # Specify the path to your generated text file
        write_dict_to_file(client_names, document_path)
        with open(document_path, 'rb') as document:
            chat_id = update.message.chat_id
            await context.bot.send_document(chat_id, document)
    except sqlite3.Error as e:
        await update.message.reply_text(f"Error fetching client list: {e}")
    finally:
        conn.close()


async def get_urls_singbox(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)

    user = get_user(user_id)
    if not user:
        await update.message.reply_text(f"Please sign in to use")
        return

    id, token, telegram_id = user

    conn = sqlite3.connect(DATABASE_FILE)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM clients WHERE user=?", (id, ))
        client_names = cursor.fetchall()
        document_path = str(telegram_id) + '.txt'  # Specify the path to your generated text file
        write_singbox_to_file(client_names, document_path)
        with open(document_path, 'rb') as document:
            chat_id = update.message.chat_id
            await context.bot.send_document(chat_id, document)
    except sqlite3.Error as e:
        await update.message.reply_text(f"Error fetching client list: {e}")
    finally:
        conn.close()

def update_clients_scheduled():
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users")
    users = cursor.fetchall()

    for user in users:
        try:
            user_id, token, telegram_id = user

            res = requests.get(DOMAIN + "/api/users", headers={"Authorization": "Bearer " + token})

            if res.status_code == 200:
                data = res.json()["users"]

                cursor.execute("SELECT * FROM clients WHERE user = ?", (user_id,))
                client_names = cursor.fetchall()
                for client in client_names:
                    id, name, file_id, username, content, user, singbox_file = client
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

                    cursor.execute("SELECT * FROM clients WHERE username=? AND user=?", (username, user_id,))
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

                        cursor.execute("INSERT OR REPLACE INTO clients (name, file_id, username, content, user) VALUES ("
                                       "?, ?, ?, ?, ?)", (name, file_id, username, text, user_id))
                        conn.commit()
                    else:
                        id, name, file_id, username, content, user, singbox_file = client_db

                        text = ""
                        for link in client["links"]:
                            link = link.split("#")
                            text += link[0] + "&allowInsecure=1#" + link[1] + "\n"

                        text = base64.b64encode(text.encode()).decode()

                        if content != text:
                            file = drive.CreateFile({'id': file_id})
                            file.SetContentString(text)
                            file.Upload()

                            update_query = "UPDATE clients SET content = ? WHERE id = ?"
                            cursor.execute(update_query, (text, id))
                            conn.commit()

                            print(
                                "Client with username " + str(username) + " updated successfully!")

                print("Total Clients Number: " + str(len(data)))
            else:
                print("Error fetching users from given domain. Content: " + res.text)
        except sqlite3.Error as e:
            print(f"Error fetching client list: {e}")
        finally:
            conn.close()
    print("[UPDATED]")


def run_scheduled():
    while True:
        try:
            update_clients_scheduled()
            time.sleep(3600 * 3)
        except Exception as e:
            print("[ERROR] ", e)


if __name__ == '__main__':
    schedule_thread = threading.Thread(target=run_scheduled)
    # schedule_thread.start()

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    start_handler = CommandHandler('start', start)
    application.add_handler(start_handler)
    application.add_handler(CommandHandler("list_clients", list_clients))
    application.add_handler(CommandHandler("update_clients", update_clients))
    application.add_handler(CommandHandler("get_urls", get_urls))
    application.add_handler(CommandHandler("get_urls_singbox", get_urls_singbox))
    application.add_handler(CommandHandler("add_client", add_client))
    application.add_handler(CommandHandler("sign_in", sign_in))
    application.add_handler(CommandHandler("help", help))

    application.run_polling(timeout=250)

