import random, json, hashlib
from flask import Flask, render_template, jsonify, request, redirect, make_response


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


app = Flask(__name__, static_url_path="/", static_folder="..")
all_pictures = [f"{x}" for x in range(278)]
game = Game()


def ensure_game():
    global game
    if not game.has_started():
        game.start()


def need_loggin():
    nickname = request.cookies.get('nickname')
    return nickname is None


@app.route('/nickname')
def nickname():
    return render_template("nickname.html")


@app.route("/")
def main():
    if need_loggin():
        return redirect("/nickname")

    ensure_game()
    global game
    return render_template("board.html",
                           game=game,
                           state=json.dumps(game.board.revealed),
                           game_map=game.board.game_map,
                           board_id=game.board.board_id,
                           starting="primary" if game.board.starting_team == "blue" else "danger",
                           nickname=request.cookies.get('nickname'),
                           admin=is_admin(),
                           codemaster=is_codemaster())


def calc_state():
    ensure_game()
    global game

    game.add_player(request.cookies.get('nickname'))
    return {"state": game.board.revealed,
            "board_id": game.board.board_id,
            "scores": game.scores,
            "guesses": game.board.guesses}


@app.route('/guess/<int:cell>')
def guess(cell):
    ensure_game()
    global game
    game.board.reveal(cell)

    if game.board.touched_black:
        return "ok"

    guesses = game.board.guesses
    if (guesses["red"] == 0) and (guesses["blue"] > 0):
        game.mark_winner("red")
    elif (guesses["blue"] == 0) and (guesses["red"] > 0):
        game.mark_winner("blue")

    return "ok"


@app.route('/state')
def get_state():
    return jsonify(calc_state())


@app.route('/setNickname', methods=['POST'])
def set_nickname():
    ensure_game()
    global game

    nickname = request.form.get('nickname')
    if nickname in game.players:
        return redirect("/nickname")

    game.add_player(nickname)
    resp = make_response(redirect("/"))
    resp.set_cookie('nickname', nickname)
    return resp


def is_admin():
    return request.cookies.get('admin') is not None \
            and request.cookies.get('admin') == "yes"


def generate_admin_page(error=False, authenticated=True):
    ensure_game()
    global game

    players = [{"name": x, "codemaster": (x in game.codemasters)} for x in game.players]
    return render_template("admin.html",
                           players=players,
                           error=error,
                           authenticated=authenticated)


@app.route('/admin')
def admin():
    if is_admin():
        return generate_admin_page()
    else:
        return generate_admin_page(authenticated=False)


@app.route('/adminLogin', methods=['POST'])
def admin_login():
    username = request.form.get("username")
    password = request.form.get("password")
    if (username == "admin") and (password=="$Hipod"):
        resp = make_response(redirect("/admin"))
        resp.set_cookie('admin', "yes")
        return resp
    else:
        return redirect("/admin")


@app.route('/setCodemasters', methods=['POST'])
def set_codemasters():
    if is_admin():
        global game

        codemasters = request.form.getlist('codemasters')
        if len(codemasters) > 2:
            return generate_admin_page(error=True)

        game.set_codemasters(*codemasters)
        game.start()
        return redirect("/")
    else:
        return redirect("/admin")


@app.route('/newgame', defaults={'won': None})
@app.route('/newgame/<won>')
def new_game(won):
    ensure_game()
    global game

    if not is_admin():
        return redirect("/")

    game.start()
    if won is not None:
        game.mark_winner(won)
    return redirect("/")


@app.route('/resetScores')
def reset_scores():
    if not is_admin():
        return redirect("/")

    ensure_game()
    global game
    game.reset_scores()
    return redirect("/")


def is_codemaster():
    ensure_game()
    global game

    nickname = request.cookies.get('nickname')
    return nickname in game.codemasters