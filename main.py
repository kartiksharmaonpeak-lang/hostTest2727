
import requests
import sqlite3
import time
import html
import logging
import json
from datetime import datetime, timedelta

# ================= CONFIG =================

BOT_TOKEN = "9273249263:AAHhEP0Iy0p7Y4CMnSxVJC34w15CHZbvvnw"
ADMIN_IDS = [8833850065]

CHANNEL_1 = "@auraxkartik"
CHANNEL_2 = "@botsbydeveloper"

UPI_ID = "Damien5@fam"
UPI_NAME = "Damien"

DB_NAME = "filebot.db"

REFERRAL_REWARD = 10
DAILY_REWARD = 5
MIN_TOPUP = 10

API = f"https://api.telegram.org/bot{BOT_TOKEN}/"

logging.basicConfig(level=logging.INFO)

# ================= DATABASE =================

db = sqlite3.connect(DB_NAME, check_same_thread=False)
db.row_factory = sqlite3.Row
db.execute("PRAGMA foreign_keys=ON")

db.executescript("""
CREATE TABLE IF NOT EXISTS users(
 user_id INTEGER PRIMARY KEY,
 balance REAL DEFAULT 0,
 referred_by INTEGER,
 joined TEXT
);

CREATE TABLE IF NOT EXISTS files(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 name TEXT,
 price REAL,
 file_id TEXT,
 created TEXT
);

CREATE TABLE IF NOT EXISTS purchases(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER,
 file_id INTEGER,
 price REAL,
 purchased TEXT,
 UNIQUE(user_id,file_id)
);

CREATE TABLE IF NOT EXISTS topups(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER,
 amount REAL,
 utr TEXT,
 status TEXT DEFAULT 'pending',
 created TEXT
);

CREATE TABLE IF NOT EXISTS transactions(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER,
 amount REAL,
 reason TEXT,
 created TEXT
);

CREATE TABLE IF NOT EXISTS bonuses(
 user_id INTEGER PRIMARY KEY,
 claimed TEXT
);
""")
db.commit()

# ================= API =================

def api(method, data=None):
    try:
        r = requests.post(
            API + method,
            data=data,
            timeout=40
        )
        return r.json()
    except Exception as e:
        logging.error(e)
        return {}

def send(chat, text, keyboard=None):
    data = {
        "chat_id": chat,
        "text": text,
        "parse_mode": "HTML"
    }
    if keyboard:
        data["reply_markup"] = json.dumps(keyboard)
    return api("sendMessage", data)

def edit(chat, msg, text, keyboard=None):
    data = {
        "chat_id": chat,
        "message_id": msg,
        "text": text,
        "parse_mode": "HTML"
    }
    if keyboard:
        data["reply_markup"] = json.dumps(keyboard)
    return api("editMessageText", data)

def answer(cid, text=""):
    api("answerCallbackQuery", {
        "callback_query_id": cid,
        "text": text
    })

def money(amount):
    return f"₹{float(amount):.2f}"

def is_admin(uid):
    return uid in ADMIN_IDS

# ================= KEYBOARD =================

def keyboard():
    return {
        "inline_keyboard": [
            [
                {"text": "📁 Buy Files", "callback_data": "files"},
                {"text": "💰 Balance", "callback_data": "balance"}
            ],
            [
                {"text": "👥 Refer & Earn", "callback_data": "refer"},
                {"text": "🎁 Daily Bonus", "callback_data": "bonus"}
            ],
            [
                {"text": "💳 Buy Credits", "callback_data": "topup"}
            ],
            [
                {"text": "ℹ️ Help", "callback_data": "help"}
            ]
        ]
    }

def home(chat, uid):
    kb = keyboard()
    if is_admin(uid):
        kb["inline_keyboard"].append([
            {"text": "⚙️ Admin Panel", "callback_data": "admin"}
        ])
    send(chat, "<b>WELCOME TO FILE STORE</b>\n\nSelect an option:", kb)

# ================= USERS =================

def get_user(uid):
    return db.execute(
        "SELECT * FROM users WHERE user_id=?",
        (uid,)
    ).fetchone()

def transaction(uid, amount, reason):
    db.execute("""
    INSERT INTO transactions(user_id,amount,reason,created)
    VALUES(?,?,?,?)
    """, (uid, amount, reason, datetime.now().isoformat()))

def change_balance(uid, amount, reason):
    user = get_user(uid)
    if not user or user["balance"] + amount < 0:
        return False

    db.execute(
        "UPDATE users SET balance=balance+? WHERE user_id=?",
        (amount, uid)
    )
    transaction(uid, amount, reason)
    db.commit()
    return True

