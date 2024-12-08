# Distributed-project-24

A project for Distributed Systems 2024. This project implements a multiplayer peer-to-peer game with Pygame where a host is dynamically chosen to function as the server.

The only required dependency is pygame, which means the client can be started with:

```bash
pip install pygame
python client.py
```

The client begins by listerning for UDP broadcasts on all interfaces and by listening for peer connections on a TCP socket. These two ways are used to establish connections to new peers. The client will respond to broadcasts by establishing a connection to the sending peer, but only if their ID is larger than the host's ID. In the opposite case, the connection will be established when the lower ID peer initiates the connection.

Simultanouesly, the client also starts broadcasting its own UUID to any possible peers on the local network. Each client generates a UUID for itself, which is used by the bully leader negotiation process. Upon receiving a connection from another peer, the client requests the peer's UUID.

The broadcast socket, peer connection listener, and any peer connections bind to a specific IP address that is acquired based on where the default gateway of the host routes the connection. This will in most cases acquire a socket to the local network. If necessary, it is possible to launch the game with the environment variable `GAME_IP` set to a specific IP address to instead set the IP manually. For example it might be useful to set `GAME_IP=127.0.0.55` to match with peers running on the loopback interface for local testing.

After a short peer discovery period, the client starts running the bully algorithm by sending itself a bully `ELECTION` message. This procedure is also re-executed if the current server crashes later.

- Upon receiving an `ELECTION` message, the client responds with an `OK` if the sender's node is smaller than the client's node, and regardless of the ID it sends an `ELECTION` message to all peers that have a higher ID.
- Upon receiving an `OK` message, the client starts waiting for a `COORDINATOR` message as the `OK` means there is a higher ID node.
- Upon receiving a `COORDINATOR` message, the client starts treating the sender as a server host.
- If the client doesn't receive an `OK` message or a `COORDINATOR` message after waiting, it times out and either sets itself as the coordinator, if it was still waiting for an `OK`, or starts a new election, if it was waiting for a `COORDINATOR` message.

The application's TCP messaging uses a simple protocol, which attaches a length header to each sent message to indicate when the message ends. This is used for both the bully algorithm and the client-server game communication. The game server communication uses JSON.
