import socket
import struct
from threading import Thread, RLock
import time
from logger import get_logger, logging
import sys
import uuid
import json
from queue import Queue
from os import getenv


class Peers:
    """A class for accessing known peers in a threadsafe way."""

    def __init__(self):
        self._peers = dict()
        self._lock = RLock()

    def _create_entry(self, ip, conn):
        """Creates a known peer dict entry, a dict containing ip, conn, and a timestamp."""
        return {"ip": ip, "ts": time.time(), "conn": conn}

    def __contains__(self, id):
        with self._lock:
            return id in self._peers

    def __getitem__(self, id):
        with self._lock:
            if id in self._peers:
                return self._peers[id].copy()
            raise KeyError(f"No peer found, {id}")

    def __setitem__(self, id, entry):
        with self._lock:
            self._peers[id] = entry

    def __delitem__(self, id):
        with self._lock:
            del self._peers[id]

    def __str__(self):
        with self._lock:
            return str(self._peers)

    def remove_stale_nodes(self, timeout=30):
        """Removes stale nodes that haven't been updated in over timeout seconds. Returns a list of removed node ids."""
        removed = []

        with self._lock:
            current_time = time.time()
            for id, (ip, timestamp) in self._peers.items():
                if current_time - timestamp > timeout:
                    removed.append(id)
            for id in removed:
                del self._peers[id]

        return removed

    def copy(self):
        """Returns a copy of known of peers."""
        with self._lock:
            return self._peers.copy()

    def update_timestamp(self, peer_id):
        """Updates the timestamp on peer_id."""
        with self._lock:
            self._peers[peer_id]["ts"] = time.time()

    def add(self, peer_id, peer_ip, peer_conn):
        """Add a new peer or update timestamp/conn."""
        with self._lock:
            if peer_id in self._peers:
                self.update_timestamp(peer_id)
            else:
                self._peers[peer_id] = self._create_entry(peer_ip, peer_conn)

    def remove(self, peer_id: uuid.UUID) -> uuid.UUID | None:
        """Tries to remove a peer from known peers, returns peer id or None if the peer wasn't found."""
        with self._lock:
            if peer_id in self._peers:
                del self._peers[peer_id]
                return peer_id
            return None


GAME_ID = "asdf"  # ID to send with the IP. TODO: come up with a better id.
known_peers = Peers()  # For discovered peers/nodes
node_id = uuid.uuid1()  # Generate a new unique node identifier
logger = get_logger("network", logging.DEBUG)
msg_in = Queue()
msg_out = Queue()


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
        # print(f"sent message: {msg}")

    def receive_message(self) -> str:
        # first we need to receive header for length information
        while len(self.buffer_in) < 4 and self.data_counter == 0:
            # print for testing purposes
            # print(self.buffer_in, self.data_counter)
            self.buffer_in.extend(self.sock.recv(4 - len(self.buffer_in)))
            # we have full header
            if len(self.buffer_in) == 4:
                self.data_counter = struct.unpack("!L", self.buffer_in)[0]
                # clear buffer for actual message
                self.buffer_in.clear()

        # receive actual message
        while True:
            # print for testing purposes
            # print(self.data_counter)
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
                # print(f"received message: {message}")
                return message
            except UnicodeDecodeError as e:
                logger.error(f"Frame contained malformed unicode: {self.buffer_in}")
                raise e


def get_local_ip():
    address = ""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.1.1.1", 1))  # Does not need to be reachable
        address = s.getsockname()[0]
    except Exception:
        address = "127.0.0.1"
    finally:
        s.close()

    return str(address)


def handshake_new_peer(conn) -> uuid.UUID | None:
    """Shake hands with new peer through Connection.
    Returns peer UUID or None if handshake wasn't successful."""
    conn.send_message(f"{GAME_ID},{node_id}")
    msg = conn.receive_message()
    msgs = msg.split(",")

    if len(msgs) != 2 and msgs[0] != GAME_ID:
        logger.warning(f"Nonconforming connection, received message {msg}")
        return None

    return uuid.UUID(msgs[1])


def handle_peer_recv(peer_id: uuid.UUID, conn: Connection):
    """Handle receiving messages from a given peer. The incoming messages should all be in JSON format."""
    logger.debug(f"Starting to receive messages from peer {peer_id}")
    try:
        while True:
            msg_json = conn.receive_message()
            try:
                msg = json.loads(msg_json)
                msg_in.put((peer_id, msg))  # Sender, msg tuple in the incoming queue
            except json.JSONDecodeError:
                logger.error(f"Peer {peer_id} sent malformed JSON: {msg_json}")
    except ConnectionResetError:
        logger.info(f"Peer {peer_id} disconnected")
        known_peers.remove(peer_id)  # Only remove the entry in the recv handler


