import random, json, hashlib, os
from pathlib import Path
from fastapi import (
    FastAPI,
    Request,
    WebSocket,
    WebSocketDisconnect,
    Depends,
    HTTPException,
    status,
)
from dotenv import load_dotenv
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Receive, Send, Scope


class Board(object):
    last_used_picture = 277
    last_starting_team = "red"

    def __init__(self):
        if Board.last_used_picture > (len(all_pictures) - 21):
            random.shuffle(all_pictures)
            Board.last_used_picture = -1

        self.pictures = all_pictures[
            (Board.last_used_picture + 1) : (Board.last_used_picture + 21)
        ]
        Board.last_used_picture += 21
        self._generate_map()
        self.revealed = [False] * 20
        self.touched_black = False

    def _generate_map(self):
        self.map = (
            ["black0"]
            + [f"white{x}" for x in range(4)]
            + [f"red{x}" for x in range(7)]
            + [f"blue{x}" for x in range(7)]
        )
        if Board.last_starting_team == "blue":
            Board.last_starting_team = "red"
            self.map.append("red7")
            self.guesses = dict(red=8, blue=7)
            self.starting_team = "red"
        else:
            Board.last_starting_team = "blue"
            self.map.append("blue7")
            self.guesses = dict(red=7, blue=8)
            self.starting_team = "blue"
        random.shuffle(self.map)

        self.game_map = []
        for cell in self.map:
            self.game_map.append(cell[:-1])

    def reveal(self, cell):
        if self.map[cell].startswith("red"):
            self.guesses["red"] -= 1
        elif self.map[cell].startswith("blue"):
            self.guesses["blue"] -= 1
        elif self.map[cell].startswith("black"):
            self.touched_black = True
        self.revealed[cell] = True

    @property
    def board_id(self):
        state_str = ",".join(self.map + self.pictures)
        obj = hashlib.md5(state_str.encode("ascii"))
        return obj.hexdigest()


class Game(object):

    def __init__(self):
        self.board = None
        self.players = set()
        self.codemasters = []
        self.reset_scores()

    def reset_scores(self):
        self.scores = dict(red=0, blue=0)

    def start(self):
        self.board = Board()

    def has_started(self):
        return self.board is not None

    def add_player(self, nickname):
        self.players.add(nickname)

    def set_codemasters(self, *nicknames):
        self.codemasters = set(nicknames)

    def mark_winner(self, team):
        self.scores[team] += 1


BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env file if present
load_dotenv()

# HTTP Basic Authentication setup using PBKDF2 (no plaintext passwords)
stored_password_hash = os.getenv("HTTP_PASSWORD_HASH")
if not stored_password_hash:
    raise RuntimeError(
        "HTTP_PASSWORD_HASH environment variable must be set (format: salt$hash)"
    )

security = HTTPBasic()


def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    if credentials.username != "codenames":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    # Parse stored salt and hash
    try:
        salt_hex, hash_hex = stored_password_hash.split("$")
        salt = bytes.fromhex(salt_hex)
        stored_key = bytes.fromhex(hash_hex)
    except Exception:
        raise RuntimeError("Invalid HTTP_PASSWORD_HASH format")
    # Compute PBKDF2 of provided password
    input_key = hashlib.pbkdf2_hmac(
        "sha256", credentials.password.encode(), salt, 100000
    )
    if input_key != stored_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


app = FastAPI()


class CachedStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


app.mount(
    "/pictures", CachedStaticFiles(directory=BASE_DIR / "pictures"), name="pictures"
)
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent / "templates")
)
all_pictures = [f"{x}" for x in range(278)]
game = Game()
connected_clients: set[WebSocket] = set()


def get_state_snapshot():
    ensure_game()
    return {
        "state": game.board.revealed,
        "board_id": game.board.board_id,
        "scores": game.scores,
        "guesses": game.board.guesses,
    }


async def broadcast_state():
    global connected_clients
    state = get_state_snapshot()
    dead = set()
    for ws in connected_clients:
        try:
            await ws.send_json(state)
        except:
            dead.add(ws)
    connected_clients -= dead


def ensure_game():
    global game
    if not game.has_started():
        game.start()


def need_loggin(request: Request):
    nickname = request.cookies.get("nickname")
    return nickname is None


