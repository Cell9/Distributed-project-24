import socket
import struct
import threading
import json
import time
import random
from typing import TypedDict

# Game state and connected clients
class PosStatus(TypedDict):
    last_direction: str
    position: tuple[int, int]
    points: int
    games_won: int

class Connection:
    "Wrapper for sockets to make sending full messages instead of streams easier"
    sock: socket.socket
    data_counter: int
    buffer_in: bytearray
    def __init__(self, sock):
        self.sock = sock
        self.data_counter = 0
        self.buffer_in = bytearray()

    def send_message(self, msg: str):
        # encode header, which is 4 bytes and indicates data length
        header = struct.pack("!L", len(msg))
        # encode message
        data = msg.encode()

        frame = header + data

        self.sock.sendall(frame)
        # message print for testing purposes
        #print(f"sent message: {msg}")

    def receive_message(self) -> str:
        # first we need to receive header for length information
        while len(self.buffer_in) < 4 and self.data_counter == 0:
            # print for testing purposes
            #print(self.buffer_in, self.data_counter)
            self.buffer_in.extend(self.sock.recv(4 - len(self.buffer_in)))
            # we have full header
            if len(self.buffer_in) == 4:
                    self.data_counter = struct.unpack("!L", self.buffer_in)[0]
                    # clear buffer for actual message
                    self.buffer_in.clear()

        # receive actual message
        while True:
            # print for testing purposes
            #print(self.data_counter)
            data = self.sock.recv(self.data_counter)
            if not data:
                # connection is done and no more data will arrive
                raise ConnectionResetError()
            else:
                self.buffer_in.extend(data)
                self.data_counter -= len(data)
                assert self.data_counter >= 0
            
            # there is still more data to be received in this message
            # as we have not read length amount of bytes
            if self.data_counter != 0:
                continue

            try:
                message = self.buffer_in.decode()
                
                # reset state
                self.buffer_in.clear()
                self.data_counter = 0

                # print received message for testing purposes
                #print(f"received message: {message}")
                return message
            except UnicodeDecodeError as e:
                print(
                    f"Frame contained malformed unicode: {self.buffer_in}"
                )
                raise e

players: dict[
    int, PosStatus
] = {}  # Stores each player's last direction and current position {player_id: {'last_direction': direction, 'position': (x, y)}}
clients: list[
    tuple[Connection, int]
] = []  # List to keep track of connected clients (client_socket, player_id)
gatherables: dict[
    int, tuple # Stores information about gatherable objects
] = {}


# Send a message to all connected clients
def broadcast(message: str, exclude_client=None):
    for client, addr in clients:
        if client != exclude_client:  # Exclude the client that sent the message
            try:
                client.send_message(message)
            except BrokenPipeError:
                print(f"Lost connection to {addr}. Removing from clients.")
                clients.remove((client, addr))


# Handle each client connection
def handle_client(client_socket):
    # Assign a new player ID to the client
    player_id = len(players) + 1
    connection = Connection(client_socket)
    clients.append((connection, player_id))  # Add the client to the list
    players[player_id] = {
        "position": (0, 0),
        "last_direction": None,
        "points": 0,
        "games_won": 0
    }  # Initialize player position and last direction
    print(f"Player {player_id} connected.")

    # Send player_id to the client
    connection.send_message(json.dumps({"player_id": player_id}))

    # Send the initial list of players to the client
    broadcast(json.dumps({"players": players}), exclude_client=connection)

    try:
        while True:
            data = connection.receive_message()

            # Process movement command
            try:
                command = json.loads(data)
            except json.JSONDecodeError as e:
                print(
                    f"Player {player_id} sent malformed JSON: {data} and {command}"
                )
                raise e
            if "move" in command and "player_id" in command:
                # Verify the command is for the current player
                if command["player_id"] == player_id:
                    # Update the last move direction
                    players[player_id]["last_direction"] = command["move"]

                    # Broadcast updated positions to all clients
                    #print(players)  # Print the dict for test purposes
                    broadcast(json.dumps({"players": players}))
    except ConnectionResetError:
        print(f"Player {player_id} disconnected.")

    finally:
        # Cleanup on client disconnect
        del players[player_id]
        clients.remove((connection, player_id))
        client_socket.close()
        print(f"Player {player_id} connection closed.")
        # Broadcast updated player list to remaining clients
        broadcast(json.dumps({"players": players}))