def handle_peer_send():
    """Handle all data sending to peers using the msg_out queue. The outgoing messages get converted into JSON."""
    while True:
        # Get peer_id and the raw message from outgoing queue.
        peer_id, msg_raw = (
            msg_out.get()
        )  # This blocks until there is an item in the queue
        try:
            conn = known_peers[peer_id]["conn"]  # Get the connection to peer
            msg_json = json.dumps(msg_raw)
            conn.send_message(msg_json)
        except KeyError as err:
            logger.debug(err)
        except BrokenPipeError:
            logger.info(f"Lost connection to {peer_id}")


def listen_for_peer_connections():
    """Blocking listen for new peer connections from nodes with lower ID.
    One of two ways of creating a new peer entry in known peers."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(
        socket.SOL_SOCKET, socket.SO_REUSEPORT, 1
    )  # Don't create more ports
    local_ip = get_local_ip()
    sock.bind((local_ip, 43234))

    # This handles connection attempts coming in from nodes with lower node_id
    while True:
        sock.listen()
        peer_socket, peer_addr = sock.accept()
        conn = Connection(peer_socket)

        peer_id = handshake_new_peer(conn)

        if not peer_id:
            peer_socket.close()
            continue

        if peer_id > node_id:
            # The connecting node should be lower ID than this one
            logger.warning("Connection refused due to node id")
            peer_socket.close()
            continue

        peer_ip, _ = peer_addr
        known_peers.add(peer_id, peer_ip, conn)
        logger.info(f"New known peer added. ID:{peer_id}, IP:{peer_ip}")

        # Start a new thread for receiving messages from the new peer
        Thread(target=handle_peer_recv, args=(peer_id, conn), daemon=True).start()


def connect_and_add_new_peer(peer_id, peer_ip):
    """Tries to create a new Connection to a node with a higher node_id, and add it to the known peers entry.
    Function is blocking. This is the second way a new peer entry can be added to known peers."""
    if peer_id == node_id:
        # This is the same node, just add it as a peer w/o a connection.
        known_peers.add(node_id, peer_ip, None)
        return
    if peer_id < node_id:
        # Connection is made through listening in this case
        return

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(
        socket.SOL_SOCKET, socket.SO_REUSEPORT, 1
    )  # Don't create more ports
    local_ip = get_local_ip()
    sock.bind((local_ip, 43234))
    sock.connect((peer_ip, 43234))
    conn = Connection(sock)
    peer_id = handshake_new_peer(conn)

    if peer_id:
        known_peers.add(peer_id, peer_ip, conn)
        logger.info(f"New known peer added. ID:{peer_id}, IP:{peer_ip}")
        Thread(target=handle_peer_recv, args=(peer_id, conn), daemon=True).start()
    else:
        sock.close()


def broadcast_ip():
    try:
        # Create a UDP socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        # Enable broadcast mode
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        # Get the local IP address
        local_ip = getenv("GAME_IP") or get_local_ip()
        broadcast_address = ("<broadcast>", 50000)  # Use port 50000 for broadcasting

        node_id_str = str(node_id)

        logger.info(
            f"Broadcasting IP, Node_ID, Game_ID: {local_ip}, {node_id_str}, {GAME_ID}"
        )
        while True:
            # Send the IP address and ID as a broadcast message
            message = f"{local_ip},{node_id_str},{GAME_ID}".encode("utf-8")
            sock.sendto(message, broadcast_address)
            time.sleep(5)  # Broadcast every 5 seconds

    except Exception as e:
        logger.error(f"Error in broadcasting: {e}")
        raise e


def listen_for_broadcasts():
    try:
        # Create a UDP socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Bind the socket to listen on all interfaces and port 50000
        sock.bind(("", 50000))

        logger.info("Listening on port 50000...")

        while True:
            # Receive data and address from the sender
            data, addr = sock.recvfrom(1024)  # Buffer size is 1024 bytes
            message = data.decode("utf-8")
            sender_ip, sender_id_str, game_id = message.split(",")
            sender_id = uuid.UUID(sender_id_str)

            if game_id == GAME_ID:
                if sender_id not in known_peers:
                    # This id was not found in known_peers
                    logger.info(
                        f"Received broadcast from: IP={sender_ip}, ID={sender_id_str}"
                    )
                    Thread(
                        target=connect_and_add_new_peer,
                        args=(sender_id, sender_ip),
                        daemon=True,
                    ).start()
                else:
                    known_peers.update_timestamp(sender_id)

            else:
                pass

            # logger.debug(f"Known peers: {known_peers}")
    except Exception as e:
        logger.error(f"Error in listening: {e}")


def send_to_all(data, exclude_peer=None):
    """Send a data to all peers, except exlude_peer. Data is turned into JSON later."""
    peers = known_peers.copy()  # We'll deadlock if this isn't done
    for peer_id in peers.keys():
        if peer_id != exclude_peer and peer_id != node_id:
            msg_out.put((peer_id, data))


def bully():
    """Waits for peer list to populate and executes Bully algorithm. Returns coordinator boolean and server IP string"""
    time.sleep(10)

    # Initialize variables
    isParticipant = True
    isCoordinator = False
    waiting = False
    server_ip = ""
    k = known_peers.copy()
    uuid_list = list()

    # Generate a list of UUIDs from known_peers and discard your own.
    for key in k.keys():
        if node_id != key:
            uuid_list.append((key))
        else:
            pass
    print(f"MY UUID: {node_id}")
    print(f"MY VARIABLE: {node_id.clock_seq_hi_variant}")

    for i in uuid_list:
        try:
            if node_id.clock_seq_hi_variant < i.clock_seq_hi_variant:
                x = i, "ELECTION"
                msg_out.put(x)
                # logger.debug(f"variables are node: {node_id.clock_seq_hi_variant} and i: {i.clock_seq_hi_variant}")
            else:
                pass
        except Exception as e:
            logger.error(f"Error in initial propagation: {e}")

    # Election process. OK to elections. Wait in loop for COORDINATOR. Break loop upon COORDINATOR and use message UUID to select sender IP-Address.
    while isParticipant or waiting:
        try:
            m = msg_in.get(timeout=3)
            logger.debug(f"Current incoming message type: {m[1]}")
            if m[1] == "OK" or waiting:
                waiting = True
                isParticipant = False
                time.sleep(5)
            if m[1] == "ELECTION" and isParticipant:
                x = m[0], "OK"
                msg_out.put(x)
            if m[1] == "COORDINATOR":
                server_ip = known_peers[m[0]]["ip"]
                break
        # COORDINATOR is sent by the last non-waiting participant upon msg_in queue being empty for 3 seconds as it causes an Exception.
        except Exception:
            if not waiting:
                for i in uuid_list:
                    x = i, "COORDINATOR"
                    msg_out.put(x)
                isParticipant = False
                isCoordinator = True
                server_ip = get_local_ip()
                break
            else:
                break
    # Return coordinator status as boolean and the server_ip to be used for connecting to server.
    return isCoordinator, server_ip


def start_broadcast_thread() -> Thread:
    """Starts and returns the LAN broadcast thread used to send host discovery messages."""
    logger.info("Starting broadcasting")
    broadcast_thread = Thread(target=broadcast_ip, daemon=True)
    broadcast_thread.start()
    return broadcast_thread


def start_broadcast_listening_thread() -> Thread:
    """Starts and returns the LAN broadcast listening thread."""
    logger.info("Starting broadcast listening")
    listening_thread = Thread(target=listen_for_broadcasts, daemon=True)
    listening_thread.start()
    return listening_thread


def start_peer_listening_thread() -> Thread:
    """Starts listening for new incoming peer connections."""
    logger.info("Starting peer connection listening")
    peer_listening_thread = Thread(target=listen_for_peer_connections, daemon=True)
    peer_listening_thread.start()
    return peer_listening_thread


def start_peer_send_thread() -> Thread:
    """Starts the peer sending thread used to send outoing messages."""
    logger.info("Starting outgoing peer messaging")
    peer_sender_thread = Thread(target=handle_peer_send, daemon=True)
    peer_sender_thread.start()
    return peer_sender_thread


if __name__ == "__main__":
    # Used only to test the abilities of this module
    cmdline_args = set(sys.argv[1:])

    # print(get_local_ip())

    if "broadcast" in cmdline_args:
        # Only broadcast, for testing/debugging
        start_peer_listening_thread()
        start_peer_send_thread()
        start_broadcast_listening_thread()
        start_broadcast_thread()
        while True:
            time.sleep(3)
            send_to_all(f"Hello from node {node_id}")
            try:
                peer_id, msg = msg_in.get(block=False)
                logger.debug(f"Message received from {peer_id}: {msg}")
            except Exception:
                pass
    elif "bully" in cmdline_args:
        # Test/debug bully algorithm
        start_peer_listening_thread()
        start_peer_send_thread()
        start_broadcast_listening_thread()
        start_broadcast_thread()

        x, y = bully()

        print(x)

        print(y)
