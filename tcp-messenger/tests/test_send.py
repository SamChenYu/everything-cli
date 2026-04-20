#!/usr/bin/env python3
"""
Unit tests for send.py
Tests encryption, key exchange, and sending functionality
"""
import unittest
import socket
import os
import tempfile
import json
from unittest.mock import Mock, patch, MagicMock, call
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend

import send


class TestRSAKeyGeneration(unittest.TestCase):
    """Test RSA key generation and serialization"""

    def test_generate_rsa_keypair(self):
        """Test generating RSA key pair"""
        private_key, public_key = send.generate_rsa_keypair()

        self.assertIsNotNone(private_key)
        self.assertIsNotNone(public_key)
        self.assertEqual(private_key.key_size, send.RSA_KEY_SIZE)

    def test_serialize_public_key(self):
        """Test public key serialization"""
        _, public_key = send.generate_rsa_keypair()
        serialized = send.serialize_public_key(public_key)

        self.assertIsInstance(serialized, bytes)
        self.assertIn(b'BEGIN PUBLIC KEY', serialized)
        self.assertIn(b'END PUBLIC KEY', serialized)

    def test_deserialize_public_key(self):
        """Test public key deserialization"""
        _, public_key = send.generate_rsa_keypair()
        serialized = send.serialize_public_key(public_key)
        deserialized = send.deserialize_public_key(serialized)

        self.assertIsNotNone(deserialized)
        self.assertEqual(deserialized.key_size, public_key.key_size)

    def test_serialize_deserialize_roundtrip(self):
        """Test that serialization and deserialization are reversible"""
        _, public_key = send.generate_rsa_keypair()
        serialized = send.serialize_public_key(public_key)
        deserialized = send.deserialize_public_key(serialized)

        reserialized = send.serialize_public_key(deserialized)
        self.assertEqual(serialized, reserialized)


class TestEncryption(unittest.TestCase):
    """Test encryption functionality"""

    def setUp(self):
        """Set up test fixtures"""
        self.private_key, self.public_key = send.generate_rsa_keypair()
        self.test_data = b"Hello, this is test data!"

    def test_encrypt_with_rsa(self):
        """Test RSA encryption"""
        encrypted = send.encrypt_with_rsa(self.test_data, self.public_key)

        self.assertIsInstance(encrypted, bytes)
        self.assertNotEqual(encrypted, self.test_data)
        self.assertGreater(len(encrypted), 0)

    def test_encrypt_large_data(self):
        """Test hybrid encryption for large data"""
        large_data = b"A" * 10000
        encrypted = send.encrypt_large_data(large_data, self.public_key)

        self.assertIsInstance(encrypted, bytes)
        self.assertNotEqual(encrypted, large_data)
        self.assertGreater(len(encrypted), len(large_data))

    def test_encrypt_large_data_structure(self):
        """Test that encrypted large data has correct structure"""
        data = b"Test data for structure validation"
        encrypted = send.encrypt_large_data(data, self.public_key)

        # Check structure: 4 bytes length + encrypted_key + 16 bytes IV + encrypted_data
        self.assertGreater(len(encrypted), 4 + 16)

        # Extract key length
        key_len = int.from_bytes(encrypted[:4], 'big')
        self.assertGreater(key_len, 0)
        self.assertLess(key_len, 1000)  # Reasonable upper bound

    def test_encrypt_empty_data(self):
        """Test encrypting empty data"""
        empty_data = b""
        encrypted = send.encrypt_large_data(empty_data, self.public_key)

        self.assertIsInstance(encrypted, bytes)
        self.assertGreater(len(encrypted), 0)


class TestSocketOperations(unittest.TestCase):
    """Test socket operations"""

    def test_recv_exact_success(self):
        """Test receiving exact number of bytes"""
        mock_sock = Mock()
        test_data = b"Hello World!"
        mock_sock.recv.return_value = test_data

        result = send.recv_exact(mock_sock, len(test_data))

        self.assertEqual(result, test_data)
        mock_sock.recv.assert_called_once()

    def test_recv_exact_multiple_chunks(self):
        """Test receiving data in multiple chunks"""
        mock_sock = Mock()
        # Simulate receiving data in chunks
        mock_sock.recv.side_effect = [b"Hello", b" ", b"World!"]

        result = send.recv_exact(mock_sock, 12)

        self.assertEqual(result, b"Hello World!")
        self.assertEqual(mock_sock.recv.call_count, 3)

    def test_recv_exact_connection_closed(self):
        """Test handling of closed connection"""
        mock_sock = Mock()
        mock_sock.recv.return_value = b""

        with self.assertRaises(ConnectionError):
            send.recv_exact(mock_sock, 100)

    def test_recv_exact_partial_then_closed(self):
        """Test receiving partial data then connection closes"""
        mock_sock = Mock()
        mock_sock.recv.side_effect = [b"Hello", b""]

        with self.assertRaises(ConnectionError):
            send.recv_exact(mock_sock, 100)