# Server's game loop for handling movements every second
def update_positions():
    gatherable_counter = 0
    while True:
        increment = 10
        time.sleep(1/5)  # Move players every 1 second

        # Update each player's position based on their last command
        for player_id, player_data in players.items():
            x, y = player_data["position"]
            direction = player_data["last_direction"]

            # Move the player based on the last direction
            if direction == "up":
                if border_check(y,"y", "up", increment):
                    y -= increment
            elif direction == "down":
                if border_check(y,"y", "down", increment):
                    y += increment
            elif direction == "left":
                if border_check(x,"x", "left", increment):
                    x -= increment
            elif direction == "right":
                if border_check(x,"x", "right", increment):
                    x += increment

            # Update player position
            players[player_id]["position"] = (x, y)

        # spawn gatherable if needed (only 1 gatherable supported at the moment)
        if len(gatherables) < GATHERABLE_LIMIT:
            spawn_x, spawn_y = spawn_gatherable(increment)
            print(f"Gatherable spawned at: {spawn_x, spawn_y}")
            #print(len(gatherables))
            gatherable_counter = gatherable_counter + 1
            gatherable_id = str(gatherable_counter + 1)
            gatherables[gatherable_id] = (spawn_x, spawn_y)
        
        gatherable_kill_check(spawn_x, spawn_y)
        #print(len(gatherables))
        
        # Broadcast updated positions to all clients
        broadcast(json.dumps({"players": players}))

        # Broadcast gatherable location to all clients
        #print(gatherables)
        broadcast(json.dumps({"gatherables": gatherables}))

# Spawns gatherable objective
def spawn_gatherable(increment):
    tries = 0
    while True and tries < 1000:
        x_pos = random.randint(int(X_MIN/increment),int(X_MAX/increment))*increment
        y_pos = random.randint(int(Y_MIN/increment),int(Y_MAX/increment))*increment
        if not player_pos_check(x_pos, y_pos):
            return (x_pos, y_pos)
        tries = tries + 1
    return (x_pos, y_pos)

# gatherable collision check for all players
def gatherable_kill_check(gatherable_x, gatherable_y):
    for player_id, player_data in players.items():
        for key in gatherables:
            gatherable_x = gatherables[key][0]
            gatherable_y = gatherables[key][1]
            #print(gatherable_x, gatherable_y)
            x, y = player_data["position"]
            if check_collision(x,y,gatherable_x, gatherable_y):
                kill_gatherable(player_id, key)
                #print(player_id)
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
    players[player_id]['points'] += 1
    del gatherables[key]
    print(f"I am slain by player {str(player_id)}, summon another gatherable!")
    if players[player_id]['points'] >= POINT_LIMIT:
        round_reset(player_id)

# when a player has enough points it wins the round and points are reset
def round_reset(player_id):
    players[player_id]['games_won'] += 1
    print(f"Player {str(player_id)} wins the round!")
    for player_id, player_data in players.items():
        player_data["points"] = 0


# return True if there is player cube in this location
def player_pos_check(x_pos, y_pos):
    check_list = []
    for player_id, player_data in players.items():
        x, y = player_data["position"]
        check_list.append((x,y))
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
    if type == "y"  and direction == "up":
        if coord - increment >= Y_MIN:
            return True
        else:
            return False

# Main server function
def start_server():
    # Server configurations
    HOST = input("server IP to bind to:")
    PORT = 12345

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.bind((HOST, PORT))
    server_socket.listen()
    print(f"Server started on {HOST}:{PORT}")

    # Start the game loop in a separate thread
    threading.Thread(target=update_positions, daemon=True).start()

    while True:
        client_socket, addr = server_socket.accept()
        print(f"Connection from {addr}")

        # Start a new thread for each connected client
        thread = threading.Thread(target=handle_client, args=(client_socket,))
        thread.start()


if __name__ == "__main__":
    # Coordinate destrictions (client's pygame draws 600x400)
    X_MIN, X_MAX, Y_MIN, Y_MAX = 0, 580, 0, 380
    POINT_LIMIT = 5
    GATHERABLE_LIMIT = 3
    start_server()
