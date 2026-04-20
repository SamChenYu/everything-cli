#!/usr/bin/env python3
"""
Unit tests for receive.py
Tests decryption, key exchange, and receiving functionality
"""
import unittest
import socket
import os
import tempfile
import json
import zipfile
from unittest.mock import Mock, patch, MagicMock, call
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend

import receive


class TestRSAKeyGeneration(unittest.TestCase):
    """Test RSA key generation and serialization"""

    def test_generate_rsa_keypair(self):
        """Test generating RSA key pair"""
        private_key, public_key = receive.generate_rsa_keypair()

        self.assertIsNotNone(private_key)
        self.assertIsNotNone(public_key)
        self.assertEqual(private_key.key_size, receive.RSA_KEY_SIZE)

    def test_serialize_public_key(self):
        """Test public key serialization"""
        _, public_key = receive.generate_rsa_keypair()
        serialized = receive.serialize_public_key(public_key)

        self.assertIsInstance(serialized, bytes)
        self.assertIn(b'BEGIN PUBLIC KEY', serialized)

    def test_deserialize_public_key(self):
        """Test public key deserialization"""
        _, public_key = receive.generate_rsa_keypair()
        serialized = receive.serialize_public_key(public_key)
        deserialized = receive.deserialize_public_key(serialized)

        self.assertIsNotNone(deserialized)
        self.assertEqual(deserialized.key_size, public_key.key_size)


class TestDecryption(unittest.TestCase):
    """Test decryption functionality"""

    def setUp(self):
        """Set up test fixtures"""
        self.private_key, self.public_key = receive.generate_rsa_keypair()
        self.test_data = b"Hello, this is test data!"

    def test_decrypt_with_rsa(self):
        """Test RSA decryption"""
        # Encrypt data first
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives import hashes

        encrypted = self.public_key.encrypt(
            self.test_data,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )

        # Now decrypt
        decrypted = receive.decrypt_with_rsa(encrypted, self.private_key)

        self.assertEqual(decrypted, self.test_data)

    def test_decrypt_large_data(self):
        """Test hybrid decryption for large data"""
        # Manually create encrypted package structure
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives import hashes

        # Generate AES key and encrypt data
        aes_key = os.urandom(32)
        iv = os.urandom(16)

        cipher = Cipher(algorithms.AES(aes_key), modes.CFB(iv), backend=default_backend())
        encryptor = cipher.encryptor()
        encrypted_data = encryptor.update(self.test_data) + encryptor.finalize()

        # Encrypt AES key with RSA
        encrypted_aes_key = self.public_key.encrypt(
            aes_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )

        # Build package
        package = len(encrypted_aes_key).to_bytes(4, 'big')
        package += encrypted_aes_key
        package += iv
        package += encrypted_data

        # Decrypt
        decrypted = receive.decrypt_large_data(package, self.private_key)

        self.assertEqual(decrypted, self.test_data)


class TestSocketOperations(unittest.TestCase):
    """Test socket operations"""

    def test_recv_exact_success(self):
        """Test receiving exact number of bytes"""
        mock_sock = Mock()
        test_data = b"Hello World!"
        mock_sock.recv.return_value = test_data

        result = receive.recv_exact(mock_sock, len(test_data))

        self.assertEqual(result, test_data)

    def test_recv_exact_multiple_chunks(self):
        """Test receiving data in multiple chunks"""
        mock_sock = Mock()
        mock_sock.recv.side_effect = [b"Hello", b" ", b"World!"]

        result = receive.recv_exact(mock_sock, 12)

        self.assertEqual(result, b"Hello World!")
        self.assertEqual(mock_sock.recv.call_count, 3)

    def test_recv_exact_connection_closed(self):
        """Test handling of closed connection"""
        mock_sock = Mock()
        mock_sock.recv.return_value = b""

        with self.assertRaises(ConnectionError):
            receive.recv_exact(mock_sock, 100)


class TestKeyExchange(unittest.TestCase):
    """Test key exchange functionality"""

    def setUp(self):
        """Set up test fixtures"""
        self.private_key, self.public_key = receive.generate_rsa_keypair()
        self.client_private, self.client_public = receive.generate_rsa_keypair()

    @patch('receive.recv_exact')
    def test_exchange_keys(self, mock_recv_exact):
        """Test successful key exchange"""
        mock_conn = Mock()
        client_public_bytes = receive.serialize_public_key(self.client_public)

        # Mock receiving client's key
        mock_recv_exact.side_effect = [
            len(client_public_bytes).to_bytes(4, 'big'),
            client_public_bytes
        ]

        result = receive.exchange_keys(mock_conn, self.public_key)

        self.assertIsNotNone(result)
        self.assertEqual(result.key_size, self.client_public.key_size)

        # Verify server sent its key
        self.assertEqual(mock_conn.sendall.call_count, 2)


