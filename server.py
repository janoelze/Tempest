# Let's start by generating the core server with the following goals:
# - Support multiple rooms
# - Track connected users and which room they're in
# - Distribute messages to all clients in the same room
# - Maintain message history per room (in-memory for now)

import socket
import threading
import random
import time
import re
import html
import os
import signal
import subprocess
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

# Decorative Unicode avatar symbols (non-emoji)
ASCII_AVATARS = ['♠', '♣', '♥', '♦', '♪', '♫', '♯', '♭', '†', '‡', '§', '¶', '©', '®', '™',
                 '←', '→', '↑', '↓', '↔', '↕', '↖', '↗', '↘', '↙', '∞', '∆', '∇', '∑', '∏',
                 '√', '∴', '∵', '∀', '∃', '∈', '∋', '⊂', '⊃', '⊆', '⊇', '⊕', '⊗', '⊙', '⊥',
                 '☐', '☑', '☒', '☓', '☆', '★', '☽', '☾', '⚡', '⚐', '⚑', '⚒', '⚓', '⚔', '⚖']

# Security configuration
MAX_CLIENTS = 100
MAX_ROOMS = 50
MAX_NICKNAME_LENGTH = 30
MAX_ROOM_NAME_LENGTH = 50
MAX_MESSAGE_LENGTH = 500
MAX_MESSAGES_PER_ROOM = 100
CONNECTION_TIMEOUT = 60 * 60  # 1 hour

@dataclass
class ClientInfo:
    nickname: str
    room: Optional[str]
    avatar: str

class CommandHandler:
    def __init__(self, server_state):
        self.server_state = server_state
    
    def handle_connect(self, conn: socket.socket, args: str) -> Tuple[bool, str]:
        """Handle /connect command"""
        if not args.strip():
            return False, "Error: /connect requires a nickname\n"
        
        raw_nickname = args.strip()
        valid, result = validate_nickname(raw_nickname)
        if not valid:
            return False, f"Error: {result}\n"
        
        nickname = sanitize_input(result)
        
        # Check for duplicate nicknames
        existing_nicks = [client.nickname.lower() for client in self.server_state.clients.values() if conn != conn]
        if nickname.lower() in existing_nicks:
            return False, "Error: Nickname already in use\n"
        
        avatar = random.choice(ASCII_AVATARS)
        self.server_state.clients[conn] = ClientInfo(nickname, None, avatar)
        print(f"[CONNECT] Client connected as '{nickname}' with avatar [{avatar}]")
        
        return True, f"WELCOME {nickname} [{avatar}]\n"
    
    def handle_room(self, conn: socket.socket, args: str) -> Tuple[bool, str]:
        """Handle /room command"""
        if conn not in self.server_state.clients:
            return False, "You must /connect first.\n"
        
        if len(self.server_state.rooms) >= MAX_ROOMS:
            return False, f"Error: Server room limit reached ({MAX_ROOMS} rooms)\n"
        
        if not args.strip():
            return False, "Error: /room requires a room name\n"
        
        raw_room = args.strip()
        valid, result = validate_room_name(raw_room)
        if not valid:
            return False, f"Error: {result}\n"
        
        new_room = sanitize_input(result)
        client_info = self.server_state.clients[conn]
        
        # Leave current room
        if client_info.room and conn in self.server_state.rooms.get(client_info.room, []):
            self.server_state.rooms[client_info.room].remove(conn)
            if not self.server_state.rooms[client_info.room]:
                del self.server_state.rooms[client_info.room]
                if client_info.room in self.server_state.messages:
                    del self.server_state.messages[client_info.room]
        
        # Join new room
        client_info.room = new_room
        self.server_state.rooms.setdefault(new_room, []).append(conn)
        self.server_state.messages.setdefault(new_room, [])
        
        print(f"[ROOM] {client_info.nickname} [{client_info.avatar}] joined room '{new_room}'")
        return True, f"ENTERED {new_room}\n"
    
    def handle_who(self, conn: socket.socket) -> Tuple[bool, str]:
        """Handle /who command"""
        if conn not in self.server_state.clients:
            return False, "You must /connect first.\n"
        
        client_info = self.server_state.clients[conn]
        if not client_info.room:
            return False, "You must join a room first.\n"
        
        user_list = []
        for c in self.server_state.rooms.get(client_info.room, []):
            if c in self.server_state.clients:
                other_client = self.server_state.clients[c] 
                user_list.append(f"[{other_client.avatar}] {other_client.nickname}")
        
        print(f"[WHO] {client_info.nickname} requested user list for room '{client_info.room}': {user_list}")
        return True, f"USERS: {', '.join(user_list)}\n"
    
    def handle_help(self) -> Tuple[bool, str]:
        """Handle /help command"""
        help_text = """Available commands:
/connect <name> - Set your nickname and connect to the server
/room <name>    - Join or create a chat room
/who            - List users in your current room
/help           - Show this help message
/bye            - Disconnect from the server

After connecting and joining a room, simply type messages to chat!"""
        return True, f"{help_text}\n"
    
    def handle_bye(self, conn: socket.socket) -> Tuple[bool, str]:
        """Handle /bye command"""
        if conn in self.server_state.clients:
            client_info = self.server_state.clients[conn]
            print(f"[DISCONNECT] {client_info.nickname} [{client_info.avatar}] disconnected gracefully")
        return True, "GOODBYE\n"