def register(uid, ref=None):
    if get_user(uid):
        return

    if ref == uid or not get_user(ref) if ref else False:
        ref = None

    db.execute("""
    INSERT INTO users(user_id,balance,referred_by,joined)
    VALUES(?,?,?,?)
    """, (uid, 0, ref, datetime.now().isoformat()))
    db.commit()

    if ref:
        change_balance(ref, REFERRAL_REWARD, "Referral reward")
        send(ref, f"You earned {money(REFERRAL_REWARD)} from a referral!")

# ================= FORCE JOIN =================

def check_join(uid):
    for channel in [CHANNEL_1, CHANNEL_2]:
        result = api("getChatMember", {
            "chat_id": channel,
            "user_id": uid
        })

        if not result.get("ok"):
            return False

        status = result["result"]["status"]
        if status not in ["member", "administrator", "creator"]:
            return False

    return True

def join_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "Join Channel 1",
              "url": "https://t.me/" + CHANNEL_1.lstrip("@")}],
            [{"text": "Join Channel 2",
              "url": "https://t.me/" + CHANNEL_2.lstrip("@")}],
            [{"text": "I've Joined", "callback_data": "check_join"}]
        ]
    }

def require_join(uid, chat):
    if not check_join(uid):
        send(
            chat,
            "Please join both channels before using the bot.",
            join_keyboard()
        )
        return False
    return True

# ================= FILE STORE =================

def show_files(chat):
    files = db.execute(
        "SELECT * FROM files ORDER BY id DESC"
    ).fetchall()

    if not files:
        send(chat, "No files available.")
        return

    buttons = []

    for f in files:
        buttons.append([{
            "text": f"{f['name']} | {money(f['price'])}",
            "callback_data": f"buy_{f['id']}"
        }])

    buttons.append([{
        "text": "Back to Menu",
        "callback_data": "home"
    }])

    send(
        chat,
        "<b>AVAILABLE FILES</b>\n\nSelect a file:",
        {"inline_keyboard": buttons}
    )

def purchase(uid, chat, fid):
    try:
        db.execute("BEGIN IMMEDIATE")

        item = db.execute(
            "SELECT * FROM files WHERE id=?",
            (fid,)
        ).fetchone()

        user = get_user(uid)

        if not item or not user:
            db.rollback()
            send(chat, "File not found.")
            return

        old = db.execute("""
        SELECT id FROM purchases
        WHERE user_id=? AND file_id=?
        """, (uid, fid)).fetchone()

        if old:
            db.rollback()
            send(chat, "You already purchased this file.")
            return

        if user["balance"] < item["price"]:
            db.rollback()
            send(
                chat,
                "Insufficient balance!\n\n"
                f"Price: {money(item['price'])}\n"
                f"Balance: {money(user['balance'])}"
            )
            return

        db.execute(
            "UPDATE users SET balance=balance-? WHERE user_id=?",
            (item["price"], uid)
        )

        db.execute("""
        INSERT INTO purchases(user_id,file_id,price,purchased)
        VALUES(?,?,?,?)
        """, (
            uid, fid, item["price"], datetime.now().isoformat()
        ))

        transaction(uid, -item["price"], f"Purchased file #{fid}")
        db.commit()

    except Exception as e:
        db.rollback()
        logging.error(e)
        send(chat, "Purchase failed.")
        return

    result = api("sendDocument", {
        "chat_id": chat,
        "document": item["file_id"],
        "caption": (
            "Purchase successful!\n"
            f"File: {html.escape(item['name'])}\n"
            f"Paid: {money(item['price'])}"
        )
    })

    if not result.get("ok"):
        send(
            chat,
            "Payment recorded, but delivery failed. "
            "Contact an admin with your purchase ID."
        )
    else:
        send(
            chat,
            "Your file has been delivered!\n"
            f"Remaining balance: {money(get_user(uid)['balance'])}"
        )

# ================= REFERRAL =================

def referral(chat, uid):
    result = api("getMe")
    if not result.get("ok"):
        send(chat, "Could not generate referral link.")
        return

    username = result["result"]["username"]
    link = f"https://t.me/{username}?start={uid}"

    count = db.execute(
        "SELECT COUNT(*) FROM users WHERE referred_by=?",
        (uid,)
    ).fetchone()[0]

    send(
        chat,
        "<b>REFER & EARN</b>\n\n"
        f"Reward: {money(REFERRAL_REWARD)}\n"
        f"Referrals: {count}\n\n"
        f"Your link:\n<code>{link}</code>"
    )

# ================= DAILY BONUS =================

