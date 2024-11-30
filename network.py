import socket
import struct
from threading import Thread, RLock
import time
from logger import get_logger, logging
import sys
import uuid

class Peers:
    """A class for accessing known peers in a threadsafe way."""

    def __init__(self):
        self._peers = dict()
        self._lock = RLock()
    
    def __contains__(self, id):
        with self._lock:
            return id in self._peers
    
    def __getitem__(self, id):
        with self._lock:
            return self._peers[id].copy()
        
    def __setitem__(self, id, ip):
        with self._lock:
            self._peers[id] = ip, time.time()
    
    def __delitem__(self, id):
        with self._lock:
            del self._peers[id]

    def __str__(self):
        with self._lock:
            return str(self._peers)
    
    def remove_stale_nodes(self, timeout = 30):
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

known_peers = Peers() # For discovered peers/nodes
node_id = uuid.uuid1() # Generate a new unique node identifier
logger = get_logger('network', logging.DEBUG)

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
                logger.error(f"Frame contained malformed unicode: {self.buffer_in}")
                raise e


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
        node_id_str = str(node_id)

        logger.info(f"Broadcasting IP, Node_ID, Game_ID: {local_ip}, {node_id_str}, {game_id}")
        while True:
            # Send the IP address and ID as a broadcast message
            message = f"{local_ip},{node_id_str},{game_id}".encode('utf-8')
            sock.sendto(message, broadcast_address)
            time.sleep(5)  # Broadcast every 5 seconds

    except Exception as e:
        logger.error(f"Error in broadcasting: {e}")

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
            message = data.decode('utf-8')
            sender_ip, sender_id_str, game_id = message.split(',')
            sender_id = uuid.UUID(sender_id_str)
            
            if game_id == 'asdf':
                if sender_id not in known_peers:
                    # This id was not found in known_peers
                    logger.info(f"Received broadcast from: IP={sender_ip}, ID={sender_id_str}")
                known_peers[sender_id] = sender_ip # This updates the timestamp for sender_id
                
            else:
                pass
            
            logger.debug(f"Known peers: {known_peers}")
                  
    except Exception as e:
        logger.error(f"Error in listening: {e}")


def start_broadcast_thread() -> Thread:
    """Starts and returns the LAN broadcast thread used to send host discovery messages."""
    broadcast_thread = Thread(target=broadcast_ip, daemon=True)
    broadcast_thread.start()
    logger.info("Starting broadcasting")
    return broadcast_thread

def start_broadcast_listening_thread() -> Thread:
    """Starts and returns the LAN broadcast listening thread."""
    listening_thread = Thread(target=listen_for_broadcasts, daemon=True)
    listening_thread.start()
    logger.info("Starting broadcast listening")
    return listening_thread

if __name__ == "__main__":
    # Used only to test the abilities of this module
    cmdline_args = set(sys.argv[1:])

    if 'broadcast' in cmdline_args:
        # Only broadcast, for testing/debugging
        start_broadcast_thread()
        start_broadcast_listening_thread().join()
    elif 'bully' in cmdline_args:
        # Test/debug bully algorithm
        pass