class MessageProcessor:
    def __init__(self, server_state, command_handler):
        self.server_state = server_state
        self.command_handler = command_handler
    
    def process_line(self, conn: socket.socket, line: str, addr) -> bool:
        """Process a line of input from client. Returns True to continue, False to disconnect."""
        if len(line) > MAX_MESSAGE_LENGTH:
            try:
                conn.sendall(f"Error: Message too long (max {MAX_MESSAGE_LENGTH} characters)\n".encode())
            except:
                pass
            return True
        
        # Handle commands
        if line.startswith("/connect"):
            success, response = self.command_handler.handle_connect(conn, line[8:].strip())
            try:
                conn.sendall(response.encode())
            except:
                return False
            
            if success:
                # Send room list with users
                self._send_room_list(conn)
            return True
            
        elif line.startswith("/room"):
            success, response = self.command_handler.handle_room(conn, line[5:].strip())
            try:
                conn.sendall(response.encode())
            except:
                return False
            
            if success and conn in self.server_state.clients:
                client_info = self.server_state.clients[conn]
                # Send last 10 messages
                room_messages = self.server_state.messages.get(client_info.room, [])
                for msg in room_messages[-10:]:
                    try:
                        conn.sendall(f"{msg}\n".encode())
                    except:
                        return False
                # Broadcast join message
                broadcast(client_info.room, f"** [{client_info.avatar}] {client_info.nickname} has entered the room **")
            return True
            
        elif line.startswith("/who"):
            success, response = self.command_handler.handle_who(conn)
            try:
                conn.sendall(response.encode())
            except:
                return False
            return True
            
        elif line.startswith("/help"):
            success, response = self.command_handler.handle_help()
            try:
                conn.sendall(response.encode())
            except:
                return False
            return True
            
        elif line.startswith("/bye"):
            success, response = self.command_handler.handle_bye(conn)
            try:
                conn.sendall(response.encode())
            except:
                pass
            return False  # Disconnect
            
        elif line.startswith("/"):
            try:
                conn.sendall("Unknown command. Type /help for available commands.\n".encode())
            except:
                return False
            return True
            
        else:
            # Handle regular message
            return self._handle_regular_message(conn, line)
    
    def _send_room_list(self, conn: socket.socket):
        """Send list of active rooms to client"""
        room_info = []
        for room_name, room_clients in self.server_state.rooms.items():
            if room_clients:  # Only show rooms with users
                users = []
                for c in room_clients:
                    if c in self.server_state.clients:
                        client = self.server_state.clients[c]
                        users.append(f"[{client.avatar}] {client.nickname}")
                room_info.append(f"{room_name}: {', '.join(users)}")
        
        try:
            if room_info:
                conn.sendall("ROOMS:\n".encode())
                for info in room_info:
                    conn.sendall(f"  {info}\n".encode())
            else:
                conn.sendall("No active rooms. Use /room <name> to create one.\n".encode())
        except:
            pass
    
    def _handle_regular_message(self, conn: socket.socket, line: str) -> bool:
        """Handle regular chat message"""
        if conn not in self.server_state.clients:
            try:
                conn.sendall("You must /connect first.\n".encode())
            except:
                return False
            return True
            
        client_info = self.server_state.clients[conn]
        if not client_info.room:
            try:
                conn.sendall("You must /room <name> first.\n".encode())
            except:
                return False
            return True
        
        # Check rate limit for messages
        if not check_rate_limit(conn):
            try:
                conn.sendall("Rate limit exceeded. Please slow down.\n".encode())
            except:
                return False
            return True
        
        # Sanitize and limit message content
        message_content = sanitize_input(line[:MAX_MESSAGE_LENGTH]) if line else ""
        if not message_content.strip():
            return True  # Skip empty messages
        
        msg = f"[{client_info.avatar}] {client_info.nickname}: {message_content}"
        print(f"[MESSAGE] Room '{client_info.room}' - {client_info.nickname} [{client_info.avatar}]: {message_content}")
        
        # Add to message history
        room_messages = self.server_state.messages.setdefault(client_info.room, [])
        room_messages.append(msg)
        
        # Limit message history per room
        if len(room_messages) > MAX_MESSAGES_PER_ROOM:
            self.server_state.messages[client_info.room] = room_messages[-MAX_MESSAGES_PER_ROOM:]
        
        # Broadcast message
        broadcast(client_info.room, msg)
        return True

