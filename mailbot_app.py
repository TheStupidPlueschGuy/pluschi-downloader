"""
Plüschi Mail-Bot System
=======================
Separates Flask-Backend auf Port 5001.
Wird vom Plüsch Downloader (Port 5000) angesprochen.

Setup:
  pip install flask flask-mail anthropic python-dotenv

Dann .env ausfüllen und starten:
  python mailbot_app.py
"""

import os
import random
import string
import time
from datetime import datetime
from flask import Flask, request, jsonify
from flask_mail import Mail, Message
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)  # Erlaubt Anfragen vom Downloader (Port 5000)

# ─── Mail-Konfiguration ───────────────────────────────────────────────────────
app.config.update(
    MAIL_SERVER="smtp.gmail.com",
    MAIL_PORT=587,
    MAIL_USE_TLS=True,
    MAIL_USERNAME=os.getenv("NOREPLY_GMAIL_USER"),
    MAIL_PASSWORD=os.getenv("NOREPLY_GMAIL_APP_PASSWORD"),
    MAIL_DEFAULT_SENDER=(
        "Plüschi Support",
        os.getenv("NOREPLY_GMAIL_USER", "noreply@example.com"),
    ),
)
mail = Mail(app)

ADMIN_EMAIL = os.getenv("SUPPORT_GMAIL_USER", "pluesch.support@gmail.com")

# ─── In-Memory Stores ─────────────────────────────────────────────────────────
otp_store   = {}   # email -> {code, expires, attempts, count, first_sent}
reset_store = {}   # token -> {email, expires, code}
ticket_store = []  # Support-Tickets

# ─── Helpers ──────────────────────────────────────────────────────────────────
def gen_otp(n=6):
    return "".join(random.choices(string.digits, k=n))

def gen_token(n=32):
    return "".join(random.choices(string.ascii_letters + string.digits, k=n))

def send_mail(to, subject, html):
    try:
        msg = Message(subject=subject, recipients=[to], html=html)
        mail.send(msg)
        return True
    except Exception as e:
        app.logger.error(f"Mail-Fehler: {e}")
        return False

def mail_template(title, body_html, footer=""):
    return f"""<!DOCTYPE html>
<html lang="de">
<head><meta charset="UTF-8"><style>
body{{font-family:'Segoe UI',Arial,sans-serif;background:#0a0a0f;margin:0;padding:20px;}}
.card{{max-width:520px;margin:0 auto;background:#1a1a2e;border-radius:16px;border:1px solid #2d2d4e;overflow:hidden;}}
.header{{background:linear-gradient(135deg,#7c3aed,#db2777);padding:28px 32px;text-align:center;}}
.header h1{{color:#fff;margin:0;font-size:22px;font-weight:700;}}
.header p{{color:rgba(255,255,255,0.7);margin:6px 0 0;font-size:13px;}}
.body{{padding:32px;color:#c8c8e0;line-height:1.65;}}
.body h2{{color:#e8e8ff;font-size:17px;margin:0 0 12px;}}
.code-box{{background:#0a0a0f;border:2px solid #7c3aed;border-radius:10px;text-align:center;padding:18px;margin:20px 0;}}
.code{{font-size:38px;font-weight:800;letter-spacing:10px;color:#a78bfa;font-family:'Courier New',monospace;}}
.warning{{background:#2d1515;border-left:3px solid #db2777;padding:10px 14px;border-radius:4px;font-size:13px;color:#f0a0a0;}}
.footer{{padding:16px 32px;background:#13132a;text-align:center;font-size:12px;color:#555575;}}
</style></head>
<body><div class="card">
  <div class="header"><h1>🦊 Plüschi System</h1><p>{title}</p></div>
  <div class="body">{body_html}</div>
  <div class="footer">{footer or "Plüschi App · Automatische Nachricht · Bitte nicht antworten"}</div>
</div></body></html>"""

GITHUB_REPO = "TheStupidPlueschGuy/PlueschDownloader"

# ─── GitHub Userdb Konfiguration ─────────────────────────────────────────────
GITHUB_TOKEN    = os.getenv("GITHUB_TOKEN")           # Personal Access Token
USERDB_REPO     = os.getenv("USERDB_REPO", "TheStupidPlueschGuy/plueschi-userdb")
USERDB_BRANCH   = os.getenv("USERDB_BRANCH", "main")
GITHUB_API      = "https://api.github.com"

