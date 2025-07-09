import json
import os
import hashlib
import urllib.parse
from wsgiref.simple_server import make_server

DATA_DIR = "data"


def load_json(name):
    path = os.path.join(DATA_DIR, name)
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        return json.load(f)


def save_json(name, data):
    path = os.path.join(DATA_DIR, name)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


class MoodMakerApp:
    def __init__(self):
        self.songs = load_json("songs.json")
        self.users = load_json("users.json")
        self.playlists = load_json("playlists.json")

    def save_data(self):
        save_json("users.json", self.users)
        save_json("playlists.json", self.playlists)

    def __call__(self, environ, start_response):
        method = environ["REQUEST_METHOD"]
        path = environ["PATH_INFO"]
        cookies = self.parse_cookies(environ.get("HTTP_COOKIE", ""))
        
        if path.startswith("/static/"):
            return self.serve_static(path, start_response)
        if path == "/" and method == "GET":
            return self.home(start_response, cookies.get("user"))
        if path == "/generate" and method == "POST":
            return self.generate(environ, start_response, cookies.get("user"))
        if path == "/save" and method == "POST":
            return self.save_playlist(environ, start_response, cookies.get("user"))
        if path == "/playlists" and method == "GET":
            return self.my_playlists(start_response, cookies.get("user"))
        if path.startswith("/share/") and method == "GET":
            pid = path.split("/")[2]
            return self.share_playlist(start_response, pid)
        if path == "/login":
            if method == "GET" or method == "POST":
                return self.login(environ, start_response)
        if path == "/register":
            if method == "GET" or method == "POST":
                return self.register(environ, start_response)
        if path == "/logout" and method == "GET":
            return self.logout(start_response)
        start_response("404 Not Found", [("Content-Type", "text/plain")])
        return [b"Not Found"]

    def parse_cookies(self, cookie_header):
        cookies = {}
        for item in cookie_header.split(";"):
            if "=" in item:
                k, v = item.strip().split("=", 1)
                cookies[k] = v
        return cookies

    def render_template(self, name, **context):
        with open(os.path.join("templates", name)) as f:
            html = f.read()
        return html.format(**context)

    def redirect(self, start_response, location):
        start_response("302 Found", [("Location", location)])
        return [b""]

    def home(self, start_response, user):
        username = user if user else "Guest"
        login_action = "logout" if user else "login"
        body = self.render_template("index.html", username=username, login_action=login_action)
        html = self.render_template("base.html", content=body)
        start_response("200 OK", [("Content-Type", "text/html")])
        return [html.encode()]

    def read_post_data(self, environ):
        length = int(environ.get("CONTENT_LENGTH", 0) or 0)
        data = environ["wsgi.input"].read(length).decode()
        return urllib.parse.parse_qs(data)

    def generate(self, environ, start_response, user):
        params = self.read_post_data(environ)
        mood = params.get("mood", [""])[0]
        custom = params.get("custom", [""])[0].strip()
        mood_key = custom.lower() if custom else mood.lower()
        songs = [s for s in self.songs if mood_key in s.get("moods", [])]
        if not songs:
            songs = self.songs[:5]
        song_items = "".join(f"<li>{s['title']} - {s['artist']}</li>" for s in songs)
        song_ids = ",".join(str(s["id"]) for s in songs)
        body = self.render_template("playlist.html", mood=mood_key, songs=song_items, song_ids=song_ids)
        html = self.render_template("base.html", content=body)
        start_response("200 OK", [("Content-Type", "text/html")])
        return [html.encode()]

    def save_playlist(self, environ, start_response, user):
        if not user:
            return self.redirect(start_response, "/login")
        params = self.read_post_data(environ)
        name = params.get("name", [""])[0]
        song_ids = [int(i) for i in params.get("song_ids", [""])[0].split(",") if i]
        pid = str(len(self.playlists) + 1)
        self.playlists[pid] = {"id": pid, "name": name, "songs": song_ids, "owner": user}
        self.users.setdefault(user, {}).setdefault("playlists", []).append(pid)
        self.save_data()
        return self.redirect(start_response, f"/share/{pid}")

    def my_playlists(self, start_response, user):
        if not user:
            return self.redirect(start_response, "/login")
        items = []
        for pid in self.users.get(user, {}).get("playlists", []):
            pl = self.playlists.get(pid)
            if pl:
                items.append(f"<li><a href='/share/{pid}'>{pl['name']}</a></li>")
        body = self.render_template("my_playlists.html", items="\n".join(items))
        html = self.render_template("base.html", content=body)
        start_response("200 OK", [("Content-Type", "text/html")])
        return [html.encode()]

    def share_playlist(self, start_response, pid):
        pl = self.playlists.get(pid)
        if not pl:
            start_response("404 Not Found", [("Content-Type", "text/plain")])
            return [b"Playlist not found"]
        songs = [self.get_song(sid) for sid in pl["songs"]]
        song_items = "".join(f"<li>{s['title']} - {s['artist']}</li>" for s in songs if s)
        body = self.render_template("share.html", name=pl["name"], songs=song_items)
        html = self.render_template("base.html", content=body)
        start_response("200 OK", [("Content-Type", "text/html")])
        return [html.encode()]

    def login(self, environ, start_response):
        if environ["REQUEST_METHOD"] == "GET":
            body = self.render_template("login.html", action="login")
            html = self.render_template("base.html", content=body)
            start_response("200 OK", [("Content-Type", "text/html")])
            return [html.encode()]
        params = self.read_post_data(environ)
        username = params.get("username", [""])[0]
        password = params.get("password", [""])[0]
        pwd_hash = hashlib.sha256(password.encode()).hexdigest()
        if username in self.users and self.users[username]["password"] == pwd_hash:
            start_response("302 Found", [("Location", "/"), ("Set-Cookie", f"user={username}; Path=/")])
            return [b""]
        body = "Login failed"
        html = self.render_template("base.html", content=body)
        start_response("401 Unauthorized", [("Content-Type", "text/html")])
        return [html.encode()]

    def register(self, environ, start_response):
        if environ["REQUEST_METHOD"] == "GET":
            body = self.render_template("login.html", action="register")
            html = self.render_template("base.html", content=body)
            start_response("200 OK", [("Content-Type", "text/html")])
            return [html.encode()]
        params = self.read_post_data(environ)
        username = params.get("username", [""])[0]
        password = params.get("password", [""])[0]
        if username in self.users:
            body = "User exists"
            html = self.render_template("base.html", content=body)
            start_response("400 Bad Request", [("Content-Type", "text/html")])
            return [html.encode()]
        pwd_hash = hashlib.sha256(password.encode()).hexdigest()
        self.users[username] = {"password": pwd_hash, "playlists": []}
        self.save_data()
        start_response("302 Found", [("Location", "/login")])
        return [b""]

    def logout(self, start_response):
        start_response("302 Found", [("Location", "/"), ("Set-Cookie", "user=; Path=/; Max-Age=0")])
        return [b""]

    def serve_static(self, path, start_response):
        file_path = path.lstrip("/")
        if not os.path.exists(file_path):
            start_response("404 Not Found", [("Content-Type", "text/plain")])
            return [b"Not Found"]
        with open(file_path, "rb") as f:
            content = f.read()
        start_response("200 OK", [("Content-Type", "text/css")])
        return [content]

    def get_song(self, sid):
        for s in self.songs:
            if s["id"] == sid:
                return s
        return None


def run():
    app = MoodMakerApp()
    with make_server("", 8000, app) as httpd:
        print("Serving on port 8000...")
        httpd.serve_forever()


if __name__ == "__main__":
    run()
