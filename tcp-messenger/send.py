#!/usr/bin/env python3
"""
Client script to send messages or files over TCP
Run this on Mac (or any machine) to send to Windows
"""
import socket
import argparse
import os
import json
import zipfile
import tempfile
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

# ============ ENCRYPTION SETTINGS ============
ENABLE_ENCRYPTION = True  # Set to False to disable encryption
RSA_KEY_SIZE = 2048  # RSA key size in bits (2048 or 4096)
RSA_PUBLIC_EXPONENT = 65537  # Standard RSA public exponent
AES_KEY_SIZE = 32  # AES-256 (32 bytes = 256 bits)
# ============================================

PORT = 9999  # Must match receiver port
BUFFER_SIZE = 4096
DEBUG_MODE = False  # Set to True to show raw unencrypted data

def recv_exact(sock, num_bytes):
    """Receive exactly num_bytes from socket"""
    data = b''
    while len(data) < num_bytes:
        chunk = sock.recv(num_bytes - len(data))
        if not chunk:
            raise ConnectionError("Socket connection closed")
        data += chunk
    return data

def generate_rsa_keypair():
    """Generate RSA public/private key pair"""
    private_key = rsa.generate_private_key(
        public_exponent=RSA_PUBLIC_EXPONENT,
        key_size=RSA_KEY_SIZE,
        backend=default_backend()
    )
    public_key = private_key.public_key()
    return private_key, public_key

def serialize_public_key(public_key):
    """Convert public key to bytes for transmission"""
    return public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )

def deserialize_public_key(key_bytes):
    """Convert bytes back to public key"""
    return serialization.load_pem_public_key(key_bytes, backend=default_backend())

def exchange_keys(sock, my_public_key):
    """Exchange public keys with the server"""
    # Send our public key
    my_public_bytes = serialize_public_key(my_public_key)
    sock.sendall(len(my_public_bytes).to_bytes(4, 'big'))
    sock.sendall(my_public_bytes)

    # Receive server's public key
    server_key_len = int.from_bytes(recv_exact(sock, 4), 'big')
    server_public_bytes = recv_exact(sock, server_key_len)
    server_public_key = deserialize_public_key(server_public_bytes)

    return server_public_key

def encrypt_with_rsa(data, public_key):
    """Encrypt small data with RSA"""
    return public_key.encrypt(
        data,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None
        )
    )

