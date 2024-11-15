import socket
import threading
import json
import time
from typing import TypedDict

# Server configurations
HOST = input("server IP to bind to:")
PORT = 12345


# Game state and connected clients
class PosStatus(TypedDict):
    last_direction: str
    position: tuple[int, int]


players: dict[
    int, PosStatus
] = {}  # Stores each player's last direction and current position {player_id: {'last_direction': direction, 'position': (x, y)}}
clients: list[
    tuple[socket.socket, int]
] = []  # List to keep track of connected clients (client_socket, player_id)


# Send a message to all connected clients
def broadcast(message, exclude_client=None):
    # message delimiter
    message += "\n"
    for client, addr in clients:
        if client != exclude_client:  # Exclude the client that sent the message
            try:
                client.sendall(message.encode())
            except BrokenPipeError:
                print(f"Lost connection to {addr}. Removing from clients.")
                clients.remove((client, addr))


# Handle each client connection
def handle_client(client_socket):
    # Assign a new player ID to the client
    player_id = len(players) + 1
    clients.append((client_socket, player_id))  # Add the client to the list
    players[player_id] = {
        "position": (0, 0),
        "last_direction": None,
    }  # Initialize player position and last direction
    print(f"Player {player_id} connected.")

    # Send player_id to the client
    client_socket.sendall(json.dumps({"player_id": player_id}).encode())

    # Send the initial list of players to the client
    broadcast(json.dumps({"players": players}), exclude_client=client_socket)

    try:
        while True:
            data = client_socket.recv(1024).decode()
            if not data:
                break

            commands = data.splitlines()
            for command in commands:
                # Process movement commands
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
                        print(players)  # Print the dict for test purposes
                        broadcast(json.dumps({"players": players}))
    except ConnectionResetError:
        print(f"Player {player_id} disconnected.")

    finally:
        # Cleanup on client disconnect
        del players[player_id]
        clients.remove((client_socket, player_id))
        client_socket.close()
        print(f"Player {player_id} connection closed.")
        # Broadcast updated player list to remaining clients
        broadcast(json.dumps({"players": players}))


# Server's game loop for handling movements every second
def update_positions():
    while True:
        time.sleep(1)  # Move players every 1 second

        # Update each player's position based on their last command
        for player_id, player_data in players.items():
            x, y = player_data["position"]
            direction = player_data["last_direction"]

            # Move the player based on the last direction
            if direction == "up":
                y -= 10
            elif direction == "down":
                y += 10
            elif direction == "left":
                x -= 10
            elif direction == "right":
                x += 10

            # Update player position
            players[player_id]["position"] = (x, y)

        # Broadcast updated positions to all clients
        broadcast(json.dumps({"players": players}))


# Main server function
def start_server():
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
    start_server()