import hashlib, hmac, base64, json as _json, urllib.request, urllib.error

def _gh_headers():
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
        "User-Agent": "PlueschDownloader-Mailbot",
    }

def _gh_get(path):
    """GET from GitHub API. Returns (data, sha) or (None, None)."""
    if not GITHUB_TOKEN:
        return None, None
    try:
        req = urllib.request.Request(
            f"{GITHUB_API}/repos/{USERDB_REPO}/contents/{path}?ref={USERDB_BRANCH}",
            headers=_gh_headers()
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            data = _json.loads(r.read().decode())
        content = base64.b64decode(data["content"]).decode("utf-8")
        return _json.loads(content), data["sha"]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, None
        raise
    except Exception:
        return None, None

def _gh_put(path, content_dict, sha=None, message="update user"):
    """PUT (create/update) file in GitHub repo."""
    if not GITHUB_TOKEN:
        return False
    try:
        body = {
            "message": message,
            "content": base64.b64encode(_json.dumps(content_dict, ensure_ascii=False, indent=2).encode()).decode(),
            "branch": USERDB_BRANCH,
        }
        if sha:
            body["sha"] = sha
        req = urllib.request.Request(
            f"{GITHUB_API}/repos/{USERDB_REPO}/contents/{path}",
            data=_json.dumps(body).encode(),
            headers=_gh_headers(),
            method="PUT"
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.status in (200, 201)
    except Exception as e:
        app.logger.error(f"GitHub PUT error: {e}")
        return False

def _gh_delete(path, sha, message="delete user"):
    """DELETE file from GitHub repo."""
    if not GITHUB_TOKEN:
        return False
    try:
        body = {"message": message, "sha": sha, "branch": USERDB_BRANCH}
        req = urllib.request.Request(
            f"{GITHUB_API}/repos/{USERDB_REPO}/contents/{path}",
            data=_json.dumps(body).encode(),
            headers=_gh_headers(),
            method="DELETE"
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.status == 200
    except Exception as e:
        app.logger.error(f"GitHub DELETE error: {e}")
        return False

def _get_index():
    """Holt _index.json: {username: email, ...}"""
    data, sha = _gh_get("users/_index.json")
    return (data or {}), sha

def _save_index(index_data, sha):
    return _gh_put("users/_index.json", index_data, sha, "update index")

def _get_user(username):
    """Holt users/{username}.json"""
    return _gh_get(f"users/{username}.json")

def _save_user(username, user_data, sha=None):
    return _gh_put(f"users/{username}.json", user_data, sha, f"update user {username}")

def _delete_user_file(username, sha):
    return _gh_delete(f"users/{username}.json", sha, f"delete user {username}")

def _hash_password(password):
    """SHA-256 Hash des Passworts."""
    return hashlib.sha256(password.encode()).hexdigest()

def _verify_password(password, hashed):
    return hashlib.sha256(password.encode()).hexdigest() == hashed

def _clean_sessions(sessions, max_devices):
    """Entfernt abgelaufene Sessions (>30 Tage inaktiv)."""
    cutoff = time.time() - (30 * 24 * 3600)
    active = [s for s in sessions if s.get("last_active", 0) > cutoff]
    return active[:max_devices]

def _get_max_devices(plan):
    return 6 if plan == "premium" else 2



# ─── Regel-basierter Support-Bot ─────────────────────────────────────────────
SUPPORT_RULES = [
    (["geht nicht","funktioniert nicht","klappt nicht","startet nicht","lädt nicht"],
     "🔧 Download funktioniert nicht?\n1. Ist die URL vollständig kopiert?\n2. Unterstützen wir diese Seite? (Sidebar → Unterstützte Seiten)\n3. Stabile Internetverbindung vorhanden?\n4. App neu starten und erneut versuchen.\nFalls es weiterhin nicht klappt, sende uns die genaue Fehlermeldung aus der App."),

    (["hängt","friert","reagiert nicht"],
     "⏳ App hängt?\nSchließe die App komplett (Task-Manager) und starte sie neu.\nVersuche eine niedrigere Qualitätsstufe (720p statt Beste).\nPrüfe ob dein Speicherort noch freien Platz hat."),

    (["langsam","zu langsam","dauert lang"],
     "⚡ Download zu langsam?\nDie Geschwindigkeit hängt von deiner Verbindung und dem Plattform-Server ab.\n→ Niedrigere Qualität wählen\n→ Stoßzeiten vermeiden (abends)\n→ Andere Bandbreiten-intensive Programme schließen"),

    (["format","mp4","mp3"],
     "🎵 Format-Problem?\nPlüsch Downloader unterstützt MP4 (Video) und MP3 (Audio).\n→ Format oben in der App auswählen bevor du downloadest\n→ Nicht alle Seiten unterstützen alle Formate"),

    (["qualität","auflösung","schlecht","pixelig"],
     "🔷 Qualitätsproblem?\n→ Unter 'Qualität' eine höhere Stufe wählen (Beste / 1080p)\n→ Manche Videos sind nur in niedrigerer Qualität verfügbar — das liegt an der Quelle"),

    (["wo gespeichert","ordner","speicherort","finden"],
     "📂 Wo ist mein Download?\n→ Speicherort steht in der App unter 'Speicherort'\n→ Standard: Windows Downloads-Ordner\n→ Einstellungen → Ordner: separate Pfade für MP3 und MP4 möglich\n→ Nach Download: 'Ordner öffnen' Button klicken"),

    (["youtube","yt"],
     "▶️ YouTube-Problem?\n→ Vollständige URL kopieren (mit https://)\n→ Private/altersbeschränkte Videos benötigen Cookies (Erweiterte Optionen)\n→ Bei anhaltenden Problemen: App-Update prüfen"),

    (["tiktok","instagram","private","cookie","privat"],
     "🍪 Private / Login-geschützte Videos?\n1. Browser-Extension 'Get cookies.txt LOCALLY' installieren\n2. Auf der Seite einloggen\n3. cookies.txt exportieren\n4. Inhalt in App → Erweiterte Optionen → Cookies einfügen"),

    (["passwort vergessen","passwort reset","einloggen","login","anmelden"],
     "🔑 Passwort-Problem?\n→ 'Passwort vergessen?' auf der Login-Seite klicken\n→ Hinterlegte E-Mail eingeben → 6-stelliger Reset-Code kommt per Mail\n→ Ohne hinterlegte E-Mail: Konto neu erstellen (Daten gehen verloren)"),

    (["konto löschen","account löschen","daten löschen"],
     "🗑️ Konto löschen?\n→ Mein Konto → Tab 'Konto' → 'Konto dauerhaft löschen'\n→ Benutzernamen zur Bestätigung eingeben\n→ Nicht rückgängig machbar!"),

    (["update","version","neu","aktuell","patch","changelog"],
     f"🔄 Updates?\n→ App prüft beim Start automatisch auf Updates\n→ 'Was ist neu?' in der Sidebar für aktuelle Änderungen\n→ Downloads: github.com/{GITHUB_REPO}/releases"),
]

def rule_based_bot(message):
    msg_lower = message.lower()
    for keywords, answer in SUPPORT_RULES:
        if any(kw in msg_lower for kw in keywords):
            return answer, False  # (antwort, eskalieren)
    return None, True  # Nichts gefunden → eskalieren

# ─── ROUTES ───────────────────────────────────────────────────────────────────

@app.route("/health")
def health():
    return jsonify({"ok": True, "service": "Plüschi Mail-Bot", "version": "1.0"})

# ── 1. OTP senden ─────────────────────────────────────────────────────────────
@app.route("/api/send-otp", methods=["POST"])
def send_otp():
    data  = request.json or {}
    email = (data.get("email") or "").strip().lower()
    reason = data.get("reason", "login")  # "login" oder "reset"

    if not email:
        return jsonify({"success": False, "error": "E-Mail fehlt"}), 400

    # Rate-Limit: max 3 pro 10 Min
    ex = otp_store.get(email)
    if ex and time.time() - ex.get("first_sent", 0) < 600:
        if ex.get("count", 0) >= 3:
            return jsonify({"success": False, "error": "Zu viele Versuche. Bitte 10 Minuten warten."}), 429

    code = gen_otp()
    otp_store[email] = {
        "code": code,
        "expires": time.time() + 300,
        "attempts": 0,
        "reason": reason,
        "count": (ex.get("count", 0) + 1) if ex else 1,
        "first_sent": ex.get("first_sent", time.time()) if ex else time.time(),
    }

    if reason == "reset":
        title_text = "Passwort-Reset Code"
        heading = "Passwort zurücksetzen 🔑"
        desc = "Gib diesen Code in der App ein um dein Passwort zurückzusetzen:"
    else:
        title_text = "Dein Login-Code"
        heading = "Hier ist dein Login-Code 🔐"
        desc = "Gib diesen Code in der Plüschi App ein um dich anzumelden:"

    html = mail_template(
        title=title_text,
        body_html=f"""
<h2>{heading}</h2>
<p>{desc}</p>
<div class="code-box">
  <div class="code">{code}</div>
  <p style="color:#888;font-size:12px;margin:8px 0 0">Gültig für 5 Minuten</p>
</div>
<div class="warning">
  ⚠️ Teile diesen Code mit niemandem! Plüschi-Mitarbeiter fragen dich niemals danach.
</div>"""
    )

    if send_mail(email, f"Plüschi {'Login' if reason == 'login' else 'Reset'}-Code", html):
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Mail konnte nicht gesendet werden"}), 500


# ── 2. OTP verifizieren ───────────────────────────────────────────────────────
@app.route("/api/verify-otp", methods=["POST"])
def verify_otp():
    data  = request.json or {}
    email = (data.get("email") or "").strip().lower()
    code  = (data.get("code")  or "").strip()

    entry = otp_store.get(email)
    if not entry:
        return jsonify({"success": False, "error": "Kein Code angefordert"}), 400

    entry["attempts"] = entry.get("attempts", 0) + 1
    if entry["attempts"] > 5:
        del otp_store[email]
        return jsonify({"success": False, "error": "Zu viele Fehlversuche. Neuen Code anfordern."}), 429

    if time.time() > entry["expires"]:
        del otp_store[email]
        return jsonify({"success": False, "error": "Code abgelaufen"}), 400

    if entry["code"] != code:
        left = 5 - entry["attempts"]
        return jsonify({"success": False, "error": f"Falscher Code ({left} Versuche verbleibend)"}), 400

    reason = entry.get("reason", "login")
    del otp_store[email]
    return jsonify({"success": True, "reason": reason})


# ── 3. Passwort-Reset Bestätigungsmail ────────────────────────────────────────
@app.route("/api/reset-confirm-mail", methods=["POST"])
def reset_confirm_mail():
    """Schickt Bestätigungsmail nach erfolgreichem Passwort-Reset."""
    data  = request.json or {}
    email = (data.get("email") or "").strip().lower()
    if not email:
        return jsonify({"success": False}), 400

    html = mail_template(
        title="Passwort geändert",
        body_html="""
<h2>✅ Dein Passwort wurde geändert</h2>
<p>Das Passwort für deinen Plüschi-Account wurde erfolgreich aktualisiert.</p>
<div class="warning">
  ⚠️ Falls du das nicht warst, kontaktiere sofort unseren Support unter pluesch.support@gmail.com!
</div>"""
    )
    send_mail(email, "Plüschi: Passwort erfolgreich geändert", html)
    return jsonify({"success": True})


# ── 3b. Passwort-Reset abschließen (kein altes PW nötig) ─────────────────────
@app.route("/api/password-reset-complete", methods=["POST"])
def password_reset_complete():
    data         = request.json or {}
    email        = (data.get("email")        or "").strip().lower()
    new_password = (data.get("new_password") or "").strip()

    if not email or not new_password:
        return jsonify({"success": False, "error": "E-Mail und neues Passwort erforderlich"}), 400
    if len(new_password) < 6:
        return jsonify({"success": False, "error": "Passwort min. 6 Zeichen"}), 400

    index, _ = _get_index()
    username = next((u for u, e in index.items() if e == email), None)
    if not username:
        return jsonify({"success": False, "error": "Kein Konto mit dieser E-Mail"}), 404

    user_data, sha = _get_user(username)
    if not user_data:
        return jsonify({"success": False, "error": "Nutzer nicht gefunden"}), 404

    user_data["password"] = _hash_password(new_password)
    user_data["sessions"] = []  # Alle Sessions invalidieren
    _save_user(username, user_data, sha)

    send_mail(email, "Plüschi: Passwort zurückgesetzt", mail_template(
        title="Passwort zurückgesetzt",
        body_html="""<h2>✅ Passwort wurde zurückgesetzt</h2>
<p>Bitte melde dich jetzt mit deinem neuen Passwort an.</p>
<div class="warning">⚠️ Falls du das nicht warst, kontaktiere sofort unseren Support!</div>"""
    ))
    return jsonify({"success": True})


# ── 4. Support-Bot ────────────────────────────────────────────────────────────
@app.route("/api/support", methods=["POST"])
def support():
    data    = request.json or {}
    email   = (data.get("email")   or "").strip().lower()
    subject = (data.get("subject") or "Kein Betreff").strip()
    message = (data.get("message") or "").strip()

    if not email or not message:
        return jsonify({"success": False, "error": "E-Mail und Nachricht erforderlich"}), 400

    ticket_id = f"T{int(time.time())}"
    ticket = {
        "id": ticket_id,
        "email": email,
        "subject": subject,
        "message": message,
        "created_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "status": "open",
    }

    bot_reply, escalate = rule_based_bot(message)
    ticket["bot_response"] = bot_reply or ""
    ticket["status"] = "escalated" if escalate else "bot_answered"
    ticket_store.append(ticket)

    if escalate:
        send_mail(
            ADMIN_EMAIL,
            f"[Ticket #{ticket_id}] {subject}",
            mail_template(
                title="Neues Support-Ticket",
                body_html=f"""
<h2>⚠️ Ticket #{ticket_id} — manuelle Bearbeitung nötig</h2>
<p><strong>Von:</strong> {email}</p>
<p><strong>Betreff:</strong> {subject}</p>
<p><strong>Erstellt:</strong> {ticket['created_at']}</p>
<hr style="border-color:#2d2d4e;margin:20px 0">
<p><strong>Nachricht:</strong></p>
<p style="background:#0a0a0f;padding:12px;border-radius:8px;">{message}</p>""",
                footer="Ticket-System · Plüschi App"
            )
        )
        send_mail(email, f"[Ticket {ticket_id}] Deine Support-Anfrage", mail_template(
            title="Support-Ticket erstellt",
            body_html=f"""
<h2>Dein Ticket #{ticket_id} wird bearbeitet 🎫</h2>
<p>Unser Bot konnte dein Anliegen leider nicht automatisch lösen.</p>
<p>Ein Mensch meldet sich so schnell wie möglich bei dir.</p>
<p style="background:#0a0a0f;padding:12px;border-radius:8px;">{message}</p>
<p style="color:#888;font-size:13px;">Ticket-ID: {ticket_id} · {ticket['created_at']}</p>"""
        ))
        return jsonify({"success": True, "escalated": True, "ticket_id": ticket_id})
    else:
        # Antwort als HTML formatieren (Zeilenumbrüche)
        reply_html = bot_reply.replace("\n", "<br>")
        send_mail(email, f"Re: {subject}", mail_template(
            title="Support-Antwort",
            body_html=f"""
<h2>Antwort auf deine Anfrage 🤖</h2>
<p><strong>Deine Frage:</strong></p>
<p style="background:#0a0a0f;padding:12px;border-radius:8px;margin-bottom:16px;">{message}</p>
<p><strong>Antwort:</strong></p>
<p style="background:#0a0a0f;padding:12px;border-radius:8px;line-height:1.8;">{reply_html}</p>
<p style="margin-top:20px;font-size:13px;color:#888;">
  Nicht geholfen? Schreib uns erneut mit mehr Details — dann leiten wir weiter.
  Ticket-ID: {ticket_id}
</p>"""
        ))
        return jsonify({"success": True, "escalated": False, "ticket_id": ticket_id, "bot_response": bot_reply})



# ── 5. Register ───────────────────────────────────────────────────────────────
@app.route("/api/register", methods=["POST"])
def register():
    data     = request.json or {}
    username = (data.get("username") or "").strip().lower()
    email    = (data.get("email")    or "").strip().lower()
    password = (data.get("password") or "").strip()
    display  = (data.get("display_name") or username).strip()

    if not username or not password:
        return jsonify({"success": False, "error": "Benutzername und Passwort sind Pflicht"}), 400
    if len(username) < 3:
        return jsonify({"success": False, "error": "Benutzername min. 3 Zeichen"}), 400
    if len(password) < 6:
        return jsonify({"success": False, "error": "Passwort min. 6 Zeichen"}), 400
    if not GITHUB_TOKEN:
        return jsonify({"success": False, "error": "Userdb nicht konfiguriert (GITHUB_TOKEN fehlt)"}), 500

    index, idx_sha = _get_index()
    if username in index:
        return jsonify({"success": False, "error": "Benutzername bereits vergeben"}), 409
    if email and email in index.values():
        return jsonify({"success": False, "error": "E-Mail bereits registriert"}), 409

    token = gen_token()
    user_data = {
        "username": username, "display_name": display, "email": email,
        "password": _hash_password(password), "avatar": "🦊", "bio": "", "website": "",
        "plan": "free", "max_devices": 2,
        "joined": datetime.now().strftime("%d.%m.%Y"),
        "last_login": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "sessions": [{"token": token, "device": data.get("device", "Unbekannt"),
                      "created": time.time(), "last_active": time.time()}],
        "prefs": {"notifications": True, "stats": True, "theme_sync": False},
    }

    if not _save_user(username, user_data):
        return jsonify({"success": False, "error": "Fehler beim Speichern in GitHub"}), 500

    index[username] = email
    _save_index(index, idx_sha)

    if email:
        send_mail(email, "Willkommen bei Plüsch Downloader! 🦊", mail_template(
            title="Konto erstellt",
            body_html=f"""<h2>Willkommen, {display}! 🦊</h2>
<p>Dein Konto wurde erfolgreich erstellt.</p>
<p><strong>Benutzername:</strong> {username}</p>
<p style="color:#888;font-size:13px;">Du kannst dich jetzt auf allen deinen Geräten anmelden (max. 2 bei Free-Plan).</p>"""
        ))

    return jsonify({"success": True, "token": token, "user": {
        "username": username, "display_name": display, "email": email,
        "avatar": "🦊", "plan": "free", "joined": user_data["joined"],
        "bio": "", "website": "", "prefs": user_data["prefs"],
    }})


# ── 6. Login ──────────────────────────────────────────────────────────────────
@app.route("/api/login", methods=["POST"])
def login():
    data     = request.json or {}
    username = (data.get("username") or "").strip().lower()
    password = (data.get("password") or "").strip()
    device   = (data.get("device")   or "Unbekannt").strip()

    if not username or not password:
        return jsonify({"success": False, "error": "Benutzername und Passwort eingeben"}), 400

    user_data, sha = _get_user(username)
    if not user_data:
        return jsonify({"success": False, "error": "Benutzername nicht gefunden"}), 404
    if not _verify_password(password, user_data.get("password", "")):
        return jsonify({"success": False, "error": "Falsches Passwort"}), 401

    max_dev  = _get_max_devices(user_data.get("plan", "free"))
    sessions = _clean_sessions(user_data.get("sessions", []), max_dev)

    if len(sessions) >= max_dev:
        return jsonify({
            "success": False,
            "error": f"Maximale Geräteanzahl ({max_dev}) erreicht. Melde dich auf einem anderen Gerät ab.",
            "device_limit": True,
        }), 403

    token = gen_token()
    sessions.append({"token": token, "device": device,
                     "created": time.time(), "last_active": time.time()})
    user_data["sessions"] = sessions
    user_data["last_login"] = datetime.now().strftime("%d.%m.%Y %H:%M")
    _save_user(username, user_data, sha)

    return jsonify({"success": True, "token": token, "user": {
        "username": username, "display_name": user_data.get("display_name", username),
        "email": user_data.get("email", ""), "avatar": user_data.get("avatar", "🦊"),
        "bio": user_data.get("bio", ""), "website": user_data.get("website", ""),
        "plan": user_data.get("plan", "free"), "joined": user_data.get("joined", ""),
        "prefs": user_data.get("prefs", {}),
    }})


# ── 7. OTP-Login (nach Verifikation) ──────────────────────────────────────────
@app.route("/api/login/otp-complete", methods=["POST"])
def login_otp_complete():
    """Nach erfolgreichem OTP-Verify: Session erstellen per E-Mail."""
    data   = request.json or {}
    email  = (data.get("email")  or "").strip().lower()
    device = (data.get("device") or "Unbekannt").strip()

    index, _ = _get_index()
    username = next((u for u, e in index.items() if e == email), None)
    if not username:
        return jsonify({"success": False, "error": "Kein Konto mit dieser E-Mail"}), 404

    user_data, sha = _get_user(username)
    if not user_data:
        return jsonify({"success": False, "error": "Nutzer nicht gefunden"}), 404

    max_dev  = _get_max_devices(user_data.get("plan", "free"))
    sessions = _clean_sessions(user_data.get("sessions", []), max_dev)

    if len(sessions) >= max_dev:
        return jsonify({"success": False, "error": f"Gerätelimit ({max_dev}) erreicht.", "device_limit": True}), 403

    token = gen_token()
    sessions.append({"token": token, "device": device, "created": time.time(), "last_active": time.time()})
    user_data["sessions"] = sessions
    user_data["last_login"] = datetime.now().strftime("%d.%m.%Y %H:%M")
    _save_user(username, user_data, sha)

    return jsonify({"success": True, "token": token, "user": {
        "username": username, "display_name": user_data.get("display_name", username),
        "email": email, "avatar": user_data.get("avatar", "🦊"),
        "bio": user_data.get("bio", ""), "website": user_data.get("website", ""),
        "plan": user_data.get("plan", "free"), "joined": user_data.get("joined", ""),
        "prefs": user_data.get("prefs", {}),
    }})


# ── 8. Session validieren ─────────────────────────────────────────────────────
@app.route("/api/session/check", methods=["POST"])
def session_check():
    data     = request.json or {}
    username = (data.get("username") or "").strip().lower()
    token    = (data.get("token")    or "").strip()

    user_data, sha = _get_user(username)
    if not user_data:
        return jsonify({"success": False, "error": "Nutzer nicht gefunden"}), 404

    sessions = user_data.get("sessions", [])
    session  = next((s for s in sessions if s.get("token") == token), None)
    if not session:
        return jsonify({"success": False, "error": "Session abgelaufen — bitte neu anmelden"}), 401

    session["last_active"] = time.time()
    user_data["sessions"] = sessions
    _save_user(username, user_data, sha)

    return jsonify({"success": True, "user": {
        "username": username, "display_name": user_data.get("display_name", username),
        "email": user_data.get("email", ""), "avatar": user_data.get("avatar", "🦊"),
        "bio": user_data.get("bio", ""), "website": user_data.get("website", ""),
        "plan": user_data.get("plan", "free"), "joined": user_data.get("joined", ""),
        "prefs": user_data.get("prefs", {}),
        "sessions": [{"device": s.get("device"), "last_active": s.get("last_active"),
                      "created": s.get("created"), "is_current": s.get("token") == token,
                      "token_hint": s.get("token", "")[:8]}
                     for s in sessions],
    }})


# ── 9. Logout ─────────────────────────────────────────────────────────────────
@app.route("/api/session/logout", methods=["POST"])
def logout():
    data     = request.json or {}
    username = (data.get("username") or "").strip().lower()
    token    = (data.get("token")    or "").strip()
    all_dev  = data.get("all_devices", False)

    user_data, sha = _get_user(username)
    if not user_data:
        return jsonify({"success": False, "error": "Nutzer nicht gefunden"}), 404

    user_data["sessions"] = [] if all_dev else [
        s for s in user_data.get("sessions", []) if s.get("token") != token
    ]
    _save_user(username, user_data, sha)
    return jsonify({"success": True})


# ── 10. Profil aktualisieren ──────────────────────────────────────────────────
@app.route("/api/user/update", methods=["POST"])
def user_update():
    data     = request.json or {}
    username = (data.get("username") or "").strip().lower()
    token    = (data.get("token")    or "").strip()

    user_data, sha = _get_user(username)
    if not user_data:
        return jsonify({"success": False, "error": "Nutzer nicht gefunden"}), 404
    if not any(s.get("token") == token for s in user_data.get("sessions", [])):
        return jsonify({"success": False, "error": "Nicht autorisiert"}), 401

    for field in ["display_name", "email", "bio", "website", "avatar", "prefs"]:
        if field in data:
            user_data[field] = data[field]

    if data.get("new_password") and data.get("old_password"):
        if not _verify_password(data["old_password"], user_data.get("password", "")):
            return jsonify({"success": False, "error": "Aktuelles Passwort falsch"}), 401
        if len(data["new_password"]) < 6:
            return jsonify({"success": False, "error": "Neues Passwort min. 6 Zeichen"}), 400
        user_data["password"] = _hash_password(data["new_password"])
        if user_data.get("email"):
            send_mail(user_data["email"], "Plüschi: Passwort geändert", mail_template(
                title="Passwort geändert",
                body_html="""<h2>✅ Passwort wurde geändert</h2>
<div class="warning">⚠️ Falls du das nicht warst, kontaktiere sofort unseren Support!</div>"""
            ))

    if "email" in data:
        index, idx_sha = _get_index()
        index[username] = data["email"]
        _save_index(index, idx_sha)

    _save_user(username, user_data, sha)
    return jsonify({"success": True})


# ── 11. Konto löschen ─────────────────────────────────────────────────────────
@app.route("/api/user/delete", methods=["POST"])
def user_delete():
    data     = request.json or {}
    username = (data.get("username") or "").strip().lower()
    token    = (data.get("token")    or "").strip()
    password = (data.get("password") or "").strip()

    user_data, sha = _get_user(username)
    if not user_data:
        return jsonify({"success": False, "error": "Nutzer nicht gefunden"}), 404
    if not any(s.get("token") == token for s in user_data.get("sessions", [])):
        return jsonify({"success": False, "error": "Nicht autorisiert"}), 401
    if not _verify_password(password, user_data.get("password", "")):
        return jsonify({"success": False, "error": "Falsches Passwort"}), 401

    _delete_user_file(username, sha)
    index, idx_sha = _get_index()
    index.pop(username, None)
    _save_index(index, idx_sha)
    return jsonify({"success": True})


# ── 12. Geräte verwalten ──────────────────────────────────────────────────────
@app.route("/api/user/devices", methods=["POST"])
def user_devices():
    data     = request.json or {}
    username = (data.get("username") or "").strip().lower()
    token    = (data.get("token")    or "").strip()

    user_data, _ = _get_user(username)
    if not user_data:
        return jsonify({"success": False, "error": "Nutzer nicht gefunden"}), 404
    if not any(s.get("token") == token for s in user_data.get("sessions", [])):
        return jsonify({"success": False, "error": "Nicht autorisiert"}), 401

    sessions = _clean_sessions(user_data.get("sessions", []),
                               _get_max_devices(user_data.get("plan", "free")))
    return jsonify({"success": True,
        "devices": [{"device": s.get("device", "Unbekannt"),
                     "last_active": datetime.fromtimestamp(s.get("last_active", 0)).strftime("%d.%m.%Y %H:%M"),
                     "created": datetime.fromtimestamp(s.get("created", 0)).strftime("%d.%m.%Y"),
                     "is_current": s.get("token") == token,
                     "token_hint": s.get("token", "")[:8]} for s in sessions],
        "plan": user_data.get("plan", "free"),
        "max_devices": _get_max_devices(user_data.get("plan", "free"))})


# ── 13. Einzelnes Gerät abmelden ──────────────────────────────────────────────
@app.route("/api/user/devices/remove", methods=["POST"])
def remove_device():
    data        = request.json or {}
    username    = (data.get("username")   or "").strip().lower()
    token       = (data.get("token")      or "").strip()
    remove_hint = (data.get("token_hint") or "").strip()

    user_data, sha = _get_user(username)
    if not user_data:
        return jsonify({"success": False, "error": "Nutzer nicht gefunden"}), 404
    if not any(s.get("token") == token for s in user_data.get("sessions", [])):
        return jsonify({"success": False, "error": "Nicht autorisiert"}), 401

    user_data["sessions"] = [s for s in user_data.get("sessions", [])
                              if not s.get("token", "").startswith(remove_hint)]
    _save_user(username, user_data, sha)
    return jsonify({"success": True})


# ── 14. Patch Notes ───────────────────────────────────────────────────────────
@app.route("/api/patchnotes")
def patchnotes():
    """Holt die neuesten Release Notes von GitHub."""
    try:
        import urllib.request, json as _json
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        req = urllib.request.Request(url, headers={"User-Agent": "PlueschDownloader"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = _json.loads(r.read().decode())
        return jsonify({
            "success": True,
            "tag_name": data.get("tag_name",""),
            "body": data.get("body",""),
            "published_at": data.get("published_at",""),
            "html_url": data.get("html_url",""),
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == "__main__":
    print("🦊 Plüschi Mail-Bot läuft auf http://localhost:5001")
    app.run(debug=False, port=5001)
