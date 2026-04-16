#!/usr/bin/env python3
"""
Server script to receive messages or files over TCP
Run this on Windows machine (or any machine)
"""
import socket
import argparse
import os
import json
import zipfile
import platform
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

HOST = '0.0.0.0'  # Listen on all interfaces
PORT = 9999       # Port to listen on
BUFFER_SIZE = 4096

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

def exchange_keys(conn, my_public_key):
    """Exchange public keys with the client"""
    # Receive client's public key
    client_key_len = int.from_bytes(conn.recv(4), 'big')
    client_public_bytes = conn.recv(client_key_len)
    client_public_key = deserialize_public_key(client_public_bytes)

    # Send our public key
    my_public_bytes = serialize_public_key(my_public_key)
    conn.sendall(len(my_public_bytes).to_bytes(4, 'big'))
    conn.sendall(my_public_bytes)

    return client_public_key

def decrypt_with_rsa(encrypted_data, private_key):
    """Decrypt small data with RSA"""
    return private_key.decrypt(
        encrypted_data,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None
        )
    )

def decrypt_large_data(encrypted_package, private_key):
    """Hybrid decryption: RSA for AES key, AES for data"""
    # Extract encrypted AES key length (first 4 bytes)
    offset = 0
    encrypted_key_len = int.from_bytes(encrypted_package[offset:offset+4], 'big')
    offset += 4

    # Extract encrypted AES key
    encrypted_aes_key = encrypted_package[offset:offset+encrypted_key_len]
    offset += encrypted_key_len

    # Decrypt AES key with RSA
    aes_key = decrypt_with_rsa(encrypted_aes_key, private_key)

    # Extract IV (16 bytes)
    iv = encrypted_package[offset:offset+16]
    offset += 16

    # Extract encrypted data
    encrypted_data = encrypted_package[offset:]

    # Decrypt data with AES
    cipher = Cipher(algorithms.AES(aes_key), modes.CFB(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    decrypted_data = decryptor.update(encrypted_data) + decryptor.finalize()

    return decrypted_data

def get_desktop_path():
    """Get the Desktop path for the current OS"""
    system = platform.system()
    home = os.path.expanduser("~")

    if system == "Windows":
        return os.path.join(home, "Desktop")
    elif system == "Darwin":  # macOS
        return os.path.join(home, "Desktop")
    elif system == "Linux":
        # Try XDG user dirs first, fallback to ~/Desktop
        desktop = os.path.join(home, "Desktop")
        if os.path.isdir(desktop):
            return desktop
        return home
    else:
        return home

def receive_file(conn, metadata, output_dir):
    """Receive a file from the connection"""
    filename = metadata['filename']
    filesize = metadata['filesize']

    filepath = os.path.join(output_dir, filename)

    # Handle duplicate filenames
    base, ext = os.path.splitext(filepath)
    counter = 1
    while os.path.exists(filepath):
        filepath = f"{base}_{counter}{ext}"
        counter += 1

    print(f"Receiving file: {filename} ({filesize} bytes)")

    with open(filepath, 'wb') as f:
        bytes_received = 0
        while bytes_received < filesize:
            chunk = conn.recv(min(BUFFER_SIZE, filesize - bytes_received))
            if not chunk:
                break
            f.write(chunk)
            bytes_received += len(chunk)
            print(f"\rProgress: {bytes_received}/{filesize} bytes ({100*bytes_received//filesize}%)", end='')

    print(f"\nFile saved to: {filepath}\n")
    return filepath

def receive_directory(conn, metadata, output_dir):
    """Receive a directory (as zip) from the connection"""
    filename = metadata['filename']
    filesize = metadata['filesize']
    original_dirname = metadata.get('original_dirname', 'received_directory')

    # Save zip to temporary location
    temp_zip = os.path.join(output_dir, filename)

    print(f"Receiving directory: {original_dirname} ({filesize} bytes)")

    with open(temp_zip, 'wb') as f:
        bytes_received = 0
        while bytes_received < filesize:
            chunk = conn.recv(min(BUFFER_SIZE, filesize - bytes_received))
            if not chunk:
                break
            f.write(chunk)
            bytes_received += len(chunk)
            print(f"\rProgress: {bytes_received}/{filesize} bytes ({100*bytes_received//filesize}%)", end='')

    print(f"\nExtracting directory...")

    # Extract zip
    extract_path = os.path.join(output_dir, original_dirname)

    # Handle duplicate directory names
    counter = 1
    while os.path.exists(extract_path):
        extract_path = os.path.join(output_dir, f"{original_dirname}_{counter}")
        counter += 1

    with zipfile.ZipFile(temp_zip, 'r') as zipf:
        zipf.extractall(output_dir)

    # Remove temporary zip file
    os.remove(temp_zip)

    print(f"Directory saved to: {extract_path}\n")

def receive_message(metadata):
    """Process a received text message"""
    message = metadata.get('content', '')
    print(f"Received: {message}\n")

def main():
    parser = argparse.ArgumentParser(description='Receive messages or files over TCP')
    parser.add_argument('--output', '-o', metavar='DIR',
                        help='Output directory for received files (default: Desktop)')

    args = parser.parse_args()

    # Set output directory (default to Desktop)
    output_dir = args.output if args.output else get_desktop_path()
    output_dir = os.path.expanduser(output_dir)

    # Create output directory if it doesn't exist
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    print(f"Files will be saved to: {output_dir}")

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

                        # Receive metadata length (4 bytes)
                        metadata_len_bytes = conn.recv(4)
                        if not metadata_len_bytes:
                            continue

                        metadata_len = int.from_bytes(metadata_len_bytes, 'big')

                        # Receive metadata
                        metadata_json = conn.recv(metadata_len)
                        metadata = json.loads(metadata_json.decode('utf-8'))

                        # Handle based on type
                        transfer_type = metadata.get('type', 'message')

                        if transfer_type == 'file':
                            receive_file(conn, metadata, output_dir)
                        elif transfer_type == 'directory':
                            receive_directory(conn, metadata, output_dir)
                        elif transfer_type == 'message':
                            receive_message(metadata)

                        print("Waiting for connection...")

                except socket.timeout:
                    continue  # No connection, keep waiting
        except KeyboardInterrupt:
            print("\nServer stopped.")

if __name__ == "__main__":
    main()
