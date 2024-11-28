from queue import Queue
import socket
import json
from threading import Thread
from typing import Literal
import pygame  # Library for creating graphical interface
import time
from server import Connection

known_peers = set() # For discovered peers/nodes

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

        #draw target, in progress
        #draw_target(300,200)

    pygame.display.flip()  # Update the display

def draw_target(x_pos, y_pos):
    pygame.draw.rect(screen, TARGET_COLOR, (x_pos, y_pos, 20, 20))


def poll_and_act_update(in_queue: Queue[str]):
    if in_queue.empty():
        return
    data = in_queue.get()
    try:
        update = json.loads(data)
    except json.JSONDecodeError as e:
        print(f"received malformed data: {data}")
        raise e

    print("got update", update)
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
def send_move(out_queue: Queue[str], direction: Literal["up", "down", "left", "right"]):
    print(
        f"player id: {player_id}, direction: {direction}"
    )  # Print some player data for test purposes
    if player_id is not None:  # Ensure player_id is set
        print("putting")
        move_command = {"move": direction, "player_id": player_id}
        try:
            message = json.dumps(move_command)
            out_queue.put(message)
            
        except (json.JSONDecodeError) as e:
            print("Disconnected from the server.")
            raise e
        

def thread_handler(sock: socket.socket, in_queue: Queue[str], out_queue: Queue[str]):
    # TODO: handle crashing. This does not propagate errors to the main thread
    conn = Connection(sock)
    while True:
        # TODO: should probably be more asynchronous. currently receiving and sending alternate
        # as sockets aren't thread safe and it'd require more complex nonblocking logic to be more async
        if not out_queue.empty():
            conn.send_message(out_queue.get())
        in_queue.put(conn.receive_message())

def broadcast_ip():
    try:
        # Create a UDP socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        # Enable broadcast mode
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        # Get the local IP address
        hostname = socket.gethostname()           # On cs.helsinki VMs this gets svm-11 as the hostname instead of svm-11-2 or 11-3.
        local_ip = socket.gethostbyname(hostname) # The 'fix' is to replace local_ip with the svm-11-2 or 11-3 ip addresses manually.

        broadcast_address = ('<broadcast>', 50000)  # Use port 50000 for broadcasting

        game_id = "asdf"  # ID to send with the IP. TODO: come up with a better id.
        
        print(f"Broadcasting IP and ID: {local_ip}, {game_id}")
        while True:
            # Send the IP address and ID as a broadcast message
            message = f"{local_ip},{game_id}".encode('utf-8')
            sock.sendto(message, broadcast_address)
            time.sleep(5)  # Broadcast every 5 seconds

    except Exception as e:
        print(f"Error in broadcasting: {e}")

def listen_for_broadcasts():
    try:
        # Create a UDP socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Bind the socket to listen on all interfaces and port 50000
        sock.bind(("", 50000))

        print("Listening for broadcasts on port 50000...")

        while True:
            # Receive data and address from the sender
            data, addr = sock.recvfrom(1024)  # Buffer size is 1024 bytes
            message = data.decode('utf-8')
            sender_ip, sender_id = message.split(',')
            
            if sender_ip not in known_peers and sender_id == 'asdf':
                print(f"Received broadcast from: IP={sender_ip}, ID={sender_id}")
                known_peers.add(sender_ip)
                
            else:
                pass
           
            print(known_peers) # TODO: Remove this after testing
                  
    except Exception as e:
        print(f"Error in listening: {e}")


# Main client function with pygame loop
def start_client():
    
    broadcast_thread = Thread(target=broadcast_ip, daemon=True)
    listen_thread = Thread(target=listen_for_broadcasts, daemon=True)

    print("Starting both broadcasting and listening...")
    broadcast_thread.start()
    listen_thread.start()
    
    client_socket = socket.socket()
    client_socket.connect((HOST, PORT))

    # we use a connection thread to avoid having to deal
    # with the complexity of nonblocking sockets
    in_queue = Queue()
    out_queue = Queue()
    conn_thread = Thread(target=thread_handler, args=(client_socket, in_queue, out_queue))
    conn_thread.start()
    
    # Main game loop
    global player_id
    running = True
    previous_key = None
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

        poll_and_act_update(in_queue)

        # Wait for the server to send the player_id
        if player_id is None:
            time.sleep(0.1)
            continue

        # Handle arrow key input for movement 
        # Ignores input if previous_key is same as current input       
        keys = pygame.key.get_pressed()
        if keys[pygame.K_UP] and previous_key != keys[pygame.K_UP]:
            print("up")
            send_move(out_queue, "up")
            previous_key = keys[pygame.K_UP]
        elif keys[pygame.K_DOWN] and previous_key != [pygame.K_DOWN]:
            send_move(out_queue, "down")
            previous_key = [pygame.K_DOWN]
        elif keys[pygame.K_LEFT] and previous_key != [pygame.K_LEFT]:
            send_move(out_queue, "left")
            previous_key = [pygame.K_LEFT]
        elif keys[pygame.K_RIGHT] and previous_key != [pygame.K_RIGHT]:
            send_move(out_queue, "right")
            previous_key = [pygame.K_RIGHT]
        else:
            pass
        
        # Now game does not call the function send_move() if previous_key is same as current input       
        
    # Clean up
    pygame.quit()


if __name__ == "__main__":

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
    screen = pygame.display.set_mode((WIDTH, HEIGHT), vsync=1)
    pygame.display.set_caption("Multiplayer Game")

    # Colors for players
    PLAYER_COLOR = (0, 128, 255)  # Blue
    OTHER_PLAYER_COLOR = (128, 128, 128)  # Gray
    TARGET_COLOR = (255, 0, 0) # Red
    start_client()
