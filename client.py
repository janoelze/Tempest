#!/usr/bin/env python3

import socket
import threading
import curses
import sys
import time
import random
import argparse
from collections import deque

class TempestClient:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.sock = None
        self.connected = False
        self.nickname = None
        self.current_room = None
        self.server_version = None
        self.messages = deque(maxlen=100)
        self.running = True
        self.typing_users = set()  # Set of nicknames currently typing
        self.last_keystroke = 0  # Timestamp of last keystroke
        self.typing_sent = False  # Whether we've sent typing indicator
        
    def connect(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # Enable TCP keepalive to prevent network timeouts
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            self.sock.connect((self.host, self.port))
            self.connected = True
            # Start receiving thread
            threading.Thread(target=self.receive_messages, daemon=True).start()
            return True
        except Exception as e:
            self.messages.append(f"Connection failed: {e}")
            return False
    
    def receive_messages(self):
        buffer = ""
        while self.connected and self.running:
            try:
                data = self.sock.recv(1024).decode()
                if not data:
                    break
                buffer += data
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    if line.strip():
                        self.handle_server_message(line.strip())
            except:
                break
        self.connected = False
    
    def handle_server_message(self, msg):
        if msg.startswith("WELCOME"):
            # Extract nickname and version from WELCOME message (format: "WELCOME nickname [avatar] vVERSION")
            parts = msg.split(" ")
            if len(parts) >= 2:
                self.nickname = parts[1]
            # Extract version if present
            for part in parts:
                if part.startswith("v") and len(part) > 1:
                    # Handle case where version might have newline attached
                    version_part = part[1:]  # Remove the 'v' prefix
                    # Split on newline and take first part
                    self.server_version = version_part.split('\n')[0]
                    break
            self.messages.append(f"* {msg}")
        elif msg.startswith("ENTERED"):
            room = msg.split(" ", 1)[1]
            self.current_room = room
            self.typing_users.clear()  # Clear typing users when changing rooms
            self.messages.append(f"* Entered {room}")
        elif msg.startswith("USERS:"):
            self.messages.append(f"* {msg}")
        elif msg.startswith("GOODBYE"):
            self.messages.append("* Goodbye!")
            self.running = False
        elif msg.startswith("TYPING "):
            # Extract nickname from TYPING message (format: "TYPING nickname [avatar]")
            parts = msg.split(" ", 2)
            if len(parts) >= 2:
                nickname = parts[1]
                self.typing_users.add(nickname)
        elif msg.startswith("TYPING-STOP "):
            # Extract nickname from TYPING-STOP message (format: "TYPING-STOP nickname")
            parts = msg.split(" ", 1)
            if len(parts) >= 2:
                nickname = parts[1]
                self.typing_users.discard(nickname)
        else:
            self.messages.append(msg)
    
    def send_message(self, msg):
        if self.connected:
            try:
                self.sock.sendall(f"{msg}\n".encode())
            except:
                self.connected = False
    
    def disconnect(self):
        self.running = False
        # Send typing-stop if we were typing
        if self.typing_sent and self.connected:
            self.send_message("/typing-stop")
            self.typing_sent = False
        if self.sock:
            self.sock.close()

def main_tui(stdscr, client):
    curses.curs_set(1)  # Show cursor
    stdscr.nodelay(1)   # Non-blocking input
    stdscr.timeout(50)  # Shorter timeout for responsiveness
    
    # Initialize color pairs - use default terminal colors
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, -1, -1)  # Use terminal default foreground and background
    
    # Initialize windows (will be recreated on resize)
    room_win = None
    line_win = None
    msg_win = None
    typing_win = None
    input_win = None
    last_height, last_width = 0, 0
    input_buffer = ""
    last_msg_count = 0
    last_typing_users = set()
    needs_full_refresh = True
    
    def safe_addstr(win, y, x, text, attr=0):
        """Safely add string to window, handling resize errors"""
        try:
            win.addstr(y, x, text, attr)
        except curses.error:
            pass  # Ignore drawing errors (likely due to resize)
    
    while client.running:
        try:
            # Get current terminal size
            height, width = stdscr.getmaxyx()
            
            # Recreate windows if terminal was resized
            if height != last_height or width != last_width:
                # Minimum size check
                if height < 7 or width < 20:
                    stdscr.clear()
                    safe_addstr(stdscr, 0, 0, "Terminal too small!")
                    stdscr.refresh()
                    continue
                    
                # Recreate windows
                try:
                    room_win = curses.newwin(1, width, 0, 0)
                    line_win = curses.newwin(1, width, 1, 0)
                    msg_win = curses.newwin(height-5, width, 2, 0)
                    typing_win = curses.newwin(1, width, height-3, 0)
                    input_win = curses.newwin(2, width, height-2, 0)
                    msg_win.scrollok(True)
                    last_height, last_width = height, width
                    needs_full_refresh = True
                except curses.error:
                    continue  # Skip this iteration if window creation fails
            
            # Check if we need to update UI elements
            msg_count = len(client.messages)
            messages_changed = msg_count != last_msg_count
            typing_changed = client.typing_users != last_typing_users
            
            # Update room window (only every second to reduce flicker from time updates)
            if room_win and (needs_full_refresh or int(time.time()) % 1 == 0):
                room_win.clear()
                room_display = f"Room: {client.current_room or 'Not connected'}"
                current_time = time.strftime("%I:%M %p")
                version_info = f"v{client.server_version}" if client.server_version else ""
                if version_info:
                    server_info = f"{client.host}:{client.port} {version_info} · {current_time}"
                else:
                    server_info = f"{client.host}:{client.port} · {current_time}"
                
                # Add room name on left (ensure it fits)
                room_text = room_display[:max(1, width-len(server_info)-2)]
                safe_addstr(room_win, 0, 0, room_text, curses.color_pair(1))
                
                # Add server info and time on right (only if there's space)
                if width > len(server_info) + 2:
                    time_pos = width - len(server_info) - 1
                    safe_addstr(room_win, 0, time_pos, server_info, curses.color_pair(1))
                room_win.refresh()
            
            # Add horizontal line under room (only on full refresh)
            if line_win and needs_full_refresh:
                line_win.clear()
                line_text = "─" * max(1, width-1)
                safe_addstr(line_win, 0, 0, line_text, curses.color_pair(1))
                line_win.refresh()
            
            # Update message window (only when messages change)
            if msg_win and (messages_changed or needs_full_refresh):
                msg_win.clear()
                msg_lines = list(client.messages)
                msg_height = max(1, height-5)
                start_line = max(0, len(msg_lines) - msg_height)
                for i, msg in enumerate(msg_lines[start_line:]):
                    if i < msg_height:
                        msg_text = msg[:max(1, width-1)]
                        safe_addstr(msg_win, i, 0, msg_text, curses.color_pair(1))
                msg_win.refresh()
                last_msg_count = msg_count
            
            # Update typing indicator window (when typing users change)
            if typing_win and (typing_changed or needs_full_refresh):
                typing_win.clear()
                if client.typing_users:
                    typing_list = sorted(list(client.typing_users))
                    if len(typing_list) == 1:
                        typing_text = f"◊ {typing_list[0]} is typing..."
                    elif len(typing_list) == 2:
                        typing_text = f"◊ {typing_list[0]} and {typing_list[1]} are typing..."
                    else:
                        typing_text = f"◊ {', '.join(typing_list[:-1])}, and {typing_list[-1]} are typing..."
                    
                    # Truncate if too long
                    typing_display = typing_text[:max(1, width-1)]
                    safe_addstr(typing_win, 0, 0, typing_display, curses.color_pair(1))
                typing_win.refresh()
                last_typing_users = client.typing_users.copy()
            
            # Always update input window to handle typing
            if input_win:
                input_win.clear()
                line_text = "─" * max(1, width-1)
                safe_addstr(input_win, 0, 0, line_text, curses.color_pair(1))
                if client.nickname:
                    prompt = f"{client.nickname}> {input_buffer}"
                else:
                    prompt = f"> {input_buffer}"
                prompt_text = prompt[:max(1, width-1)]
                safe_addstr(input_win, 1, 0, prompt_text, curses.color_pair(1))
                
                # Position cursor at end of input
                cursor_pos = min(len(prompt_text), width-1)
                try:
                    input_win.move(1, cursor_pos)
                except curses.error:
                    pass
                input_win.refresh()
            
            needs_full_refresh = False
            
            # Handle input
            try:
                ch = stdscr.getch()
                if ch == -1:
                    # No input - check for typing timeout
                    current_time = time.time()
                    if client.typing_sent and current_time - client.last_keystroke > 2.0:
                        # User stopped typing, send typing-stop
                        if client.connected:
                            client.send_message("/typing-stop")
                        client.typing_sent = False
                    continue
                elif ch == 10 or ch == 13:  # Enter
                    if input_buffer.strip():
                        # Send typing-stop if we were typing
                        if client.typing_sent and client.connected:
                            client.send_message("/typing-stop")
                        client.typing_sent = False
                        # Send the actual message
                        client.send_message(input_buffer.strip())
                        input_buffer = ""
                elif ch == 127 or ch == 8:  # Backspace
                    input_buffer = input_buffer[:-1]
                    # Track keystroke for typing indicator
                    if not client.typing_sent and client.connected:
                        current_time = time.time()
                        client.last_keystroke = current_time
                        client.send_message("/typing")
                        client.typing_sent = True
                elif ch == 27:  # Escape
                    break
                elif 32 <= ch <= 126:  # Printable characters
                    input_buffer += chr(ch)
                    # Track keystroke for typing indicator
                    if not client.typing_sent and client.connected:
                        current_time = time.time()
                        client.last_keystroke = current_time
                        client.send_message("/typing")
                        client.typing_sent = True
            except KeyboardInterrupt:
                break
        except curses.error:
            # Handle any other curses errors during the main loop
            continue
    
    client.disconnect()

