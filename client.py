from typing import Literal
import pygame  # Library for creating graphical interface
import time
from logger import get_logger, logging
from network import (
    start_broadcast_thread,
    start_broadcast_listening_thread,
    start_peer_listening_thread,
    start_peer_send_thread,
    start_bully_thread,
    node_id,
    client_send_to_server,
    poll_client_msg_queue,
    known_peers
)
from server import start_server_thread
from uuid import UUID

# Get the client logger, you can specify one even for a function as well
logger = get_logger("client", level=logging.DEBUG)


# Display the game positions
def display_positions():
    screen.fill((0, 0, 0))  # Clear screen with black background

    # print(str(positions.items()))  # Print dict for test purposes
    # Draw each player as a rectangle
    for pid, data in positions.items():
        # Check if this player is the local player
        position = data["position"]
        if pid == str(node_id):
            color = PLAYER_COLOR  # Local player color
        else:
            color = OTHER_PLAYER_COLOR  # Other players' color
        pygame.draw.rect(screen, color, (position[0], position[1], 20, 20))

    # Draw gatherables to the screen (currently only one is used)
    try:
        for item in gatherable_positions:
            gatherable_position = gatherable_positions[item]
            draw_target(gatherable_position[0], gatherable_position[1])
    except:
        # no gatherable data received yet
        pass

    pygame.display.flip()  # Update the display


def draw_target(x_pos, y_pos):
    pygame.draw.rect(screen, TARGET_COLOR, (x_pos, y_pos, 20, 20))


def scoreboardinfo():
    for pid, data in scoreboard.items():
        print(f"Player {pid}, points: {data['points']}, games won: {data['games_won']}")


def poll_and_act_update(leader_id):
    peer_id, update = poll_client_msg_queue()
    if not update or peer_id != leader_id:
        display_positions()
        return

    # Ensure these are treated as global variables
    global positions, gatherable_positions, scoreboard, gamestate_clock

    if "sync_gamestate" in update:
        logger.debug(f"Received sync gamestate request from server")
        if update["sync_gamestate"] < gamestate_clock:
            logger.debug(f"Sent newer gamestate back to server")
            client_send_to_server({
                "sync_gamestate": gamestate_clock,
                "players": positions,
                "gatherables": gatherable_positions,
                "scoreboard": scoreboard,
            })

    if "clock" in update:
        gamestate_clock = update["clock"]

    # Update player positions when received
    if "players" in update:
        positions = update["players"]

    # Update gatherable position when received
    if "gatherables" in update:
        gatherable_positions = update["gatherables"]

    # Update scoreboard when received and print info
    if "scoreboard" in update:
        scoreboard = update["scoreboard"]
        scoreboardinfo()

    # Update the display
    display_positions()


# Send movement commands to the server via queue
def send_move(direction: Literal["up", "down", "left", "right"]):
    move_command = {"move": direction, "player_id": str(node_id)}
    client_send_to_server(move_command)


def check_leader(current_leader: UUID, previous_key) -> UUID:
    """Checks if the leader exists."""
    while True:
        new_leader = known_peers.get_leader()
        if new_leader is None:
            time.sleep(0.1)
            continue
        return new_leader

# Main client function with pygame loop
def start_client():
    start_peer_listening_thread()
    start_peer_send_thread()
    start_broadcast_listening_thread()
    start_broadcast_thread()
    start_bully_thread()
    start_server_thread()

    # Main game loop
    running = True
    previous_key = None
    current_leader = check_leader(None, previous_key)
    pygame_clock = pygame.time.Clock()

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

        current_leader = check_leader(current_leader, previous_key)
        poll_and_act_update(current_leader)

        # Handle arrow key input for movement
        # Ignores input if previous_key is same as current input
        keys = pygame.key.get_pressed()
        if keys[pygame.K_UP] and previous_key != keys[pygame.K_UP]:
            send_move("up")
            previous_key = keys[pygame.K_UP]
        elif keys[pygame.K_DOWN] and previous_key != [pygame.K_DOWN]:
            send_move("down")
            previous_key = [pygame.K_DOWN]
        elif keys[pygame.K_LEFT] and previous_key != [pygame.K_LEFT]:
            send_move("left")
            previous_key = [pygame.K_LEFT]
        elif keys[pygame.K_RIGHT] and previous_key != [pygame.K_RIGHT]:
            send_move("right")
            previous_key = [pygame.K_RIGHT]
        
        # Cap framerate to 60 fps
        pygame_clock.tick(60)

    # Clean up
    pygame.quit()


if __name__ == "__main__":
    # Start the client

    # Server connection configuration
    # HOST = input("server ip to connect to:")
    # HOST = 'server ip here'
    PORT = 12345

    # Game state
    Position = tuple[int, int]
    positions: dict[
        str, Position
    ] = {}  # Dictionary to keep track of player positions locally
    # player_id: None | int = None  # Unique identifier for the client
    gamestate_clock: int = 0
    scoreboard = {}

    # Initialize pygame
    pygame.init()
    WIDTH, HEIGHT = 600, 400
    screen = pygame.display.set_mode((WIDTH, HEIGHT), vsync=1)
    pygame.display.set_caption("Multiplayer Game")

    # Colors for players
    PLAYER_COLOR = (0, 128, 255)  # Blue
    OTHER_PLAYER_COLOR = (128, 128, 128)  # Gray
    TARGET_COLOR = (255, 0, 0)  # Red
    start_client()
