#!/usr/bin/env python3
"""
Server script to receive messages over TCP
Run this on Windows machine
"""
import socket

HOST = '0.0.0.0'  # Listen on all interfaces
PORT = 9999       # Port to listen on

def main():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((HOST, PORT))
        s.listen()
        s.settimeout(1.0)  # Timeout to allow checking for keyboard interrupt

        # Get and display the local IP address
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        print(f"Server IP Address: {local_ip}")
        print(f"Listening on port {PORT}...")
        print("Press Ctrl+C to stop\n")

        try:
            while True:
                try:
                    conn, addr = s.accept()
                    with conn:
                        print(f"Connected by {addr}")
                        data = conn.recv(1024)
                        if data:
                            message = data.decode('utf-8')
                            print(f"Received: {message}\n")
                        print("Waiting for connection...")
                except socket.timeout:
                    continue  # No connection, keep waiting
        except KeyboardInterrupt:
            print("\nServer stopped.")

if __name__ == "__main__":
    main()