class ServerState:
    def __init__(self):
        self.clients: Dict[socket.socket, ClientInfo] = {}
        self.rooms: Dict[str, List[socket.socket]] = {}
        self.messages: Dict[str, List[str]] = {}
        self.rate_limits: Dict[socket.socket, Tuple[float, int]] = {}
        self.active_connections = 0

# Global server state
server_state = ServerState()
command_handler = CommandHandler(server_state)
message_processor = MessageProcessor(server_state, command_handler)

def sanitize_input(text):
    """Sanitize user input to prevent injection attacks"""
    if not text:
        return ""
    # Remove control characters except newline and tab
    sanitized = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', text)
    # HTML escape to prevent XSS-like attacks
    sanitized = html.escape(sanitized)
    return sanitized.strip()

def validate_nickname(nickname):
    """Validate nickname format and content"""
    if not nickname or len(nickname.strip()) == 0:
        return False, "Nickname cannot be empty"
    
    nickname = nickname.strip()
    if len(nickname) > MAX_NICKNAME_LENGTH:
        return False, f"Nickname too long (max {MAX_NICKNAME_LENGTH} characters)"
    
    # Check for valid characters (alphanumeric, spaces, basic punctuation)
    if not re.match(r'^[a-zA-Z0-9\s\-_\.\[\]\(\)]+$', nickname):
        return False, "Nickname contains invalid characters"
    
    return True, nickname[:MAX_NICKNAME_LENGTH]

def validate_room_name(room_name):
    """Validate room name format and content"""
    if not room_name or len(room_name.strip()) == 0:
        return False, "Room name cannot be empty"
    
    room_name = room_name.strip()
    if len(room_name) > MAX_ROOM_NAME_LENGTH:
        return False, f"Room name too long (max {MAX_ROOM_NAME_LENGTH} characters)"
    
    # Allow # prefix and basic characters
    if not re.match(r'^[#a-zA-Z0-9\s\-_\.]+$', room_name):
        return False, "Room name contains invalid characters"
    
    return True, room_name[:MAX_ROOM_NAME_LENGTH]