@app.get(
    "/nickname", response_class=HTMLResponse, dependencies=[Depends(verify_credentials)]
)
async def nickname(request: Request):
    response = templates.TemplateResponse("nickname.html", {"request": request})
    response.set_cookie("authenticated", "yes", httponly=True, path="/")
    return response


@app.get("/", response_class=HTMLResponse, dependencies=[Depends(verify_credentials)])
async def main(request: Request):
    if need_loggin(request):
        return RedirectResponse("/nickname")

    ensure_game()
    global game
    response = templates.TemplateResponse(
        "board.html",
        {
            "request": request,
            "game": game,
            "state": json.dumps(game.board.revealed),
            "game_map": game.board.game_map,
            "board_id": game.board.board_id,
            "starting": "primary" if game.board.starting_team == "blue" else "danger",
            "nickname": request.cookies.get("nickname"),
            "admin": is_admin(request),
            "codemaster": is_codemaster(request),
        },
    )
    response.set_cookie("authenticated", "yes", httponly=True, path="/")
    return response


def calc_state(request: Request):
    ensure_game()
    global game

    game.add_player(request.cookies.get("nickname"))
    return {
        "state": game.board.revealed,
        "board_id": game.board.board_id,
        "scores": game.scores,
        "guesses": game.board.guesses,
    }


@app.get("/guess/{cell}", dependencies=[Depends(verify_credentials)])
async def guess(cell: int):
    ensure_game()
    global game
    game.board.reveal(cell)

    if game.board.touched_black:
        await broadcast_state()
        return "ok"

    guesses = game.board.guesses
    if (guesses["red"] == 0) and (guesses["blue"] > 0):
        game.mark_winner("red")
    elif (guesses["blue"] == 0) and (guesses["red"] > 0):
        game.mark_winner("blue")

    await broadcast_state()
    return "ok"


@app.get("/state", dependencies=[Depends(verify_credentials)])
async def get_state(request: Request):
    return calc_state(request)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    try:
        await websocket.accept()
        print(
            f"[WS] Accepted connection from {websocket.client}, cookies: {websocket.cookies}"
        )

        # Check for authenticated cookie
        auth_cookie = websocket.cookies.get("authenticated")
        if auth_cookie != "yes":
            print(f"[WS] Missing/invalid authenticated cookie: {auth_cookie}, closing")
            await websocket.close(code=1008, reason="Unauthorized")
            return
        print("[WS] Authentication passed")

        # Track player for admin UI
        nickname = websocket.cookies.get("nickname")
        if nickname:
            game.add_player(nickname)
        connected_clients.add(websocket)

        try:
            print("[WS] Sending initial state")
            await websocket.send_json(get_state_snapshot())
            print("[WS] Initial state sent, entering message loop")
            while True:
                data = await websocket.receive_text()
                try:
                    msg = json.loads(data)
                    if msg.get("type") == "guess":
                        cell = msg.get("cell")
                        print(f"[WS] Received guess: cell={cell}, type={type(cell)}")
                        if cell is not None:
                            ensure_game()
                            print(
                                f"[WS] Revealing cell {cell}, state before: {game.board.revealed}"
                            )
                            game.board.reveal(cell)
                            print(
                                f"[WS] Revealed, state after: {game.board.revealed}, touched_black={game.board.touched_black}"
                            )

                            if game.board.touched_black:
                                print("[WS] Black touched, broadcasting")
                                await broadcast_state()
                            else:
                                guesses = game.board.guesses
                                print(f"[WS] Guesses: {guesses}")
                                if (guesses["red"] == 0) and (guesses["blue"] > 0):
                                    game.mark_winner("red")
                                    print("[WS] Red won")
                                elif (guesses["blue"] == 0) and (guesses["red"] > 0):
                                    game.mark_winner("blue")
                                    print("[WS] Blue won")
                                await broadcast_state()
                except Exception as e:
                    print(f"[WS] Error processing message: {e}")
                    import traceback

                    traceback.print_exc()
        except WebSocketDisconnect:
            print("[WS] Client disconnected normally")
            connected_clients.discard(websocket)
        except Exception as e:
            print(f"[WS] Unexpected error in message loop: {e}")
            import traceback

            traceback.print_exc()
            connected_clients.discard(websocket)
    except Exception as e:
        print(f"[WS] Outer exception: {e}")
        import traceback

        traceback.print_exc()
        await websocket.send_json(get_state_snapshot())
        # Listen for messages from this client
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("type") == "guess":
                    cell = msg.get("cell")
                    print(f"[WS] Received guess: cell={cell}, type={type(cell)}")
                    if cell is not None:
                        # Reuse the guess logic (reveal + broadcast)
                        ensure_game()
                        print(
                            f"[WS] Revealing cell {cell}, state before: {game.board.revealed}"
                        )
                        game.board.reveal(cell)
                        print(
                            f"[WS] Revealed, state after: {game.board.revealed}, touched_black={game.board.touched_black}"
                        )

                        if game.board.touched_black:
                            print("[WS] Black touched, broadcasting")
                            await broadcast_state()
                        else:
                            guesses = game.board.guesses
                            print(f"[WS] Guesses: {guesses}")
                            if (guesses["red"] == 0) and (guesses["blue"] > 0):
                                game.mark_winner("red")
                                print("[WS] Red won")
                            elif (guesses["blue"] == 0) and (guesses["red"] > 0):
                                game.mark_winner("blue")
                                print("[WS] Blue won")
                            await broadcast_state()
            except Exception as e:
                print(f"[WS] Error processing message: {e}")
                import traceback

                traceback.print_exc()
    except WebSocketDisconnect:
        connected_clients.discard(websocket)


