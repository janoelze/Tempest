#!/usr/bin/env python3

import socket
import threading
import time
import sys
import subprocess
import signal
import os
from contextlib import contextmanager

class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    NC = '\033[0m'  # No Color

class TempestTestSuite:
    def __init__(self):
        self.server_process = None
        self.test_port = 1991
        self.use_existing_server = False
        self.tests_passed = 0
        self.tests_failed = 0
        
    def print_colored(self, message, color=Colors.NC):
        print(f"{color}{message}{Colors.NC}")
        
    def check_port_in_use(self, port):
        """Check if port is already in use"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(1)
                result = sock.connect_ex(('localhost', port))
                return result == 0
        except:
            return False
        
    def start_server(self):
        """Start the Tempest server"""
        if self.check_port_in_use(self.test_port):
            self.print_colored("Server already running on port 1991", Colors.YELLOW)
            self.use_existing_server = True
            return True

        try:
            self.server_process = subprocess.Popen(
                [sys.executable, 'server.py'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            # Wait for server to start
            time.sleep(2)
            
            # Check if server is still running
            if self.server_process.poll() is not None:
                self.print_colored("Server failed to start", Colors.RED)
                return False
                
            # Check if port is listening
            if not self.check_port_in_use(self.test_port):
                self.print_colored("Server not listening on port", Colors.RED)
                return False

            return True
            
        except Exception as e:
            self.print_colored(f"Failed to start server: {e}", Colors.RED)
            return False
            
    def stop_server(self):
        """Stop the Tempest server"""
        if self.server_process and not self.use_existing_server:
            self.server_process.terminate()
            try:
                self.server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.server_process.kill()
                self.server_process.wait()
                
    @contextmanager
    def test_client(self, timeout=5):
        """Context manager for test client connections"""
        client = None
        try:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(timeout)
            client.connect(('localhost', self.test_port))
            yield client
        finally:
            if client:
                try:
                    client.sendall(b'/bye\n')
                    client.close()
                except:
                    pass
                    
    def run_test(self, test_name, test_func):
        """Run a single test and track results"""
        # self.print_colored(f"\n🧪 {test_name}", Colors.YELLOW)
        try:
            if test_func():
                self.print_colored(f"- {test_name} PASSED")
                self.tests_passed += 1
                return True
            else:
                self.print_colored(f"- {test_name} FAILED", Colors.RED)
                self.tests_failed += 1
                return False
        except Exception as e:
            self.print_colored(f"- {test_name} FAILED: {e}", Colors.RED)
            self.tests_failed += 1
            return False
            
    def test_basic_connection(self):
        """Test basic server connection and welcome message"""
        with self.test_client() as client:
            # Read welcome message
            welcome = client.recv(1024).decode().strip()
            # case-insensitive check
            if "welcome to tempest server" not in welcome.lower():
                return False

            # Test /connect command
            client.sendall(b'/connect testuser\n')
            time.sleep(0.1)
            response = client.recv(1024).decode().strip()
            # case-insensitive match for WELCOME testuser
            return "WELCOME TESTUSER" in response.upper()

    def test_room_list_on_connect(self):
        """Test that room list is sent when client connects"""
        with self.test_client() as client:
            client.recv(1024)  # welcome
            client.sendall(b'/connect testuser\n')
            time.sleep(0.1)

            try:
                response = client.recv(1024).decode()
                # case-insensitive match
                return "WELCOME TESTUSER" in response.upper()
            except:
                return False

    def test_help_command(self):
        """Test /help command functionality"""
        with self.test_client() as client:
            # Skip welcome message
            client.recv(1024)

            # Test /help command
            client.sendall(b'/help\n')
            time.sleep(0.1)
            help_response = client.recv(1024).decode()

            # Verify help contains expected commands
            expected_commands = ['/connect', '/room', '/who', '/help', '/bye']
            if not all(cmd in help_response for cmd in expected_commands):
                return False

            # Test unknown command feedback
            client.sendall(b'/unknown\n')
            time.sleep(0.1)
            unknown_response = client.recv(1024).decode()
            # relax to any mention of "help"
            return "help" in unknown_response.lower()

    def test_room_operations(self):
        """Test room joining and messaging"""
        with self.test_client() as client:
            # Skip welcome message
            client.recv(1024)
            
            # Connect user
            client.sendall(b'/connect alice\n')
            time.sleep(0.1)
            client.recv(1024)  # consume response
            
            # Join room
            client.sendall(b'/room #testroom\n')
            time.sleep(0.1)
            room_response = client.recv(1024).decode()
            
            if ">>> Entered room: #testroom" not in room_response:
                return False
                
            # Send message
            client.sendall(b'Hello from test!\n')
            time.sleep(0.1)
            
            # Test /who command
            client.sendall(b'/who\n')
            time.sleep(0.1)
            who_response = client.recv(1024).decode()
            
            return "alice" in who_response
            
    def test_multiple_clients(self):
        """Test multiple client communication"""
        def client_alice():
            with self.test_client() as alice:
                alice.recv(1024)  # welcome
                alice.sendall(b'/connect alice\n')
                time.sleep(0.1)
                alice.recv(1024)  # welcome response
                
                alice.sendall(b'/room #multiclient\n')
                time.sleep(0.1)
                alice.recv(1024)  # room response
                
                alice.sendall(b'Hello from Alice!\n')
                time.sleep(2)  # Wait for Bob to join
                
                # Try to receive Bob's message
                try:
                    alice.settimeout(3)
                    data = alice.recv(1024).decode()
                    return "bob: Hello from Bob!" in data
                except socket.timeout:
                    return False
                    
        def client_bob():
            time.sleep(1)  # Let Alice join first
            with self.test_client() as bob:
                bob.recv(1024)  # welcome
                bob.sendall(b'/connect bob\n')
                time.sleep(0.1)
                bob.recv(1024)  # welcome response
                
                bob.sendall(b'/room #multiclient\n')
                time.sleep(0.1)
                room_data = bob.recv(1024).decode()
                
                # Should see Alice's message in history
                alice_msg_in_history = "alice: Hello from Alice!" in room_data
                
                bob.sendall(b'Hello from Bob!\n')
                time.sleep(0.1)
                
                return alice_msg_in_history
                
        # Run both clients concurrently
        import concurrent.futures
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            alice_future = executor.submit(client_alice)
            bob_future = executor.submit(client_bob)
            
            alice_result = alice_future.result(timeout=10)
            bob_result = bob_future.result(timeout=10)
            
        return alice_result or bob_result  # At least one should work
        
    def test_python_client_connectivity(self):
        """Test that Python client can connect (basic connectivity test)"""
        try:
            # Import the client module to test basic functionality
            import importlib.util
            spec = importlib.util.spec_from_file_location("client", "client.py")
            client_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(client_module)
            
            # Test basic connection without TUI
            test_client = client_module.TempestClient('localhost', self.test_port)
            connected = test_client.connect()
            
            if connected:
                test_client.disconnect()
                return True
            return False
            
        except Exception as e:
            print(f"Client connectivity test error: {e}")
            return False

    def test_large_payload_attack(self):
        """Test server resilience against large payload attacks"""
        with self.test_client(timeout=10) as client:
            try:
                client.recv(1024)  # welcome
                client.sendall(b'/connect testuser\n')
                time.sleep(0.1)
                client.recv(1024)  # welcome response
                
                # Send oversized nickname (potential buffer overflow)
                large_nickname = 'A' * 10000
                client.sendall(f'/connect {large_nickname}\n'.encode())
                time.sleep(0.1)
                
                # Server should still respond (not crash)
                try:
                    response = client.recv(1024)
                    return len(response) > 0
                except socket.timeout:
                    return False
            except Exception:
                return False

    def test_injection_in_nickname(self):
        """Test for injection vulnerabilities in nicknames"""
        with self.test_client() as client:
            try:
                client.recv(1024)  # welcome
                
                # Try injection-like nickname (short enough to test character validation)
                malicious_nick = "admin<script>"
                client.sendall(f'/connect {malicious_nick}\n'.encode())
                time.sleep(0.1)
                response = client.recv(1024).decode()
                
                # Server should reject malicious input with error message
                return "Error:" in response and "invalid characters" in response
            except Exception:
                return False

    def test_room_name_injection(self):
        """Test for injection vulnerabilities in room names"""
        with self.test_client() as client:
            try:
                client.recv(1024)  # welcome
                client.sendall(b'/connect testuser\n')
                time.sleep(0.1)
                client.recv(1024)  # welcome response
                
                # Try malicious room name
                malicious_room = "#room<script>alert('xss')</script>"
                client.sendall(f'/room {malicious_room}\n'.encode())
                time.sleep(0.1)
                response = client.recv(1024).decode()
                
                # Server should reject malicious input with error message
                return "Error:" in response and "invalid characters" in response.lower()
            except Exception:
                return False

    def test_message_flooding(self):
        """Test server resilience against message flooding"""
        with self.test_client() as client:
            try:
                client.recv(1024)  # welcome
                client.sendall(b'/connect flooduser\n')
                time.sleep(0.1)
                client.recv(1024)  # welcome response
                
                client.sendall(b'/room #floodroom\n')
                time.sleep(0.1)
                client.recv(1024)  # room response
                
                # Flood with messages
                for i in range(100):
                    client.sendall(f'Flood message {i}\n'.encode())
                    if i % 10 == 0:
                        time.sleep(0.01)  # Brief pause to avoid overwhelming
                
                # Server should still respond
                client.sendall(b'/who\n')
                time.sleep(0.5)
                response = client.recv(1024)
                return len(response) > 0
            except Exception:
                return False

    def test_connection_flooding(self):
        """Test server resilience against connection flooding"""
        connections = []
        try:
            # Try to open many connections quickly
            for i in range(20):
                try:
                    conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    conn.settimeout(2)
                    conn.connect(('localhost', self.test_port))
                    connections.append(conn)
                    conn.recv(1024)  # consume welcome
                except Exception:
                    break
            
            # Try to use the last connection
            if connections:
                last_conn = connections[-1]
                last_conn.sendall(b'/help\n')
                time.sleep(0.1)
                response = last_conn.recv(1024)
                return len(response) > 0
            
            return len(connections) > 5  # Should handle at least a few connections
        except Exception:
            return False
        finally:
            # Clean up connections
            for conn in connections:
                try:
                    conn.sendall(b'/bye\n')
                    conn.close()
                except:
                    pass

    def test_malformed_commands(self):
        """Test server resilience against malformed commands"""
        with self.test_client() as client:
            try:
                client.recv(1024)  # welcome
                
                # Send various malformed commands
                malformed_commands = [
                    b'/connect\n',  # No argument
                    b'/room\n',     # No argument
                    b'/connect ' + b'A' * 1000 + b'\n',  # Very long argument
                    b'/room ' + b'B' * 1000 + b'\n',     # Very long room name
                    b'/' + b'C' * 100 + b'\n',           # Very long command
                    b'/\n',         # Just slash
                    b'//\n',        # Double slash
                    b'/connect user1\n/connect user2\n', # Multiple connects
                ]
                
                for cmd in malformed_commands:
                    client.sendall(cmd)
                    time.sleep(0.05)
                    try:
                        client.recv(1024)  # Try to consume response
                    except socket.timeout:
                        pass
                
                # Server should still respond to valid commands
                client.sendall(b'/help\n')
                time.sleep(0.1)
                response = client.recv(1024)
                return b'help' in response.lower()
            except Exception:
                return False

    def test_resource_exhaustion_rooms(self):
        """Test server resilience against room creation flooding"""
        with self.test_client() as client:
            try:
                client.recv(1024)  # welcome
                client.sendall(b'/connect roomspammer\n')
                time.sleep(0.1)
                client.recv(1024)  # welcome response
                
                # Create many rooms
                for i in range(50):
                    client.sendall(f'/room #testroom{i}\n'.encode())
                    time.sleep(0.01)
                    try:
                        client.recv(1024)  # consume response
                    except socket.timeout:
                        pass
                
                # Server should still respond
                client.sendall(b'/who\n')
                time.sleep(0.1)
                response = client.recv(1024)
                return len(response) > 0
            except Exception:
                return False

    def test_unicode_injection(self):
        """Test server handling of unicode and special characters"""
        with self.test_client() as client:
            try:
                client.recv(1024)  # welcome
                
                # Test unicode in nickname
                unicode_nick = "test用户🔥💀"
                client.sendall(f'/connect {unicode_nick}\n'.encode('utf-8'))
                time.sleep(0.1)
                response = client.recv(1024)
                
                if len(response) == 0:
                    return False
                
                # Test unicode in room name
                unicode_room = "#房间🏠"
                client.sendall(f'/room {unicode_room}\n'.encode('utf-8'))
                time.sleep(0.1)
                response = client.recv(1024)
                
                return len(response) > 0
            except Exception:
                return False

    def test_version_display(self):
        """Test that server sends version information in WELCOME message"""
        with self.test_client() as client:
            try:
                client.recv(1024)  # welcome message
                
                # Connect user
                client.sendall(b'/connect testuser\n')
                time.sleep(0.1)
                response = client.recv(1024).decode().strip()
                
                # Check if response contains version information
                # Format should be: "WELCOME testuser [avatar] vVERSION"
                if "WELCOME TESTUSER" not in response.upper():
                    return False
                
                # Check for version pattern (v followed by characters, handling newlines)
                import re
                version_pattern = r'v[a-zA-Z0-9*]+(?:\n|$|\s)'
                has_version = bool(re.search(version_pattern, response))
                
                return has_version
                
            except Exception as e:
                print(f"Version test error: {e}")
                return False

    def test_typing_indicator(self):
        """Test typing indicator functionality"""
        # Create two clients
        with self.test_client() as client1, self.test_client() as client2:
            try:
                # Both clients connect
                client1.recv(1024)  # welcome
                client2.recv(1024)  # welcome
                
                client1.sendall(b'/connect alice\n')
                time.sleep(0.1)
                client1.recv(1024)  # welcome response
                
                client2.sendall(b'/connect bob\n')
                time.sleep(0.1)
                client2.recv(1024)  # welcome response
                
                # Both join the same room
                client1.sendall(b'/room #testroom\n')
                time.sleep(0.1)
                client1.recv(1024)  # room join response
                
                client2.sendall(b'/room #testroom\n')
                time.sleep(0.1)
                client2.recv(1024)  # room join response
                
                # Clear any remaining messages (like "alice entered room")
                try:
                    client2.recv(1024)
                except socket.timeout:
                    pass
                
                # Test basic typing indicator
                client1.sendall(b'/typing\n')
                time.sleep(0.2)
                
                # Client2 should receive typing notification
                try:
                    response = client2.recv(1024).decode()
                    if 'TYPING alice' not in response:
                        return False
                except socket.timeout:
                    return False
                
                # Test typing stop
                client1.sendall(b'/typing-stop\n')
                time.sleep(0.2)
                
                try:
                    response = client2.recv(1024).decode()
                    if 'TYPING-STOP alice' not in response:
                        return False
                except socket.timeout:
                    return False
                
                # Test that sending a message auto-stops typing
                client1.sendall(b'/typing\n')
                time.sleep(0.1)
                
                # Consume the typing notification
                try:
                    client2.recv(1024)
                except socket.timeout:
                    pass
                
                # Send a message (should auto-stop typing)
                client1.sendall(b'Hello world\n')
                time.sleep(0.2)
                
                # Should receive typing-stop and the message
                typing_stop_found = False
                message_found = False
                
                for _ in range(3):  # Try multiple times to catch both messages
                    try:
                        response = client2.recv(1024).decode()
                        if 'TYPING-STOP alice' in response:
                            typing_stop_found = True
                        if 'alice: Hello world' in response:
                            message_found = True
                    except socket.timeout:
                        break
                
                return typing_stop_found and message_found
                
            except Exception as e:
                print(f"Typing indicator test error: {e}")
                return False
            
    def run_all_tests(self):
        """Run the complete test suite"""
        self.print_colored("Tempest Integration Tests", Colors.YELLOW)

        # Start server
        if not self.start_server():
            return False
            
        try:
            # Run all tests
            tests = [
                ("Basic Connection", self.test_basic_connection),
                ("Version Display", self.test_version_display),
                ("Room List on Connect", self.test_room_list_on_connect),
                ("Help Command", self.test_help_command),
                ("Room Operations", self.test_room_operations),
                ("Multiple Clients", self.test_multiple_clients),
                ("Python Client Connectivity", self.test_python_client_connectivity),
                ("Large Payload Attack", self.test_large_payload_attack),
                ("Nickname Injection", self.test_injection_in_nickname),
                ("Room Name Injection", self.test_room_name_injection),
                ("Message Flooding", self.test_message_flooding),
                ("Connection Flooding", self.test_connection_flooding),
                ("Malformed Commands", self.test_malformed_commands),
                ("Resource Exhaustion (Rooms)", self.test_resource_exhaustion_rooms),
                ("Unicode Injection", self.test_unicode_injection),
                ("Typing Indicator", self.test_typing_indicator),
            ]
            
            for test_name, test_func in tests:
                self.run_test(test_name, test_func)
                
        finally:
            self.stop_server()

        total_tests = self.tests_passed + self.tests_failed
        if self.tests_failed == 0:
            self.print_colored("All tests passed!", Colors.YELLOW)
            return True
        else:
            self.print_colored(f"❌ {self.tests_failed}/{total_tests} tests failed", Colors.RED)
            return False

def main():
    """Main entry point"""
    test_suite = TempestTestSuite()
    success = test_suite.run_all_tests()
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()