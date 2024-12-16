# Distributed-project-24

A project for Distributed Systems 2024. This project implements a multiplayer peer-to-peer game with Pygame where a host is dynamically chosen to function as the server.

The only required dependency is pygame, which means the client can be started with:

```bash
pip install pygame
python client.py
```

The client begins by listerning for UDP broadcasts on all interfaces and by listening for peer connections on a TCP socket. These two ways are used to establish connections to new peers. The client will respond to broadcasts by establishing a connection to the sending peer, but only if their ID is larger than the host's ID. In the opposite case, the connection will be established when the lower ID peer initiates the connection.

Simultanouesly, the client also starts broadcasting its own UUID to any possible peers on the local network. Each client generates a UUID for itself using Python's `uuid` module. The UUID is used by the bully leader negotiation process. Upon receiving a connection from another peer, the client requests the peer's UUID.

The broadcast socket, peer connection listener, and any peer connections bind to a specific IP address that is acquired based on where the default gateway of the host routes the connection. This will in most cases acquire a socket to the local network. After a short peer discovery period, the client starts running the bully algorithm by sending itself a bully `ELECTION` message. This procedure is also re-executed if the current server crashes later.

- Upon receiving an `ELECTION` message, the client responds with an `OK` if the sender's node is smaller than the client's node, and regardless of the ID it sends an `ELECTION` message to all peers that have a higher ID.
- Upon receiving an `OK` message, the client starts waiting for a `COORDINATOR` message as the `OK` means there is a higher ID node.
- Upon receiving a `COORDINATOR` message, the client starts treating the sender as a server host.
- If the client doesn't receive an `OK` message or a `COORDINATOR` message after waiting, it times out and either sets itself as the coordinator, if it was still waiting for an `OK`, or starts a new election, if it was waiting for a `COORDINATOR` message.

The application's TCP messaging uses a simple protocol, which attaches a length header to each sent message to indicate when the message ends. This is used for both the bully algorithm and the client-server game communication. The game server communication uses JSON. The client, bully algorithm, and the server threads do not themselves send/receive data but read data from their respective incoming message queues. Incoming messages are put to the queue by separate threads each handling one connection to a peer. Similarly, outgoing messages are put into an outgoing message queue, where a separate sender thread reads them and sends them to the recipient.

The JSON objects sent by the server may contain the following keys:

- `sync_gamestate`, which contains the server's logical clock and asks for clients to relay any possible newer game states to the server. This would be the only value sent in the message when the server host changes.
- `clock`, containing the server's current logical clock value.
- `players`, containing the player positions.
- `gatherables`, containing the goal object positions.
- `scoreboard`, containing the player scores.

On every server tick, the server will send the `clock`, and `players` values, but the `gatherables` and `scoreboard` values are only set when they are updated. The client communicates back to the server by sending movement directions with JSON, and may also relay the full game state back as an answer to `sync_gamestate`.

State is shared between the client and server, as movement commands only point out the direction the player is moving towards. Synchronization and consistency are enabled via logical clocks, which are used for deciding what the newest game state is. There is no explicit need for a consensus as the server host handles all game logic, but when it crashes, the logical clock helps restore the correct game state. Node discovery is implemented via broadcasting in the local network, which is used to gather the list for appointing a leader. The game has fault tolerance in the form of choosing a new leader whenever the current server host crashes. There is no specific mechanism in the current implementation for improved scalability as only one node can act as the server at a time, and it doesn't make sense for a single game to have too many players due to game board size.
