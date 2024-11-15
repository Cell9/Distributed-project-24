import socket
import json
import pygame  # Library for creating graphical interface
import time

# Server connection configuration
HOST = input("server ip to connect to:")
# HOST = 'server ip here'
PORT = 12345


# Game state
Position = tuple[int, int]
positions: dict[
    int, Position
] = {}  # Dictionary to keep track of player positions locally
player_id: None | int = None  # Unique identifier for the client

# Initialize pygame
pygame.init()
WIDTH, HEIGHT = 600, 400
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Multiplayer Game")

# Colors for players
PLAYER_COLOR = (0, 128, 255)  # Blue
OTHER_PLAYER_COLOR = (128, 128, 128)  # Gray


# Display the game positions
def display_positions():
    screen.fill((0, 0, 0))  # Clear screen with black background

    print(str(positions.items()))  # Print dict for test purposes
    # Draw each player as a rectangle
    for pid, data in positions.items():
        print(
            "pid: " + str(pid) + ", " + "player_id: " + str(player_id)
        )  # Print some player data for test purposes
        # Check if this player is the local player
        position = data["position"]
        if str(pid) == str(player_id):
            color = PLAYER_COLOR  # Local player color
        else:
            color = OTHER_PLAYER_COLOR  # Other players' color
        pygame.draw.rect(screen, color, (position[0], position[1], 20, 20))

    pygame.display.flip()  # Update the display


def poll_and_act_update(client_socket: socket.socket):
    try:
        data = client_socket.recv(1024).decode()
    # no new data available
    except BlockingIOError:
        return
    if not data:
        # no data indicates disconnection
        print("server connection has disconnected")
        # TODO: handle this?
        exit(1)
    try:
        # multiple updates may be received at once,
        # and the server adds \n to end of each message
        # so we can read line by line
        updates = [json.loads(line) for line in data.splitlines()]
    except json.JSONDecodeError as e:
        print(f"received malformed data: {data}")
        raise e

    for update in updates:
        # Ensure these are treated as global variables
        global positions, player_id

        # Set player ID when first received from server
        if "player_id" in update and player_id is None:
            player_id = update["player_id"]

        # Update player positions when received
        if "players" in update:
            positions = update["players"]

    # Update the display
    display_positions()


# Send movement commands to the server via queue
def send_move(client_socket: socket.socket, direction):
    print(
        f"player id: {player_id}, direction: {direction}"
    )  # Print some player data for test purposes
    if player_id is not None:  # Ensure player_id is set
        print("putting")
        move_command = {"move": direction, "player_id": player_id}
        try:
            # no timeout specified, this will block
            message = json.dumps(move_command) + "\n"
            print("sending")
            client_socket.sendall(message.encode())
        except (ConnectionResetError, json.JSONDecodeError) as e:
            print("Disconnected from the server.")
            raise e


# Main client function with pygame loop
def start_client():
    client_socket = socket.socket()
    client_socket.connect((HOST, PORT))
    client_socket.setblocking(False)

    # Main game loop
    global player_id
    running = True
    while running:
        # print("going")
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

        poll_and_act_update(client_socket)

        # Wait for the server to send the player_id
        if player_id is None:
            time.sleep(0.1)
            continue

        # Handle arrow key input for movement
        keys = pygame.key.get_pressed()
        if keys[pygame.K_UP]:
            send_move(client_socket, "up")
        elif keys[pygame.K_DOWN]:
            send_move(client_socket, "down")
        elif keys[pygame.K_LEFT]:
            send_move(client_socket, "left")
        elif keys[pygame.K_RIGHT]:
            send_move(client_socket, "right")
        # Small delay to avoid flooding the server
        # TODO: remove this and implement proper messaging
        # movement should probably be sent periodically instead of being sent once per frame
        time.sleep(1 / 30)
    # Clean up
    pygame.quit()


if __name__ == "__main__":
    start_client()