class TestKeyExchange(unittest.TestCase):
    """Test key exchange functionality"""

    def setUp(self):
        """Set up test fixtures"""
        self.private_key, self.public_key = send.generate_rsa_keypair()
        self.server_private, self.server_public = send.generate_rsa_keypair()

    @patch('send.recv_exact')
    def test_exchange_keys(self, mock_recv_exact):
        """Test successful key exchange"""
        mock_sock = Mock()
        server_public_bytes = send.serialize_public_key(self.server_public)

        # Mock receiving server's key
        mock_recv_exact.side_effect = [
            len(server_public_bytes).to_bytes(4, 'big'),
            server_public_bytes
        ]

        result = send.exchange_keys(mock_sock, self.public_key)

        self.assertIsNotNone(result)
        self.assertEqual(result.key_size, self.server_public.key_size)

        # Verify client sent its key
        self.assertEqual(mock_sock.sendall.call_count, 2)


class TestSendFile(unittest.TestCase):
    """Test file sending functionality"""

    def setUp(self):
        """Create temporary test file"""
        self.temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False)
        self.temp_file.write("Test file content for unit testing")
        self.temp_file.close()

        self.private_key, self.public_key = send.generate_rsa_keypair()

    def tearDown(self):
        """Clean up temporary file"""
        if os.path.exists(self.temp_file.name):
            os.remove(self.temp_file.name)

    @patch('send.exchange_keys')
    @patch('socket.socket')
    def test_send_file_with_encryption(self, mock_socket, mock_exchange):
        """Test sending file with encryption enabled"""
        send.ENABLE_ENCRYPTION = True

        mock_conn = MagicMock()
        mock_socket.return_value.__enter__.return_value = mock_conn
        mock_exchange.return_value = self.public_key

        send.send_file('localhost', self.temp_file.name, self.private_key, self.public_key)

        # Verify connection was made
        mock_conn.connect.assert_called_once()

        # Verify data was sent
        self.assertGreater(mock_conn.sendall.call_count, 0)

        # Verify key exchange occurred
        mock_exchange.assert_called_once()

    @patch('socket.socket')
    def test_send_file_without_encryption(self, mock_socket):
        """Test sending file without encryption"""
        send.ENABLE_ENCRYPTION = False

        mock_conn = MagicMock()
        mock_socket.return_value.__enter__.return_value = mock_conn

        send.send_file('localhost', self.temp_file.name)

        # Verify connection was made
        mock_conn.connect.assert_called_once()

        # Verify data was sent
        self.assertGreater(mock_conn.sendall.call_count, 0)

    def test_send_file_invalid_path(self):
        """Test sending non-existent file"""
        with patch('builtins.print') as mock_print:
            send.send_file('localhost', '/nonexistent/file.txt')
            mock_print.assert_called()

    @patch('send.exchange_keys')
    @patch('socket.socket')
    def test_send_file_metadata(self, mock_socket, mock_exchange):
        """Test that file metadata is sent correctly"""
        send.ENABLE_ENCRYPTION = False

        mock_conn = MagicMock()
        mock_socket.return_value.__enter__.return_value = mock_conn

        send.send_file('localhost', self.temp_file.name)

        # Find the metadata send call
        calls = mock_conn.sendall.call_args_list
        self.assertGreater(len(calls), 1)

        # Second call should be metadata JSON
        metadata_call = calls[1][0][0]
        metadata = json.loads(metadata_call.decode('utf-8'))

        self.assertEqual(metadata['type'], 'file')
        self.assertIn('filename', metadata)
        self.assertIn('filesize', metadata)