@app.post("/setNickname", dependencies=[Depends(verify_credentials)])
async def set_nickname(request: Request):
    ensure_game()
    global game

    form = await request.form()
    nickname = form.get("nickname")
    if nickname in game.players:
        return RedirectResponse("/nickname", status_code=303)

    game.add_player(nickname)
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie("nickname", nickname)
    resp.set_cookie("authenticated", "yes", httponly=True, path="/")
    return resp


def is_admin(request: Request):
    return (
        request.cookies.get("admin") is not None
        and request.cookies.get("admin") == "yes"
    )


def generate_admin_page(request: Request, error=False, authenticated=True):
    ensure_game()
    global game

    players = [{"name": x, "codemaster": (x in game.codemasters)} for x in game.players]
    response = templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "players": players,
            "error": error,
            "authenticated": authenticated,
        },
    )
    response.set_cookie("authenticated", "yes", httponly=True, path="/")
    return response


@app.get(
    "/admin", response_class=HTMLResponse, dependencies=[Depends(verify_credentials)]
)
async def admin(request: Request):
    if is_admin(request):
        return generate_admin_page(request)
    else:
        return generate_admin_page(request, authenticated=False)


@app.post("/adminLogin", dependencies=[Depends(verify_credentials)])
async def admin_login(request: Request):
    form = await request.form()
    username = form.get("username")
    password = form.get("password")
    if (username == "admin") and (password == "$Hipod"):
        resp = RedirectResponse("/admin", status_code=303)
        resp.set_cookie("admin", "yes")
        resp.set_cookie("authenticated", "yes", httponly=True, path="/")
        return resp
    else:
        return RedirectResponse("/admin", status_code=303)


@app.post("/setCodemasters", dependencies=[Depends(verify_credentials)])
async def set_codemasters(request: Request):
    if is_admin(request):
        global game

        form = await request.form()
        codemasters = form.getlist("codemasters")
        if len(codemasters) > 2:
            return generate_admin_page(request, error=True)

        game.set_codemasters(*codemasters)
        game.start()
        await broadcast_state()
        return RedirectResponse("/", status_code=303)
    else:
        return RedirectResponse("/admin", status_code=303)


@app.get("/newgame", dependencies=[Depends(verify_credentials)])
@app.get("/newgame/{won}", dependencies=[Depends(verify_credentials)])
async def new_game(request: Request, won: str = None):
    ensure_game()
    global game

    if not is_admin(request):
        return RedirectResponse("/", status_code=303)

    game.start()
    if won is not None:
        game.mark_winner(won)
    await broadcast_state()
    return RedirectResponse("/", status_code=303)


@app.get("/resetScores", dependencies=[Depends(verify_credentials)])
async def reset_scores(request: Request):
    if not is_admin(request):
        return RedirectResponse("/", status_code=303)

    ensure_game()
    global game
    game.reset_scores()
    await broadcast_state()
    return RedirectResponse("/", status_code=303)


def is_codemaster(request: Request):
    ensure_game()
    global game

    nickname = request.cookies.get("nickname")
    return nickname in game.codemasters
