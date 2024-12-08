from threading import Thread
import time
import random
from typing import TypedDict
from network import (
    Connection, 
    get_local_ip, 
    known_peers, 
    node_id, 
    send_to_clients, 
    clear_server_messages,
    poll_server_msg_queue,
    maintenance_msg_in,
    SYNC_GAMESTATE
)
import uuid
from logger import get_logger, logging

# Intialize global variables
global new_player_joined
X_MIN, X_MAX, Y_MIN, Y_MAX = 0, 580, 0, 380
POINT_LIMIT = 5
GATHERABLE_LIMIT = 3
new_player_joined = False
HOST = get_local_ip()
gamestate_clock = 0
logger = get_logger("server", logging.DEBUG)

# Game state and connected clients
class PosStatus(TypedDict):
    last_direction: str
    position: tuple[int, int]
    points: int
    games_won: int


class ScoreStatus(TypedDict):
    points: int
    games_won: int


players: dict[
    str, PosStatus
] = {}  # Stores each player's last direction and current position {player_id: {'last_direction': direction, 'position': (x, y)}}
clients: list[
    tuple[Connection, int]
] = []  # List to keep track of connected clients (client_socket, player_id)
gatherables: dict[
    int, tuple  # Stores information about gatherable objects
] = {}
scoreboard: dict[int, ScoreStatus] = {}  # Stores each player's points and rounds won


def get_server_maintenance_message():
    """Retrieves server maintenance message from queue"""
    try:
        return maintenance_msg_in.get(block=False)
    except Exception:
        return None

def sync_gamestate():
    """Sync gamestate after server change."""
    global players, scoreboard, gatherables, gamestate_clock
    maint_msg = get_server_maintenance_message()

    if maint_msg == SYNC_GAMESTATE:
        # The server needs to ask for gamestate clocks from the clients
        # and select the highest one as the new gamestate
        send_to_clients({"sync_gamestate": gamestate_clock})
        time.sleep(3)

        while True:
            peer_id, msg = poll_server_msg_queue()
            if peer_id == None:
                break
            if "sync_gamestate" not in msg:
                continue
            if gamestate_clock < msg["sync_gamestate"]:
                # Update the server gamestate to the received one
                gamestate_clock = msg["sync_gamestate"]
                players = msg["players"]
                scoreboard = msg["scoreboard"]
                gatherables = msg["gatherables"]

        # Update clients to newest gamestate
        send_to_clients({
            "clock": gamestate_clock,
            "players": players,
            "gatherables": gatherables,
            "scoreboard": scoreboard,
        })

        
    
def create_new_player(peer_id: str):
    """Creates a new player to the players dict"""
    global new_player_joined
    new_player_joined = True

    players[peer_id] = {
        "position": (0, 0),
        "last_direction": None,
        "points": 0,
        "games_won": 0,
    }

    # Add player to scoreboard
    scoreboard[peer_id] = {"points": 0, "games_won": 0}
    
def process_player_messages():
    """Process all received player messages from the game_msg_in queue 
    and update player movement directions."""
    while True:
        peer_id, msg = poll_server_msg_queue()
        if peer_id == None and msg == None:
            return
        peer_id = str(peer_id)
        if "move" in msg:
            players[peer_id]["last_direction"] = msg["move"]


def handle_player_status():
    """Add/remove players if they are/aren't in the known peers."""
    # Add any new peers to players
    peers = known_peers.copy()
    for peer_id in peers:
        peer_id = str(peer_id)
        if peer_id not in players:
            create_new_player(peer_id)

    # Remove players that are no longer peers
    players_copy = players.copy()
    for player_id in players_copy:
        pid = uuid.UUID(player_id)
        if pid not in peers:
            logger.debug(f"Client {player_id} removed from players.")
            del players[player_id]
            del scoreboard[player_id]