class TestSendDirectory(unittest.TestCase):
    """Test directory sending functionality"""

    def setUp(self):
        """Create temporary test directory"""
        self.temp_dir = tempfile.mkdtemp()

        # Create some test files
        with open(os.path.join(self.temp_dir, 'file1.txt'), 'w') as f:
            f.write("File 1 content")

        with open(os.path.join(self.temp_dir, 'file2.txt'), 'w') as f:
            f.write("File 2 content")

        self.private_key, self.public_key = send.generate_rsa_keypair()

    def tearDown(self):
        """Clean up temporary directory"""
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    @patch('send.exchange_keys')
    @patch('socket.socket')
    def test_send_directory(self, mock_socket, mock_exchange):
        """Test sending directory as zip"""
        send.ENABLE_ENCRYPTION = False

        mock_conn = MagicMock()
        mock_socket.return_value.__enter__.return_value = mock_conn

        send.send_directory('localhost', self.temp_dir)

        # Verify connection was made
        mock_conn.connect.assert_called_once()

        # Verify data was sent
        self.assertGreater(mock_conn.sendall.call_count, 0)

    def test_send_directory_invalid_path(self):
        """Test sending non-existent directory"""
        with patch('builtins.print') as mock_print:
            send.send_directory('localhost', '/nonexistent/directory')
            mock_print.assert_called()

    @patch('send.exchange_keys')
    @patch('socket.socket')
    def test_send_directory_metadata(self, mock_socket, mock_exchange):
        """Test that directory metadata is sent correctly"""
        send.ENABLE_ENCRYPTION = False

        mock_conn = MagicMock()
        mock_socket.return_value.__enter__.return_value = mock_conn

        send.send_directory('localhost', self.temp_dir)

        # Find the metadata send call
        calls = mock_conn.sendall.call_args_list
        self.assertGreater(len(calls), 1)

        # Second call should be metadata JSON
        metadata_call = calls[1][0][0]
        metadata = json.loads(metadata_call.decode('utf-8'))

        self.assertEqual(metadata['type'], 'directory')
        self.assertIn('filename', metadata)
        self.assertIn('original_dirname', metadata)


class TestSendMessage(unittest.TestCase):
    """Test message sending functionality"""

    def setUp(self):
        """Set up test fixtures"""
        self.private_key, self.public_key = send.generate_rsa_keypair()

    @patch('builtins.input', side_effect=['Hello', 'World', KeyboardInterrupt()])
    @patch('send.exchange_keys')
    @patch('socket.socket')
    def test_send_message_loop(self, mock_socket, mock_exchange, mock_input):
        """Test sending multiple messages in a loop"""
        send.ENABLE_ENCRYPTION = False

        mock_conn = MagicMock()
        mock_socket.return_value.__enter__.return_value = mock_conn
        mock_exchange.return_value = self.public_key

        send.send_message('localhost', self.private_key, self.public_key)

        # Should have connected twice (once per message)
        self.assertEqual(mock_conn.connect.call_count, 2)

    @patch('builtins.input', return_value='')
    @patch('socket.socket')
    def test_send_empty_message(self, mock_socket, mock_input):
        """Test that empty messages are not sent"""
        send.ENABLE_ENCRYPTION = False

        mock_conn = MagicMock()
        mock_socket.return_value.__enter__.return_value = mock_conn

        # Simulate one empty input then exit
        mock_input.side_effect = ['', KeyboardInterrupt()]

        send.send_message('localhost')

        # Connection should not be attempted for empty message
        self.assertEqual(mock_conn.connect.call_count, 0)


class TestMainFunction(unittest.TestCase):
    """Test main function and argument parsing"""

    @patch('send.send_file')
    @patch('send.generate_rsa_keypair')
    @patch('sys.argv', ['send.py', '--file', 'test.txt', '--host', 'localhost'])
    def test_main_file_mode(self, mock_keygen, mock_send_file):
        """Test main function in file mode"""
        send.ENABLE_ENCRYPTION = True
        mock_keygen.return_value = (Mock(), Mock())

        with patch('os.path.isfile', return_value=True):
            send.main()

        mock_send_file.assert_called_once()

    @patch('send.send_message')
    @patch('send.generate_rsa_keypair')
    @patch('sys.argv', ['send.py', '--host', 'localhost'])
    def test_main_message_mode(self, mock_keygen, mock_send_msg):
        """Test main function in message mode"""
        send.ENABLE_ENCRYPTION = True
        mock_keygen.return_value = (Mock(), Mock())

        send.main()

        mock_send_msg.assert_called_once()

    @patch('send.generate_rsa_keypair')
    @patch('sys.argv', ['send.py', '--debug', '--host', 'localhost'])
    def test_main_debug_mode(self, mock_keygen):
        """Test that debug mode is set correctly"""
        mock_keygen.return_value = (Mock(), Mock())

        with patch('send.send_message'):
            send.main()

        self.assertTrue(send.DEBUG_MODE)


if __name__ == '__main__':
    unittest.main()