def check_rate_limit(conn, max_messages=20, window_seconds=60):
    """Check if connection exceeds rate limit"""
    now = time.time()
    
    if conn not in server_state.rate_limits:
        server_state.rate_limits[conn] = (now, 1)
        return True
    
    last_time, count = server_state.rate_limits[conn]
    
    # Reset counter if window has passed
    if now - last_time >= window_seconds:
        server_state.rate_limits[conn] = (now, 1)
        return True
    
    # Check if under limit
    if count < max_messages:
        server_state.rate_limits[conn] = (last_time, count + 1)
        return True
    
    # Rate limited
    return False

def broadcast(room, msg):
    if room in server_state.rooms:
        print(f"[BROADCAST] Room '{room}': {msg}")
        for conn in server_state.rooms[room][:]:  # Copy list to avoid modification during iteration
            try:
                conn.sendall(f"{msg}\n".encode())
            except Exception as e:
                print(f"[ERROR] Broadcast error to client: {e}")
                # Remove broken connection
                server_state.rooms[room].remove(conn)
                if conn in server_state.clients:
                    del server_state.clients[conn]

def handle_client(conn, addr):
    nickname = None
    room = None

    try:
        # Enable TCP keepalive to prevent network timeouts
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        
        # Check connection limit
        if server_state.active_connections >= MAX_CLIENTS:
            conn.sendall("Server full. Please try again later.\n".encode())
            return
        
        server_state.active_connections += 1
        print(f"[CONNECT] New client connected from {addr} ({server_state.active_connections}/{MAX_CLIENTS})")
        conn.sendall("Welcome to Tempest Server! Use /connect <name> to begin.\n".encode())
    except Exception as e:
        print(f"[ERROR] Initial connection setup failed for {addr}: {e}")
        return
    
    try:
        while True:
            try:
                line = conn.recv(1024)
                if not line:
                    break
                line = line.decode('utf-8', errors='ignore').strip()
            except Exception as e:
                print(f"[ERROR] Receive error from {addr}: {e}")
                break

            # Process the line using the message processor
            should_continue = message_processor.process_line(conn, line, addr)
            if not should_continue:
                break

    except socket.timeout:
        print(f"[TIMEOUT] Client {addr} timed out")
    except Exception as e:
        print(f"[ERROR] Client {addr} error: {e}")
    finally:
        # Clean up
        try:
            server_state.active_connections -= 1
            if conn in server_state.clients:
                client_info = server_state.clients[conn]
                print(f"[CLEANUP] Cleaning up client {client_info.nickname} [{client_info.avatar}] from {addr}")
                if client_info.room and conn in server_state.rooms.get(client_info.room, []):
                    server_state.rooms[client_info.room].remove(conn)
                    # Clean up empty rooms
                    if not server_state.rooms[client_info.room]:
                        del server_state.rooms[client_info.room]
                        if client_info.room in server_state.messages:
                            del server_state.messages[client_info.room]
                    else:
                        broadcast(client_info.room, f"** [{client_info.avatar}] {client_info.nickname} has left the room **")
                del server_state.clients[conn]
            else:
                print(f"[CLEANUP] Anonymous client from {addr} disconnected")
            
            # Clean up rate limit data
            if conn in server_state.rate_limits:
                del server_state.rate_limits[conn]
        except Exception as cleanup_error:
            print(f"[ERROR] Cleanup error for {addr}: {cleanup_error}")
        finally:
            try:
                conn.close()
            except:
                pass

def find_tempest_processes():
    """Find all running Tempest server processes"""
    try:
        # Find processes running server.py
        result = subprocess.run(['pgrep', '-f', 'python.*server.py'], 
                              capture_output=True, text=True)
        pids = []
        if result.returncode == 0:
            pids.extend([int(pid.strip()) for pid in result.stdout.strip().split('\n') if pid.strip()])
        
        # Also check for processes listening on port 1991
        try:
            result = subprocess.run(['lsof', '-ti:1991'], 
                                  capture_output=True, text=True)
            if result.returncode == 0:
                port_pids = [int(pid.strip()) for pid in result.stdout.strip().split('\n') if pid.strip()]
                pids.extend(port_pids)
        except:
            pass
        
        # Remove duplicates and exclude current process
        current_pid = os.getpid()
        return list(set(pid for pid in pids if pid != current_pid))
    except:
        return []