class TestGetDesktopPath(unittest.TestCase):
    """Test desktop path detection"""

    @patch('platform.system', return_value='Darwin')
    def test_get_desktop_path_mac(self, mock_system):
        """Test getting desktop path on macOS"""
        desktop = receive.get_desktop_path()
        self.assertIn('Desktop', desktop)

    @patch('platform.system', return_value='Windows')
    def test_get_desktop_path_windows(self, mock_system):
        """Test getting desktop path on Windows"""
        desktop = receive.get_desktop_path()
        self.assertIn('Desktop', desktop)

    @patch('platform.system', return_value='Linux')
    @patch('os.path.isdir', return_value=True)
    def test_get_desktop_path_linux(self, mock_isdir, mock_system):
        """Test getting desktop path on Linux"""
        desktop = receive.get_desktop_path()
        self.assertIn('Desktop', desktop)

    @patch('platform.system', return_value='Unknown')
    def test_get_desktop_path_unknown_os(self, mock_system):
        """Test getting desktop path on unknown OS"""
        desktop = receive.get_desktop_path()
        self.assertIsNotNone(desktop)


class TestReceiveFile(unittest.TestCase):
    """Test file receiving functionality"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.private_key, self.public_key = receive.generate_rsa_keypair()
        self.test_data = b"Test file content for receiving"

    def tearDown(self):
        """Clean up temporary directory"""
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_receive_file_unencrypted(self):
        """Test receiving unencrypted file"""
        mock_conn = Mock()
        mock_conn.recv.return_value = self.test_data

        metadata = {
            'filename': 'test.txt',
            'filesize': len(self.test_data),
            'encrypted': False
        }

        filepath = receive.receive_file(mock_conn, metadata, self.temp_dir)

        self.assertTrue(os.path.exists(filepath))
        with open(filepath, 'rb') as f:
            content = f.read()
        self.assertEqual(content, self.test_data)

    def test_receive_file_duplicate_name(self):
        """Test handling duplicate filenames"""
        # Create existing file
        existing_file = os.path.join(self.temp_dir, 'test.txt')
        with open(existing_file, 'w') as f:
            f.write("existing")

        mock_conn = Mock()
        mock_conn.recv.return_value = self.test_data

        metadata = {
            'filename': 'test.txt',
            'filesize': len(self.test_data),
            'encrypted': False
        }

        filepath = receive.receive_file(mock_conn, metadata, self.temp_dir)

        # Should create file with different name
        self.assertNotEqual(filepath, existing_file)
        self.assertTrue(os.path.exists(filepath))
        self.assertIn('test_1.txt', filepath)

    @patch('receive.decrypt_large_data')
    def test_receive_file_encrypted(self, mock_decrypt):
        """Test receiving encrypted file"""
        encrypted_data = b"encrypted_content"
        mock_decrypt.return_value = self.test_data

        mock_conn = Mock()
        mock_conn.recv.return_value = encrypted_data

        metadata = {
            'filename': 'encrypted.txt',
            'filesize': len(encrypted_data),
            'encrypted': True
        }

        filepath = receive.receive_file(mock_conn, metadata, self.temp_dir, self.private_key)

        # Verify decryption was called
        mock_decrypt.assert_called_once_with(encrypted_data, self.private_key)

        # Verify file was saved with decrypted content
        self.assertTrue(os.path.exists(filepath))
        with open(filepath, 'rb') as f:
            content = f.read()
        self.assertEqual(content, self.test_data)


class TestReceiveDirectory(unittest.TestCase):
    """Test directory receiving functionality"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.private_key, self.public_key = receive.generate_rsa_keypair()

        # Create a zip file for testing
        self.zip_path = os.path.join(self.temp_dir, 'test.zip')
        with zipfile.ZipFile(self.zip_path, 'w') as zipf:
            zipf.writestr('testdir/file1.txt', 'Content 1')
            zipf.writestr('testdir/file2.txt', 'Content 2')

        with open(self.zip_path, 'rb') as f:
            self.zip_data = f.read()

        os.remove(self.zip_path)

    def tearDown(self):
        """Clean up temporary directory"""
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_receive_directory_unencrypted(self):
        """Test receiving unencrypted directory"""
        mock_conn = Mock()
        mock_conn.recv.return_value = self.zip_data

        metadata = {
            'filename': 'testdir.zip',
            'filesize': len(self.zip_data),
            'original_dirname': 'testdir',
            'encrypted': False
        }

        receive.receive_directory(mock_conn, metadata, self.temp_dir)

        # Verify directory was extracted
        extracted_dir = os.path.join(self.temp_dir, 'testdir')
        self.assertTrue(os.path.exists(os.path.join(extracted_dir, 'file1.txt')))
        self.assertTrue(os.path.exists(os.path.join(extracted_dir, 'file2.txt')))

    @patch('receive.decrypt_large_data')
    def test_receive_directory_encrypted(self, mock_decrypt):
        """Test receiving encrypted directory"""
        encrypted_data = b"encrypted_zip_content"
        mock_decrypt.return_value = self.zip_data

        mock_conn = Mock()
        mock_conn.recv.return_value = encrypted_data

        metadata = {
            'filename': 'testdir.zip',
            'filesize': len(encrypted_data),
            'original_dirname': 'testdir',
            'encrypted': True
        }

        receive.receive_directory(mock_conn, metadata, self.temp_dir, self.private_key)

        # Verify decryption was called
        mock_decrypt.assert_called_once()

        # Verify directory was extracted
        extracted_dir = os.path.join(self.temp_dir, 'testdir')
        self.assertTrue(os.path.exists(os.path.join(extracted_dir, 'file1.txt')))