def bonus(chat, uid):
    now = datetime.now()

    row = db.execute(
        "SELECT claimed FROM bonuses WHERE user_id=?",
        (uid,)
    ).fetchone()

    if row:
        last = datetime.fromisoformat(row["claimed"])
        remaining = timedelta(hours=24) - (now - last)

        if remaining.total_seconds() > 0:
            hours = int(remaining.total_seconds() // 3600)
            minutes = int((remaining.total_seconds() % 3600) // 60)
            send(chat, f"Already claimed! Come back in {hours}h {minutes}m.")
            return

    db.execute("""
    INSERT INTO bonuses(user_id,claimed)
    VALUES(?,?)
    ON CONFLICT(user_id)
    DO UPDATE SET claimed=excluded.claimed
    """, (uid, now.isoformat()))

    db.commit()
    change_balance(uid, DAILY_REWARD, "Daily bonus")
    send(chat, f"Bonus claimed! You received {money(DAILY_REWARD)}.")

# ================= TOPUP =================

states = {}
uploads = {}

def topup(chat, uid):
    states[uid] = {"step": "amount"}

    send(
        chat,
        "<b>BUY CREDITS</b>\n\n"
        f"UPI ID: <code>{html.escape(UPI_ID)}</code>\n"
        f"Payee: {html.escape(UPI_NAME)}\n"
        f"Minimum: {money(MIN_TOPUP)}\n\n"
        "Enter your payment amount."
    )

def process_state(message, uid, chat):
    state = states.get(uid)
    if not state:
        return False

    text = message.get("text", "").strip()

    if state["step"] == "amount":
        try:
            amount = float(text)
            if not MIN_TOPUP <= amount <= 100000:
                raise ValueError()
        except ValueError:
            send(chat, "Enter a valid amount.")
            return True

        state["amount"] = amount
        state["step"] = "utr"

        send(
            chat,
            f"Amount: {money(amount)}\n\n"
            "Complete your payment and enter your UTR/reference number."
        )
        return True

    if state["step"] == "utr":
        if not 6 <= len(text) <= 50:
            send(chat, "Enter a valid reference number.")
            return True

        db.execute("""
        INSERT INTO topups(user_id,amount,utr,created)
        VALUES(?,?,?,?)
        """, (uid, state["amount"], text, datetime.now().isoformat()))

        db.commit()

        rid = db.execute(
            "SELECT last_insert_rowid()"
        ).fetchone()[0]

        amount = state["amount"]
        del states[uid]

        send(
            chat,
            f"Request submitted!\n"
            f"Request ID: #{rid}\n"
            f"Amount: {money(amount)}\n"
            "Awaiting admin verification."
        )

        for admin in ADMIN_IDS:
            send(
                admin,
                f"<b>PAYMENT REQUEST #{rid}</b>\n\n"
                f"User: <code>{uid}</code>\n"
                f"Amount: {money(amount)}\n"
                f"UTR: <code>{html.escape(text)}</code>\n\n"
                f"/approve {rid}\n/reject {rid}"
            )

        return True

    return False

# ================= ADMIN =================

def admin_panel(chat):
    send(
        chat,
        "<b>ADMIN PANEL</b>",
        {
            "inline_keyboard": [
                [
                    {"text": "Upload File", "callback_data": "upload"},
                    {"text": "Manage Files", "callback_data": "manage"}
                ],
                [
                    {"text": "Pending Payments", "callback_data": "pending"},
                    {"text": "Statistics", "callback_data": "stats"}
                ]
            ]
        }
    )

def stats(chat):
    users = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    files = db.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    purchases = db.execute("SELECT COUNT(*) FROM purchases").fetchone()[0]
    revenue = db.execute(
        "SELECT COALESCE(SUM(price),0) FROM purchases"
    ).fetchone()[0]

    send(
        chat,
        "<b>BOT STATISTICS</b>\n\n"
        f"Users: {users}\n"
        f"Files: {files}\n"
        f"Purchases: {purchases}\n"
        f"Sales: {money(revenue)}"
    )

def manage_files(chat):
    files = db.execute(
        "SELECT * FROM files ORDER BY id DESC"
    ).fetchall()

    if not files:
        send(chat, "No files found.")
        return

    for f in files:
        send(
            chat,
            f"<b>File #{f['id']}</b>\n"
            f"Name: {html.escape(f['name'])}\n"
            f"Price: {money(f['price'])}\n"
            f"/deletefile {f['id']}"
        )

def pending(chat):
    rows = db.execute(
        "SELECT * FROM topups WHERE status='pending'"
    ).fetchall()

    if not rows:
        send(chat, "No pending payments.")
        return

    for r in rows:
        send(
            chat,
            f"<b>REQUEST #{r['id']}</b>\n"
            f"User: {r['user_id']}\n"
            f"Amount: {money(r['amount'])}\n"
            f"UTR: <code>{html.escape(r['utr'])}</code>\n\n"
            f"/approve {r['id']}\n/reject {r['id']}"
        )

def start_upload(chat, uid):
    uploads[uid] = {"step": "details"}
    send(
        chat,
        "Send file details in this format:\n\n"
        "<code>File Name | Price</code>\n\n"
        "Example: Premium Pack | 50"
    )

# ================= ADMIN COMMANDS =================

def admin_command(message, uid, chat):
    if not is_admin(uid):
        return

    parts = message.get("text", "").split()
    command = parts[0]

    if command in ["/approve", "/reject"]:
        if len(parts) != 2:
            send(chat, f"Usage: {command} REQUEST_ID")
            return

        try:
            rid = int(parts[1])
        except ValueError:
            send(chat, "Invalid request ID.")
            return

        try:
            db.execute("BEGIN IMMEDIATE")

            row = db.execute(
                "SELECT * FROM topups WHERE id=? AND status='pending'",
                (rid,)
            ).fetchone()

            if not row:
                db.rollback()
                send(chat, "Request not found or already processed.")
                return

            if command == "/approve":
                db.execute(
                    "UPDATE users SET balance=balance+? WHERE user_id=?",
                    (row["amount"], row["user_id"])
                )
                transaction(
                    row["user_id"], row["amount"], f"UPI topup #{rid}"
                )
                status = "approved"
            else:
                status = "rejected"

            db.execute(
                "UPDATE topups SET status=? WHERE id=?",
                (status, rid)
            )
            db.commit()

            send(chat, f"Request #{rid} {status}.")

            if status == "approved":
                send(
                    row["user_id"],
                    f"Payment approved! Added {money(row['amount'])}."
                )
            else:
                send(row["user_id"], "Your payment request was rejected.")

        except Exception as e:
            db.rollback()
            logging.error(e)
            send(chat, "Operation failed.")

    elif command in ["/credit", "/debit"]:
        if len(parts) != 3:
            send(chat, f"Usage: {command} USER_ID AMOUNT")
            return

        try:
            target = int(parts[1])
            amount = float(parts[2])
            if not 0 < amount <= 100000:
                raise ValueError()
        except ValueError:
            send(chat, "Invalid user ID or amount.")
            return

        if command == "/debit":
            amount = -amount

        if change_balance(target, amount, "Admin adjustment"):
            send(chat, "Balance updated.")
            send(target, f"Your balance was adjusted by {money(amount)}.")
        else:
            send(chat, "User not found or insufficient balance.")

    elif command == "/deletefile":
        if len(parts) != 2:
            send(chat, "Usage: /deletefile FILE_ID")
            return

        try:
            fid = int(parts[1])
        except ValueError:
            send(chat, "Invalid file ID.")
            return

        result = db.execute(
            "DELETE FROM files WHERE id=?",
            (fid,)
        )
        db.commit()

        send(chat, "File deleted." if result.rowcount else "File not found.")

# ================= MESSAGES =================

def handle_message(message):
    user = message.get("from", {})
    uid = user.get("id")
    chat = message.get("chat", {}).get("id")

    if not uid or not chat:
        return

    if message.get("chat", {}).get("type") != "private":
        return

    text = message.get("text", "")

    if text.startswith("/start"):
        args = text.split(maxsplit=1)
        ref = None

        if len(args) == 2:
            try:
                ref = int(args[1])
            except ValueError:
                pass

        register(uid, ref)

        if require_join(uid, chat):
            home(chat, uid)
        return

    if not get_user(uid):
        send(chat, "Send /start first.")
        return

    if not require_join(uid, chat):
        return

    if text == "/cancel":
        states.pop(uid, None)
        uploads.pop(uid, None)
        send(chat, "Operation cancelled.")
        return

    if text.startswith((
        "/approve", "/reject", "/credit",
        "/debit", "/deletefile"
    )):
        admin_command(message, uid, chat)
        return

    # Admin upload
    if is_admin(uid) and uid in uploads:
        state = uploads[uid]

        if state["step"] == "details":
            try:
                name, price = text.rsplit("|", 1)
                name = name.strip()
                price = float(price.strip())

                if not name or len(name) > 100 or not 0 <= price <= 100000:
                    raise ValueError()

                state["name"] = name
                state["price"] = price
                state["step"] = "document"

                send(chat, "Now send the document.")
            except ValueError:
                send(chat, "Invalid format. Use File Name | Price.")
            return

        if state["step"] == "document":
            doc = message.get("document")

            if not doc:
                send(chat, "Please send a document.")
                return

            db.execute("""
            INSERT INTO files(name,price,file_id,created)
            VALUES(?,?,?,?)
            """, (
                state["name"],
                state["price"],
                doc["file_id"],
                datetime.now().isoformat()
            ))
            db.commit()

            del uploads[uid]
            send(chat, "File uploaded successfully!")
            return

    if process_state(message, uid, chat):
        return

    if text == "/admin":
        if is_admin(uid):
            admin_panel(chat)
        else:
            send(chat, "Access denied.")

    elif text == "/balance":
        send(chat, f"Your balance: {money(get_user(uid)['balance'])}")

    elif text == "/files":
        show_files(chat)