def connection_animation():
    """Display retro connection animation"""
    frames = [
        "Initializing connection...",
        "Scanning for available ports...",
        "Establishing TCP handshake...",
        "Authenticating with server...",
        "Loading chat protocols...",
        "Synchronizing with server clock...",
        "Connection established!"
    ]
    
    progress_chars = ["░", "▒", "▓", "█"]
    
    for i, frame in enumerate(frames):
        print(f"\r{frame}", end="", flush=True)
        
        # Show progress bar for each step
        progress = ""
        for j in range(20):
            if j < (i + 1) * 20 // len(frames):
                progress += random.choice(progress_chars)
            else:
                progress += "░"
        
        print(f"\n[{progress}] {((i + 1) * 100) // len(frames)}%", end="")
        
        # Simulate connection work with random delay
        time.sleep(random.uniform(0.1, 0.4))
        
        # Clear line for next frame
        if i < len(frames) - 1:
            print("\033[2A\033[K\033[1B\033[K", end="")
    
    print("\n")
    time.sleep(0.2)

def main():
    parser = argparse.ArgumentParser(description='Tempest Chat Client')
    parser.add_argument('server', nargs='?', default='localhost:1991',
                       help='Server address (host:port)')
    args = parser.parse_args()
    
    if ':' in args.server:
        host, port = args.server.rsplit(':', 1)
        port = int(port)
    else:
        host = args.server
        port = 1991
    
    client = TempestClient(host, port)
    
    print(f"Connecting to {host}:{port}...")
    
    # Attempt actual connection
    if not client.connect():
        print("CONNECTION FAILED")
        print("Check server status and try again.")
        return 1
    
    print("Connected successfully!")
    
    try:
        curses.wrapper(main_tui, client)
    except KeyboardInterrupt:
        pass
    finally:
        client.disconnect()
    
    return 0

if __name__ == "__main__":
    sys.exit(main())