class TestReceiveMessage(unittest.TestCase):
    """Test message receiving functionality"""

    def setUp(self):
        """Set up test fixtures"""
        self.private_key, self.public_key = receive.generate_rsa_keypair()

    @patch('receive.recv_exact')
    def test_receive_message_unencrypted(self, mock_recv_exact):
        """Test receiving unencrypted message"""
        test_message = "Hello, World!"
        message_bytes = test_message.encode('utf-8')

        mock_conn = Mock()
        mock_recv_exact.return_value = message_bytes

        metadata = {
            'size': len(message_bytes),
            'encrypted': False
        }

        with patch('builtins.print'):
            receive.receive_message(mock_conn, metadata, self.private_key)

        mock_recv_exact.assert_called_once_with(mock_conn, len(message_bytes))

    @patch('receive.recv_exact')
    @patch('receive.decrypt_large_data')
    def test_receive_message_encrypted(self, mock_decrypt, mock_recv_exact):
        """Test receiving encrypted message"""
        test_message = "Secret message"
        encrypted_data = b"encrypted_message_data"

        mock_recv_exact.return_value = encrypted_data
        mock_decrypt.return_value = test_message.encode('utf-8')

        mock_conn = Mock()

        metadata = {
            'size': len(encrypted_data),
            'encrypted': True
        }

        with patch('builtins.print'):
            receive.receive_message(mock_conn, metadata, self.private_key)

        mock_decrypt.assert_called_once_with(encrypted_data, self.private_key)


class TestMainFunction(unittest.TestCase):
    """Test main function and server loop"""

    @patch('receive.generate_rsa_keypair')
    @patch('socket.socket')
    @patch('sys.argv', ['receive.py', '--output', '/tmp/test'])
    def test_main_with_custom_output(self, mock_socket, mock_keygen):
        """Test main function with custom output directory"""
        receive.ENABLE_ENCRYPTION = True
        mock_keygen.return_value = (Mock(), Mock())

        mock_server = MagicMock()
        mock_socket.return_value.__enter__.return_value = mock_server
        mock_server.accept.side_effect = KeyboardInterrupt()

        receive.main()

        mock_server.bind.assert_called_once()

    @patch('receive.generate_rsa_keypair')
    @patch('sys.argv', ['receive.py', '--debug'])
    def test_main_debug_mode(self, mock_keygen):
        """Test that debug mode is set correctly"""
        mock_keygen.return_value = (Mock(), Mock())

        with patch('socket.socket') as mock_socket:
            mock_server = MagicMock()
            mock_socket.return_value.__enter__.return_value = mock_server
            mock_server.accept.side_effect = KeyboardInterrupt()

            receive.main()

        self.assertTrue(receive.DEBUG_MODE)

    @patch('receive.os.makedirs')
    @patch('receive.os.path.exists', return_value=False)
    @patch('receive.generate_rsa_keypair')
    @patch('socket.socket')
    @patch('sys.argv', ['receive.py', '--output', '/custom/path'])
    def test_main_creates_output_dir(self, mock_socket, mock_keygen, mock_exists, mock_makedirs):
        """Test that output directory is created if it doesn't exist"""
        mock_keygen.return_value = (Mock(), Mock())
        mock_server = MagicMock()
        mock_socket.return_value.__enter__.return_value = mock_server
        mock_server.accept.side_effect = KeyboardInterrupt()

        receive.main()

        mock_makedirs.assert_called_once()


class TestServerLoop(unittest.TestCase):
    """Test server connection handling"""

    @patch('receive.receive_file')
    @patch('receive.exchange_keys')
    @patch('receive.recv_exact')
    def test_server_handles_file_transfer(self, mock_recv_exact, mock_exchange, mock_receive_file):
        """Test server correctly routes file transfer"""
        metadata = {
            'type': 'file',
            'filename': 'test.txt',
            'filesize': 100,
            'encrypted': False
        }
        metadata_json = json.dumps(metadata).encode('utf-8')

        side_effect_list = [
            len(metadata_json).to_bytes(4, 'big'),
            metadata_json,
            b'x' * 100
        ]

        mock_recv_exact.side_effect = side_effect_list

        with tempfile.TemporaryDirectory() as temp_dir:
            mock_conn = Mock()
            mock_exchange.return_value = Mock()

            # Simulate receiving one transfer
            metadata_len_bytes = side_effect_list[0]
            metadata_len = int.from_bytes(metadata_len_bytes, 'big')
            metadata_json_data = side_effect_list[1]
            metadata_parsed = json.loads(metadata_json_data.decode('utf-8'))

            mock_receive_file(mock_conn, metadata_parsed, temp_dir, None)

            mock_receive_file.assert_called_once()


if __name__ == '__main__':
    unittest.main()