def shutdown_tempest_servers():
    """Shutdown all running Tempest servers"""
    pids = find_tempest_processes()
    
    if not pids:
        print("No Tempest servers found running.")
        return
    
    print(f"Found {len(pids)} Tempest server process(es): {pids}")
    
    # First try graceful shutdown with SIGTERM
    for pid in pids:
        try:
            print(f"Sending SIGTERM to process {pid}...")
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            print(f"Process {pid} already terminated.")
        except PermissionError:
            print(f"Permission denied to terminate process {pid}.")
    
    # Wait a moment for graceful shutdown
    time.sleep(2)
    
    # Check if any processes are still running and force kill if necessary
    remaining_pids = find_tempest_processes()
    if remaining_pids:
        print(f"Force killing remaining processes: {remaining_pids}")
        for pid in remaining_pids:
            try:
                os.kill(pid, signal.SIGKILL)
                print(f"Force killed process {pid}")
            except ProcessLookupError:
                print(f"Process {pid} already terminated.")
            except PermissionError:
                print(f"Permission denied to force kill process {pid}.")
    
    # Final check
    final_pids = find_tempest_processes()
    if final_pids:
        print(f"Warning: Some processes may still be running: {final_pids}")
        print("You may need to run this script with sudo or manually kill these processes.")
    else:
        print("All Tempest servers have been shut down successfully.")

def start_server(host='localhost', port=1991):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        # Security configurations
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.settimeout(1.0)  # Allow keyboard interrupt
        
        try:
            s.bind((host, port))
            s.listen(5)  # Limit backlog
            print(f"[SERVER] Tempest Server running on {host}:{port}...")
            print(f"[CONFIG] Max clients: {MAX_CLIENTS}, Max rooms: {MAX_ROOMS}")
            
            while True:
                try:
                    conn, addr = s.accept()
                    print(f"[ACCEPT] Accepting connection from {addr}")
                    threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()
                except socket.timeout:
                    continue  # Allow graceful shutdown
                except KeyboardInterrupt:
                    print("\n[SHUTDOWN] Server shutting down...")
                    break
                except Exception as e:
                    print(f"[ERROR] Accept error: {e}")
                    continue
        except Exception as e:
            print(f"[ERROR] Server startup failed: {e}")
            return

if __name__ == "__main__":
    import sys
    
    host = 'localhost'  # Default to localhost for security
    port = 1991
    
    # Parse command line arguments
    if len(sys.argv) > 1:
        if sys.argv[1] == '--help' or sys.argv[1] == '-h':
            print("Usage: python server.py [options] [host] [port]")
            print()
            print("Options:")
            print("  --shutdown         Shutdown all running Tempest servers")
            print("  --help, -h         Show this help message")
            print()
            print("Arguments:")
            print("  host: Interface to bind to (default: localhost)")
            print("        Use '0.0.0.0' to accept connections from any IP")
            print("  port: Port to listen on (default: 1991)")
            print()
            print("Examples:")
            print("  python server.py                  # localhost:1991")
            print("  python server.py 0.0.0.0          # all interfaces:1991")
            print("  python server.py 0.0.0.0 8080     # all interfaces:8080")
            print("  python server.py --shutdown       # shutdown running servers")
            sys.exit(0)
        elif sys.argv[1] == '--shutdown':
            shutdown_tempest_servers()
            sys.exit(0)
        
        # Parse host/port arguments (skip if first arg was a flag)
        arg_start = 1
        host = sys.argv[arg_start]
        if len(sys.argv) > arg_start + 1:
            try:
                port = int(sys.argv[arg_start + 1])
            except ValueError:
                print(f"Error: Invalid port '{sys.argv[arg_start + 1]}'. Must be a number.")
                sys.exit(1)
    
    if host == '0.0.0.0':
        print("WARNING: Server will accept connections from any IP address!")
        print("Make sure your firewall is properly configured.")
    
    start_server(host, port)