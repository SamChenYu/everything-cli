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
import shutil
import tempfile
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from security_utils import (
    safe_extract_zip, validate_file_size, get_safe_output_path,
    SecurityError, ZipBombError, FileSizeError, DiskSpaceError, PathTraversalError
)

# ============ ENCRYPTION SETTINGS ============
ENABLE_ENCRYPTION = True  # Set to False to disable encryption
RSA_KEY_SIZE = 2048  # RSA key size in bits (2048 or 4096)
RSA_PUBLIC_EXPONENT = 65537  # Standard RSA public exponent
AES_KEY_SIZE = 32  # AES-256 (32 bytes = 256 bits)
# ============================================

HOST = '0.0.0.0'  # Listen on all interfaces
PORT = 9999       # Port to listen on
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

def exchange_keys(conn, my_public_key):
    """Exchange public keys with the client"""
    # Receive client's public key
    client_key_len = int.from_bytes(recv_exact(conn, 4), 'big')
    client_public_bytes = recv_exact(conn, client_key_len)
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

def receive_file(conn, metadata, output_dir, private_key=None):
    """Receive a file from the connection"""
    filename = metadata['filename']
    filesize = metadata['filesize']
    encrypted = metadata.get('encrypted', False)

    # Validate file size before receiving
    try:
        validate_file_size(filesize, output_dir)
    except (FileSizeError, DiskSpaceError) as e:
        print(f"Error: {e}")
        raise

    # Get safe output path
    try:
        filepath = get_safe_output_path(output_dir, filename)
    except (PathTraversalError, ValueError) as e:
        print(f"Error: Invalid filename - {e}")
        raise

    print(f"Receiving file: {filename} ({filesize} bytes)")
    if encrypted:
        print("  (encrypted)")

    if DEBUG_MODE:
        print(f"[DEBUG] File metadata: {metadata}")

    # Receive all data first
    data = b''
    bytes_received = 0
    while bytes_received < filesize:
        chunk = conn.recv(min(BUFFER_SIZE, filesize - bytes_received))
        if not chunk:
            break
        data += chunk
        bytes_received += len(chunk)
        print(f"\rProgress: {bytes_received}/{filesize} bytes ({100*bytes_received//filesize}%)", end='')

    print()

    # Decrypt if needed
    if encrypted and private_key:
        print("Decrypting file...")
        if DEBUG_MODE:
            print(f"[DEBUG] Encrypted file size: {len(data)} bytes")
        data = decrypt_large_data(data, private_key)
        if DEBUG_MODE:
            print(f"[DEBUG] Decrypted file size: {len(data)} bytes")

    # Save file
    with open(filepath, 'wb') as f:
        f.write(data)

    print(f"File saved to: {filepath}\n")
    return filepath

def receive_directory(conn, metadata, output_dir, private_key=None):
    """Receive a directory (as zip) from the connection"""
    filename = metadata['filename']
    filesize = metadata['filesize']
    original_dirname = metadata.get('original_dirname', 'received_directory')
    encrypted = metadata.get('encrypted', False)

    # Validate file size before receiving
    try:
        validate_file_size(filesize, output_dir)
    except (FileSizeError, DiskSpaceError) as e:
        print(f"Error: {e}")
        raise

    # Save zip to temporary location
    temp_zip = os.path.join(output_dir, filename)

    print(f"Receiving directory: {original_dirname} ({filesize} bytes)")
    if encrypted:
        print("  (encrypted)")

    if DEBUG_MODE:
        print(f"[DEBUG] Directory metadata: {metadata}")

    # Receive all data first
    data = b''
    bytes_received = 0
    while bytes_received < filesize:
        chunk = conn.recv(min(BUFFER_SIZE, filesize - bytes_received))
        if not chunk:
            break
        data += chunk
        bytes_received += len(chunk)
        print(f"\rProgress: {bytes_received}/{filesize} bytes ({100*bytes_received//filesize}%)", end='')

    print()

    # Decrypt if needed
    if encrypted and private_key:
        print("Decrypting directory...")
        if DEBUG_MODE:
            print(f"[DEBUG] Encrypted zip size: {len(data)} bytes")
        data = decrypt_large_data(data, private_key)
        if DEBUG_MODE:
            print(f"[DEBUG] Decrypted zip size: {len(data)} bytes")

    # Save decrypted zip
    with open(temp_zip, 'wb') as f:
        f.write(data)

    print(f"Validating and extracting directory...")

    try:
        # Determine target path, auto-suffixing if it already exists
        extract_path = os.path.join(output_dir, original_dirname)
        counter = 1
        while os.path.exists(extract_path):
            extract_path = os.path.join(output_dir, f"{original_dirname}_{counter}")
            counter += 1

        # Extract into a staging dir so we can rename to the unique target
        staging_dir = tempfile.mkdtemp(dir=output_dir, prefix='.extract_')
        try:
            extracted_size = safe_extract_zip(temp_zip, staging_dir)

            if DEBUG_MODE:
                print(f"[DEBUG] Extracted {extracted_size:,} bytes")

            staging_contents = os.listdir(staging_dir)
            if (len(staging_contents) == 1
                    and os.path.isdir(os.path.join(staging_dir, staging_contents[0]))):
                shutil.move(os.path.join(staging_dir, staging_contents[0]), extract_path)
            else:
                os.makedirs(extract_path)
                for item in staging_contents:
                    shutil.move(os.path.join(staging_dir, item),
                                os.path.join(extract_path, item))
        finally:
            if os.path.exists(staging_dir):
                shutil.rmtree(staging_dir, ignore_errors=True)

        print(f"Directory saved to: {extract_path}")

    except ZipBombError as e:
        print(f"\n⚠️  ZIP BOMB DETECTED: {e}")
        print("Transfer rejected for security reasons.")
        raise
    except (FileSizeError, PathTraversalError) as e:
        print(f"\n⚠️  SECURITY ERROR: {e}")
        print("Transfer rejected for security reasons.")
        raise
    finally:
        # Always remove temporary zip file
        if os.path.exists(temp_zip):
            os.remove(temp_zip)

    print()