def encrypt_large_data(data, public_key):
    """Hybrid encryption: AES for data, RSA for AES key"""
    # Generate random AES key
    aes_key = os.urandom(AES_KEY_SIZE)
    iv = os.urandom(16)  # AES block size

    # Encrypt data with AES
    cipher = Cipher(algorithms.AES(aes_key), modes.CFB(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    encrypted_data = encryptor.update(data) + encryptor.finalize()

    # Encrypt AES key with RSA
    encrypted_aes_key = encrypt_with_rsa(aes_key, public_key)

    # Return: encrypted_key_length + encrypted_key + iv + encrypted_data
    result = len(encrypted_aes_key).to_bytes(4, 'big')
    result += encrypted_aes_key
    result += iv
    result += encrypted_data

    return result

def send_file(host, filepath, private_key=None, public_key=None):
    """Send a single file over TCP"""
    if not os.path.isfile(filepath):
        print(f"Error: {filepath} is not a valid file")
        return

    filename = os.path.basename(filepath)
    filesize = os.path.getsize(filepath)

    if DEBUG_MODE:
        print(f"[DEBUG] Sending file: {filename}")
        print(f"[DEBUG] Original file size: {filesize} bytes")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((host, PORT))

        # Exchange keys if encryption is enabled
        server_public_key = None
        if ENABLE_ENCRYPTION:
            if DEBUG_MODE:
                print("Exchanging encryption keys...")
            server_public_key = exchange_keys(s, public_key)
            if DEBUG_MODE:
                print("Secure connection established")

        # Read file data
        with open(filepath, 'rb') as f:
            file_data = f.read()

        # Encrypt if enabled
        if ENABLE_ENCRYPTION:
            print("Encrypting file...")
            encrypted_data = encrypt_large_data(file_data, server_public_key)
            data_to_send = encrypted_data
            actual_size = len(encrypted_data)
            if DEBUG_MODE:
                print(f"[DEBUG] Encrypted file size: {actual_size} bytes")
        else:
            data_to_send = file_data
            actual_size = filesize

        # Send metadata
        metadata = {
            'type': 'file',
            'filename': filename,
            'filesize': actual_size,
            'original_size': filesize,
            'encrypted': ENABLE_ENCRYPTION
        }
        metadata_json = json.dumps(metadata).encode('utf-8')

        if DEBUG_MODE:
            print(f"[DEBUG] Metadata: {metadata}")

        s.sendall(len(metadata_json).to_bytes(4, 'big'))
        s.sendall(metadata_json)

        # Send file data
        bytes_sent = 0
        offset = 0
        while offset < len(data_to_send):
            chunk = data_to_send[offset:offset + BUFFER_SIZE]
            s.sendall(chunk)
            bytes_sent += len(chunk)
            offset += len(chunk)
            progress = 100 * bytes_sent // len(data_to_send)
            print(f"\rProgress: {bytes_sent}/{actual_size} bytes ({progress}%)", end='')

        print(f"\nFile '{filename}' sent successfully!")
        if ENABLE_ENCRYPTION:
            print("  (encrypted)")


def send_directory(host, dirpath, private_key=None, public_key=None):
    """Send a directory as a zip file over TCP"""
    if not os.path.isdir(dirpath):
        print(f"Error: {dirpath} is not a valid directory")
        return

    dirname = os.path.basename(dirpath.rstrip('/'))

    # Create temporary zip file
    with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp:
        tmp_zip_path = tmp.name

    try:
        print(f"Zipping directory '{dirname}'...")
        with zipfile.ZipFile(tmp_zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(dirpath):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.join(dirname, os.path.relpath(file_path, dirpath))
                    zipf.write(file_path, arcname)

        original_size = os.path.getsize(tmp_zip_path)

        if DEBUG_MODE:
            print(f"[DEBUG] Sending directory: {dirname}")
            print(f"[DEBUG] Original zip size: {original_size} bytes")

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((host, PORT))

            # Exchange keys if encryption is enabled
            server_public_key = None
            if ENABLE_ENCRYPTION:
                if DEBUG_MODE:
                    print("Exchanging encryption keys...")
                server_public_key = exchange_keys(s, public_key)
                if DEBUG_MODE:
                    print("Secure connection established")

            # Read zip data
            with open(tmp_zip_path, 'rb') as f:
                zip_data = f.read()

            # Encrypt if enabled
            if ENABLE_ENCRYPTION:
                print("Encrypting directory...")
                encrypted_data = encrypt_large_data(zip_data, server_public_key)
                data_to_send = encrypted_data
                actual_size = len(encrypted_data)
                if DEBUG_MODE:
                    print(f"[DEBUG] Encrypted zip size: {actual_size} bytes")
            else:
                data_to_send = zip_data
                actual_size = original_size

            # Send metadata
            metadata = {
                'type': 'directory',
                'filename': f"{dirname}.zip",
                'filesize': actual_size,
                'original_size': original_size,
                'original_dirname': dirname,
                'encrypted': ENABLE_ENCRYPTION
            }
            metadata_json = json.dumps(metadata).encode('utf-8')

            if DEBUG_MODE:
                print(f"[DEBUG] Metadata: {metadata}")

            s.sendall(len(metadata_json).to_bytes(4, 'big'))
            s.sendall(metadata_json)

            # Send zip file data
            bytes_sent = 0
            offset = 0
            while offset < len(data_to_send):
                chunk = data_to_send[offset:offset + BUFFER_SIZE]
                s.sendall(chunk)
                bytes_sent += len(chunk)
                offset += len(chunk)
                progress = 100 * bytes_sent // len(data_to_send)
                print(f"\rProgress: {bytes_sent}/{actual_size} bytes ({progress}%)", end='')

            print(f"\nDirectory '{dirname}' sent successfully!")
            if ENABLE_ENCRYPTION:
                print("  (encrypted)")

    finally:
        # Clean up temporary zip file
        if os.path.exists(tmp_zip_path):
            os.remove(tmp_zip_path)

def send_message(host, private_key=None, public_key=None):
    """Send text messages over TCP"""
    print(f"Connected to {host}:{PORT}")
    if ENABLE_ENCRYPTION:
        print("Encryption enabled")
    if DEBUG_MODE:
        print("[DEBUG MODE ENABLED - Raw data will be shown]")
    print("Type your messages (Ctrl+C to quit)\n")

    try:
        while True:
            message = input("Message: ")
            if message:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.connect((host, PORT))

                    # Exchange keys if encryption is enabled
                    server_public_key = None
                    if ENABLE_ENCRYPTION:
                        server_public_key = exchange_keys(s, public_key)

                    # Prepare message
                    message_bytes = message.encode('utf-8')

                    if DEBUG_MODE:
                        print(f"[DEBUG] Raw message: {message}")
                        print(f"[DEBUG] Message bytes ({len(message_bytes)}): {message_bytes[:100]}...")

                    # Encrypt if enabled
                    if ENABLE_ENCRYPTION:
                        encrypted_message = encrypt_with_rsa(message_bytes, server_public_key)
                        data_to_send = encrypted_message
                        if DEBUG_MODE:
                            print(f"[DEBUG] Encrypted size: {len(encrypted_message)} bytes")
                    else:
                        data_to_send = message_bytes

                    # Send metadata
                    metadata = {
                        'type': 'message',
                        'size': len(data_to_send),
                        'encrypted': ENABLE_ENCRYPTION
                    }
                    metadata_json = json.dumps(metadata).encode('utf-8')

                    if DEBUG_MODE:
                        print(f"[DEBUG] Metadata: {metadata}")

                    s.sendall(len(metadata_json).to_bytes(4, 'big'))
                    s.sendall(metadata_json)

                    # Send message data
                    s.sendall(data_to_send)

                    status = "Sent (encrypted)" if ENABLE_ENCRYPTION else "Sent!"
                    print(f"{status}\n")
    except KeyboardInterrupt:
        print("\nDisconnected.")

def main():
    global DEBUG_MODE

    parser = argparse.ArgumentParser(description='Send messages or files over TCP')
    parser.add_argument('--file', '-f', metavar='PATH', help='Send a file or directory')
    parser.add_argument('--host', '-H', help='IP address of receiver (if not specified, will prompt)')
    parser.add_argument('--debug', '-d', action='store_true', help='Enable debug mode (show raw unencrypted data)')

    args = parser.parse_args()

    # Set debug mode
    DEBUG_MODE = args.debug

    # Generate RSA key pair if encryption is enabled
    private_key = None
    public_key = None
    if ENABLE_ENCRYPTION:
        print("Generating encryption keys...")
        private_key, public_key = generate_rsa_keypair()
        print("Keys generated")

    # Get host address
    host = args.host if args.host else input("Enter IP address of receiver: ")

    if args.file:
        # File/directory transfer mode
        path = os.path.expanduser(args.file)

        if os.path.isfile(path):
            send_file(host, path, private_key, public_key)
        elif os.path.isdir(path):
            send_directory(host, path, private_key, public_key)
        else:
            print(f"Error: '{args.file}' is not a valid file or directory")
    else:
        # Message mode
        send_message(host, private_key, public_key)

if __name__ == "__main__":
    main()
