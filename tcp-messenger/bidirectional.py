#!/usr/bin/env python3
"""
Bidirectional chat application over TCP
Combines sending and receiving capabilities for real-time chat
Supports text messages and file transfers
"""
import socket
import argparse
import threading
import json
import sys
import os
import tempfile
import zipfile
import platform
import shutil
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from security_utils import (
    safe_extract_zip, validate_file_size, get_safe_output_path,
    SecurityError, ZipBombError, FileSizeError, DiskSpaceError, PathTraversalError
)

ENABLE_ENCRYPTION = True
RSA_KEY_SIZE = 2048
RSA_PUBLIC_EXPONENT = 65537
AES_KEY_SIZE = 32
PORT = 9999
BUFFER_SIZE = 4096
DEBUG_MODE = False

class BidirectionalChat:
    def __init__(self, mode, host=None, port=PORT, debug=False, output_dir=None):
        self.mode = mode
        self.host = host
        self.port = port
        self.debug = debug
        self.private_key = None
        self.public_key = None
        self.peer_public_key = None
        self.running = True
        self.connection = None
        self.output_dir = output_dir or self.get_desktop_path()
        self.input_lock = threading.Lock()

        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

        if ENABLE_ENCRYPTION:
            print("Generating encryption keys...")
            self.private_key, self.public_key = self.generate_rsa_keypair()
            print("Keys generated")

    def get_desktop_path(self):
        system = platform.system()
        home = os.path.expanduser("~")

        if system == "Windows":
            return os.path.join(home, "Desktop")
        elif system == "Darwin":
            return os.path.join(home, "Desktop")
        elif system == "Linux":
            desktop = os.path.join(home, "Desktop")
            if os.path.isdir(desktop):
                return desktop
            return home
        else:
            return home

    def generate_rsa_keypair(self):
        private_key = rsa.generate_private_key(
            public_exponent=RSA_PUBLIC_EXPONENT,
            key_size=RSA_KEY_SIZE,
            backend=default_backend()
        )
        public_key = private_key.public_key()
        return private_key, public_key

    def serialize_public_key(self, public_key):
        return public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )

    def deserialize_public_key(self, key_bytes):
        return serialization.load_pem_public_key(key_bytes, backend=default_backend())

    def recv_exact(self, sock, num_bytes):
        data = b''
        while len(data) < num_bytes:
            chunk = sock.recv(num_bytes - len(data))
            if not chunk:
                raise ConnectionError("Socket connection closed")
            data += chunk
        return data

    def exchange_keys_as_client(self, sock):
        my_public_bytes = self.serialize_public_key(self.public_key)
        sock.sendall(len(my_public_bytes).to_bytes(4, 'big'))
        sock.sendall(my_public_bytes)

        server_key_len = int.from_bytes(self.recv_exact(sock, 4), 'big')
        server_public_bytes = self.recv_exact(sock, server_key_len)
        return self.deserialize_public_key(server_public_bytes)

    def exchange_keys_as_server(self, conn):
        client_key_len = int.from_bytes(self.recv_exact(conn, 4), 'big')
        client_public_bytes = self.recv_exact(conn, client_key_len)
        client_public_key = self.deserialize_public_key(client_public_bytes)

        my_public_bytes = self.serialize_public_key(self.public_key)
        conn.sendall(len(my_public_bytes).to_bytes(4, 'big'))
        conn.sendall(my_public_bytes)

        return client_public_key

    def encrypt_with_rsa(self, data, public_key):
        return public_key.encrypt(
            data,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )

    def decrypt_with_rsa(self, encrypted_data):
        return self.private_key.decrypt(
            encrypted_data,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )

    def encrypt_large_data(self, data, public_key):
        aes_key = os.urandom(AES_KEY_SIZE)
        iv = os.urandom(16)

        cipher = Cipher(algorithms.AES(aes_key), modes.CFB(iv), backend=default_backend())
        encryptor = cipher.encryptor()
        encrypted_data = encryptor.update(data) + encryptor.finalize()

        encrypted_aes_key = self.encrypt_with_rsa(aes_key, public_key)

        result = len(encrypted_aes_key).to_bytes(4, 'big')
        result += encrypted_aes_key
        result += iv
        result += encrypted_data

        return result

    def decrypt_large_data(self, encrypted_package):
        offset = 0
        encrypted_key_len = int.from_bytes(encrypted_package[offset:offset+4], 'big')
        offset += 4

        encrypted_aes_key = encrypted_package[offset:offset+encrypted_key_len]
        offset += encrypted_key_len

        aes_key = self.decrypt_with_rsa(encrypted_aes_key)

        iv = encrypted_package[offset:offset+16]
        offset += 16

        encrypted_data = encrypted_package[offset:]

        cipher = Cipher(algorithms.AES(aes_key), modes.CFB(iv), backend=default_backend())
        decryptor = cipher.decryptor()
        decrypted_data = decryptor.update(encrypted_data) + decryptor.finalize()

        return decrypted_data

    def send_message(self, message):
        try:
            message_bytes = message.encode('utf-8')

            if ENABLE_ENCRYPTION:
                data_to_send = self.encrypt_large_data(message_bytes, self.peer_public_key)
            else:
                data_to_send = message_bytes

            metadata = {
                'type': 'message',
                'size': len(data_to_send),
                'encrypted': ENABLE_ENCRYPTION
            }
            metadata_json = json.dumps(metadata).encode('utf-8')

            self.connection.sendall(len(metadata_json).to_bytes(4, 'big'))
            self.connection.sendall(metadata_json)
            self.connection.sendall(data_to_send)

            return True
        except Exception as e:
            if self.debug:
                print(f"\n[ERROR] Failed to send message: {e}")
            return False

    def send_file(self, filepath):
        try:
            if not os.path.isfile(filepath):
                print(f"\r\033[K[ERROR] {filepath} is not a valid file")
                return False

            filename = os.path.basename(filepath)

            with open(filepath, 'rb') as f:
                file_data = f.read()

            if ENABLE_ENCRYPTION:
                encrypted_data = self.encrypt_large_data(file_data, self.peer_public_key)
                data_to_send = encrypted_data
                actual_size = len(encrypted_data)
            else:
                data_to_send = file_data
                actual_size = len(file_data)

            metadata = {
                'type': 'file',
                'filename': filename,
                'filesize': actual_size,
                'original_size': len(file_data),
                'encrypted': ENABLE_ENCRYPTION
            }
            metadata_json = json.dumps(metadata).encode('utf-8')

            self.connection.sendall(len(metadata_json).to_bytes(4, 'big'))
            self.connection.sendall(metadata_json)
            self.connection.sendall(data_to_send)

            print(f"\r\033[K[FILE SENT] {filename} ({len(file_data)} bytes)")
            return True
        except Exception as e:
            print(f"\r\033[K[ERROR] Failed to send file: {e}")
            return False

    def send_directory(self, dirpath):
        try:
            if not os.path.isdir(dirpath):
                print(f"\r\033[K[ERROR] {dirpath} is not a valid directory")
                return False

            dirname = os.path.basename(dirpath.rstrip('/'))

            with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp:
                tmp_zip_path = tmp.name

            try:
                with zipfile.ZipFile(tmp_zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for root, dirs, files in os.walk(dirpath):
                        for file in files:
                            file_path = os.path.join(root, file)
                            arcname = os.path.join(dirname, os.path.relpath(file_path, dirpath))
                            zipf.write(file_path, arcname)

                with open(tmp_zip_path, 'rb') as f:
                    zip_data = f.read()

                if ENABLE_ENCRYPTION:
                    encrypted_data = self.encrypt_large_data(zip_data, self.peer_public_key)
                    data_to_send = encrypted_data
                    actual_size = len(encrypted_data)
                else:
                    data_to_send = zip_data
                    actual_size = len(zip_data)

                metadata = {
                    'type': 'directory',
                    'filename': f"{dirname}.zip",
                    'filesize': actual_size,
                    'original_size': len(zip_data),
                    'original_dirname': dirname,
                    'encrypted': ENABLE_ENCRYPTION
                }
                metadata_json = json.dumps(metadata).encode('utf-8')

                self.connection.sendall(len(metadata_json).to_bytes(4, 'big'))
                self.connection.sendall(metadata_json)
                self.connection.sendall(data_to_send)

                print(f"\r\033[K[DIRECTORY SENT] {dirname} ({len(zip_data)} bytes)")
                return True
            finally:
                if os.path.exists(tmp_zip_path):
                    os.remove(tmp_zip_path)
        except Exception as e:
            print(f"\r\033[K[ERROR] Failed to send directory: {e}")
            return False

    def receive_messages(self):
        try:
            while self.running:
                try:
                    metadata_len_bytes = self.recv_exact(self.connection, 4)
                    metadata_len = int.from_bytes(metadata_len_bytes, 'big')

                    metadata_json = self.recv_exact(self.connection, metadata_len)
                    metadata = json.loads(metadata_json.decode('utf-8'))

                    transfer_type = metadata.get('type', 'message')

                    if transfer_type == 'message':
                        message_size = metadata['size']
                        encrypted = metadata.get('encrypted', False)

                        message_data = self.recv_exact(self.connection, message_size)

                        if encrypted and self.private_key:
                            decrypted_bytes = self.decrypt_large_data(message_data)
                            message = decrypted_bytes.decode('utf-8')
                        else:
                            message = message_data.decode('utf-8')

                        with self.input_lock:
                            print(f"\r\033[K{self.peer_name}: {message}")
                            print(f"You: ", end='', flush=True)

                    elif transfer_type == 'file':
                        self.receive_file(metadata)

                    elif transfer_type == 'directory':
                        self.receive_directory(metadata)

                except ConnectionError:
                    break
                except Exception as e:
                    if self.debug:
                        print(f"\n[ERROR] Receive error: {e}")
                    break
        except Exception as e:
            if self.debug:
                print(f"\n[ERROR] Fatal receive error: {e}")
        finally:
            self.running = False

    def receive_file(self, metadata):
        filename = metadata['filename']
        filesize = metadata['filesize']
        encrypted = metadata.get('encrypted', False)

        try:
            # Validate file size
            validate_file_size(filesize, self.output_dir)

            # Get safe output path
            filepath = get_safe_output_path(self.output_dir, filename)

            # Receive data
            data = self.recv_exact(self.connection, filesize)

            if encrypted and self.private_key:
                data = self.decrypt_large_data(data)

            with open(filepath, 'wb') as f:
                f.write(data)

            with self.input_lock:
                print(f"\r\033[K[FILE RECEIVED] {filename} -> {filepath}")
                print(f"You: ", end='', flush=True)

        except (FileSizeError, DiskSpaceError, PathTraversalError, SecurityError) as e:
            with self.input_lock:
                print(f"\r\033[K[ERROR] File rejected: {e}")
                print(f"You: ", end='', flush=True)

    def receive_directory(self, metadata):
        filename = metadata['filename']
        filesize = metadata['filesize']
        original_dirname = metadata.get('original_dirname', 'received_directory')
        encrypted = metadata.get('encrypted', False)

        temp_zip = os.path.join(self.output_dir, filename)

        try:
            # Validate file size
            validate_file_size(filesize, self.output_dir)

            # Receive data
            data = self.recv_exact(self.connection, filesize)

            if encrypted and self.private_key:
                data = self.decrypt_large_data(data)

            with open(temp_zip, 'wb') as f:
                f.write(data)

            # Determine target path, auto-suffixing if it already exists
            extract_path = os.path.join(self.output_dir, original_dirname)
            counter = 1
            while os.path.exists(extract_path):
                extract_path = os.path.join(self.output_dir, f"{original_dirname}_{counter}")
                counter += 1

            # Extract into a staging dir so we can rename to the unique target
            staging_dir = tempfile.mkdtemp(dir=self.output_dir, prefix='.extract_')
            try:
                safe_extract_zip(temp_zip, staging_dir)

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

            with self.input_lock:
                print(f"\r\033[K[DIRECTORY RECEIVED] {original_dirname} -> {extract_path}")
                print(f"You: ", end='', flush=True)

        except ZipBombError as e:
            with self.input_lock:
                print(f"\r\033[K[ZIP BOMB DETECTED] {e}")
                print("Transfer rejected for security reasons.")
                print(f"You: ", end='', flush=True)
        except (FileSizeError, DiskSpaceError, PathTraversalError, SecurityError) as e:
            with self.input_lock:
                print(f"\r\033[K[SECURITY ERROR] {e}")
                print(f"You: ", end='', flush=True)
        finally:
            # Always remove temporary zip file
            if os.path.exists(temp_zip):
                os.remove(temp_zip)

    def send_messages(self):
        print("\n--- Commands ---")
        print("/file <path>  - Send a file")
        print("/dir <path>   - Send a directory")
        print("/help         - Show this help")
        print("----------------\n")
        print(f"You: ", end='', flush=True)
        try:
            while self.running:
                try:
                    with self.input_lock:
                        message = input()

                    if not self.running:
                        break

                    if not message.strip():
                        print(f"You: ", end='', flush=True)
                        continue

                    if message.startswith('/file '):
                        filepath = message[6:].strip()
                        filepath = os.path.expanduser(filepath)
                        self.send_file(filepath)
                        print(f"You: ", end='', flush=True)

                    elif message.startswith('/dir '):
                        dirpath = message[5:].strip()
                        dirpath = os.path.expanduser(dirpath)
                        self.send_directory(dirpath)
                        print(f"You: ", end='', flush=True)

                    elif message == '/help':
                        print("\r\033[K--- Commands ---")
                        print("/file <path>  - Send a file")
                        print("/dir <path>   - Send a directory")
                        print("/help         - Show this help")
                        print("----------------")
                        print(f"You: ", end='', flush=True)

                    else:
                        if not self.send_message(message):
                            print("Failed to send message")
                            break
                        print(f"You: ", end='', flush=True)

                except EOFError:
                    break
                except KeyboardInterrupt:
                    break
        except Exception as e:
            if self.debug:
                print(f"\n[ERROR] Send error: {e}")
        finally:
            self.running = False

    def run_as_server(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(('0.0.0.0', self.port))
            s.listen(1)

            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as temp_s:
                    temp_s.connect(('8.8.8.8', 80))
                    local_ip = temp_s.getsockname()[0]
            except Exception:
                local_ip = "Unable to determine"

            print(f"Server IP Address: {local_ip}")
            print(f"Listening on port {self.port}...")
            print(f"Files will be saved to: {self.output_dir}")
            print("Waiting for connection...\n")

            conn, addr = s.accept()
            self.connection = conn
            self.peer_name = f"Peer ({addr[0]})"

            with conn:
                print(f"Connected to {addr}")

                if ENABLE_ENCRYPTION:
                    print("Exchanging encryption keys...")
                    self.peer_public_key = self.exchange_keys_as_server(conn)
                    print("Secure connection established")

                print("\n=== Chat Started ===")
                print("Type your messages below (Ctrl+C to quit)\n")

                receive_thread = threading.Thread(target=self.receive_messages, daemon=True)
                receive_thread.start()

                self.send_messages()

                receive_thread.join(timeout=1)

        print("\n\n=== Chat Ended ===")

    def run_as_client(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            print(f"Connecting to {self.host}:{self.port}...")
            s.connect((self.host, self.port))
            self.connection = s
            self.peer_name = f"Peer ({self.host})"

            print(f"Connected to {self.host}")

            if ENABLE_ENCRYPTION:
                print("Exchanging encryption keys...")
                self.peer_public_key = self.exchange_keys_as_client(s)
                print("Secure connection established")

            print("\n=== Chat Started ===")
            print("Type your messages below (Ctrl+C to quit)\n")

            receive_thread = threading.Thread(target=self.receive_messages, daemon=True)
            receive_thread.start()

            self.send_messages()

            receive_thread.join(timeout=1)

        print("\n\n=== Chat Ended ===")

    def run(self):
        try:
            if self.mode == 'server':
                self.run_as_server()
            else:
                self.run_as_client()
        except KeyboardInterrupt:
            print("\n\nDisconnecting...")
            self.running = False
        except Exception as e:
            print(f"\n\nError: {e}")
            self.running = False


def main():
    parser = argparse.ArgumentParser(
        description='Bidirectional TCP chat application with file transfer',
        epilog='Examples:\n'
               '  %(prog)s                           # Start as host (listen for connections)\n'
               '  %(prog)s --connect 192.168.1.100   # Connect to a host\n',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('--connect', '-c', metavar='HOST', help='Connect to specified host IP address')
    parser.add_argument('--port', '-p', type=int, default=PORT, help=f'Port number (default: {PORT})')
    parser.add_argument('--output', '-o', help='Output directory for received files (default: Desktop)')
    parser.add_argument('--debug', '-d', action='store_true', help='Enable debug mode')

    args = parser.parse_args()

    global DEBUG_MODE
    DEBUG_MODE = args.debug

    # Determine mode based on --connect flag
    if args.connect:
        mode = 'client'
        host = args.connect
    else:
        mode = 'server'
        host = None

    chat = BidirectionalChat(
        mode=mode,
        host=host,
        port=args.port,
        debug=args.debug,
        output_dir=args.output
    )

    chat.run()


if __name__ == "__main__":
    main()