def receive_message(conn, metadata, private_key):
    """Process a received text message"""
    message_size = metadata['size']
    encrypted = metadata.get('encrypted', False)

    if DEBUG_MODE:
        print(f"[DEBUG] Receiving message: {message_size} bytes, encrypted={encrypted}")

    # Receive message data
    message_data = recv_exact(conn, message_size)

    if DEBUG_MODE and encrypted:
        print(f"[DEBUG] Encrypted data ({len(message_data)} bytes): {message_data[:100]}...")

    # Decrypt if needed
    if encrypted and private_key:
        decrypted_bytes = decrypt_large_data(message_data, private_key)
        message = decrypted_bytes.decode('utf-8')
        if DEBUG_MODE:
            print(f"[DEBUG] Decrypted message: {message}")
    else:
        message = message_data.decode('utf-8')
        if DEBUG_MODE:
            print(f"[DEBUG] Raw message: {message}")

    print(f"Received: {message}\n")

def main():
    global DEBUG_MODE

    parser = argparse.ArgumentParser(description='Receive messages or files over TCP')
    parser.add_argument('--output', '-o', metavar='DIR',
                        help='Output directory for received files (default: Desktop)')
    parser.add_argument('--debug', '-d', action='store_true', help='Enable debug mode (show raw unencrypted data)')

    args = parser.parse_args()

    # Set debug mode
    DEBUG_MODE = args.debug

    # Set output directory (default to Desktop)
    output_dir = args.output if args.output else get_desktop_path()
    output_dir = os.path.expanduser(output_dir)

    # Create output directory if it doesn't exist
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    print(f"Files will be saved to: {output_dir}")

    # Generate RSA key pair if encryption is enabled
    private_key = None
    public_key = None
    if ENABLE_ENCRYPTION:
        print("Generating encryption keys...")
        private_key, public_key = generate_rsa_keypair()
        print("Keys generated")

    if DEBUG_MODE:
        print("[DEBUG MODE ENABLED - Raw data will be shown]")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((HOST, PORT))
        s.listen()
        s.settimeout(1.0)  # Timeout to allow checking for keyboard interrupt

        # Get and display the local IP address
        try:
            # Use a more reliable method to get local IP
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as temp_s:
                temp_s.connect(('8.8.8.8', 80))
                local_ip = temp_s.getsockname()[0]
        except Exception:
            local_ip = "Unable to determine"

        print(f"Server IP Address: {local_ip}")
        print(f"Listening on port {PORT}...")
        print("Press Ctrl+C to stop\n")

        try:
            while True:
                try:
                    conn, addr = s.accept()
                    with conn:
                        print(f"Connected by {addr}")

                        # Exchange keys if encryption is enabled
                        client_public_key = None
                        if ENABLE_ENCRYPTION:
                            if DEBUG_MODE:
                                print("Exchanging encryption keys...")
                            client_public_key = exchange_keys(conn, public_key)
                            if DEBUG_MODE:
                                print("Secure connection established")

                        # Receive metadata length (4 bytes)
                        metadata_len_bytes = recv_exact(conn, 4)
                        metadata_len = int.from_bytes(metadata_len_bytes, 'big')

                        if DEBUG_MODE:
                            print(f"[DEBUG] Metadata length: {metadata_len} bytes")

                        # Receive metadata
                        metadata_json = recv_exact(conn, metadata_len)
                        metadata = json.loads(metadata_json.decode('utf-8'))

                        if DEBUG_MODE:
                            print(f"[DEBUG] Metadata: {metadata}")

                        # Handle based on type
                        transfer_type = metadata.get('type', 'message')

                        if transfer_type == 'file':
                            receive_file(conn, metadata, output_dir, private_key)
                        elif transfer_type == 'directory':
                            receive_directory(conn, metadata, output_dir, private_key)
                        elif transfer_type == 'message':
                            receive_message(conn, metadata, private_key)

                        # Shutdown connection gracefully
                        try:
                            conn.shutdown(socket.SHUT_RDWR)
                        except OSError:
                            pass

                        print("Waiting for connection...")

                except socket.timeout:
                    continue  # No connection, keep waiting
        except KeyboardInterrupt:
            print("\nShutting down server...")
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            print("Server stopped.")

if __name__ == "__main__":
    main()