# Server's game loop for handling movements every second
def update_positions():
    gatherable_change = False
    score_change = False
    global new_player_joined, gamestate_clock
    increment = 10

    while True:
        time.sleep(1 / 5)  # Move players every 1 second

        if known_peers.get_leader() != node_id:
            clear_server_messages()
            continue

        handle_player_status()
        sync_gamestate()
        process_player_messages()

        # Update each player's position based on their last command
        for player_id, player_data in players.items():
            x, y = player_data["position"]
            direction = player_data["last_direction"]

            # Move the player based on the last direction
            if direction == "up":
                if border_check(y, "y", "up", increment):
                    y -= increment
            elif direction == "down":
                if border_check(y, "y", "down", increment):
                    y += increment
            elif direction == "left":
                if border_check(x, "x", "left", increment):
                    x -= increment
            elif direction == "right":
                if border_check(x, "x", "right", increment):
                    x += increment

            # Update player position
            players[player_id]["position"] = (x, y)

        # spawn gatherable if needed
        while len(gatherables) < GATHERABLE_LIMIT:
            gatherable_change = True
            spawn_x, spawn_y = spawn_gatherable(increment)
            gatherable_counter = 0
            if len(gatherables) > 0:
                gatherable_counter = max([int(key) for key in gatherables.keys()])
            gatherable_id = gatherable_counter + 1
            logger.debug(f"Gatherable spawned at: {spawn_x, spawn_y} with ID: {gatherable_id}")
            gatherables[str(gatherable_id)] = (spawn_x, spawn_y)

        if gatherable_kill_check():
            score_change = True
        # print(len(gatherables))

        gamestate_clock = gamestate_clock + 1

        # Always send at least these
        gamestate_dict = {
            "clock": gamestate_clock,
            "players": players,
        }

        # Update gatherable location to all clients
        if gatherable_change or new_player_joined:
            gamestate_dict["gatherables"] = gatherables
            gatherable_change = False
            new_player_joined = False

        # Update scoreboard when change happens
        if score_change:
            print(scoreboard)
            gamestate_dict["scoreboard"] = scoreboard
            score_change = False

        # Update positions to all clients
        send_to_clients(gamestate_dict)


# Spawns gatherable objective
def spawn_gatherable(increment):
    tries = 0
    while True and tries < 1000:
        x_pos = (
            random.randint(int(X_MIN / increment), int(X_MAX / increment)) * increment
        )
        y_pos = (
            random.randint(int(Y_MIN / increment), int(Y_MAX / increment)) * increment
        )
        if not player_pos_check(x_pos, y_pos):
            return (x_pos, y_pos)
        tries = tries + 1
    return (x_pos, y_pos)


# gatherable collision check for all players
def gatherable_kill_check():
    for player_id, player_data in players.items():
        for key in gatherables:
            gatherable_x = gatherables[key][0]
            gatherable_y = gatherables[key][1]
            # print(gatherable_x, gatherable_y)
            x, y = player_data["position"]
            if check_collision(x, y, gatherable_x, gatherable_y):
                kill_gatherable(player_id, key)
                # print(player_id)
                return True
    else:
        return False


# check if player collides on object based on coordinates
def check_collision(player_x, player_y, object_x, object_y):
    if player_x == object_x and player_y == object_y:
        return True
    else:
        return False


# despawn gatherable, gives points, check if player has enough to win
def kill_gatherable(player_id, key):
    players[player_id]["points"] += 1
    scoreboard[player_id]["points"] += 1
    del gatherables[key]
    print(f"I am slain by player {str(player_id)}, summon another gatherable!")
    if players[player_id]["points"] >= POINT_LIMIT:
        round_reset(player_id)


# when a player has enough points it wins the round and points are reset
def round_reset(player_id):
    players[player_id]["games_won"] += 1
    scoreboard[player_id]["games_won"] += 1
    print(f"Player {str(player_id)} wins the round!")
    # handle scores saved to player table
    for player_id, player_data in players.items():
        player_data["points"] = 0
    # handle scoreboard
    for player_id, player_data in scoreboard.items():
        player_data["points"] = 0


# return True if there is player cube in this location
def player_pos_check(x_pos, y_pos):
    check_list = []
    for player_id, player_data in players.items():
        x, y = player_data["position"]
        check_list.append((x, y))
    if (x_pos, y_pos) in check_list:
        return True
    else:
        return False


# Check if player moving out of bounds
def border_check(coord, type, direction, increment):
    if type == "x" and direction == "left":
        if coord - increment >= X_MIN:
            return True
        else:
            return False
    if type == "x" and direction == "right":
        if coord + increment <= X_MAX:
            return True
        else:
            return False
    if type == "y" and direction == "down":
        if coord + increment <= Y_MAX:
            return True
        else:
            return False
    if type == "y" and direction == "up":
        if coord - increment >= Y_MIN:
            return True
        else:
            return False


def start_server_thread() -> Thread:
    """Starts the server thread, which only executes when this node is elected leader."""
    server_thread = Thread(target=update_positions, daemon=True)
    server_thread.start()
    return server_thread
