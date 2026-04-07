#!/usr/bin/env python3
"""
Client script to send messages over TCP
Run this on Mac (or any machine) to send to Windows
"""
import socket

PORT = 9999  # Must match receiver port

def main():
    host = input("Enter IP address of receiver: ")
    print(f"Connected to {host}:{PORT}")
    print("Type your messages (Ctrl+C to quit)\n")

    try:
        while True:
            message = input("Message: ")
            if message:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.connect((host, PORT))
                    s.sendall(message.encode('utf-8'))
                    print(f"Sent!\n")
    except KeyboardInterrupt:
        print("\nDisconnected.")

if __name__ == "__main__":
    main()
