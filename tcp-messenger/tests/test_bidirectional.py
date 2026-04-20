#!/usr/bin/env python3
"""
Unit tests for bidirectional.py
Tests bidirectional chat functionality with encryption and file transfers
"""
import unittest
import socket
import os
import tempfile
import json
import threading
import time
from unittest.mock import Mock, patch, MagicMock, call
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend

import bidirectional


class TestBidirectionalChatInit(unittest.TestCase):
    """Test BidirectionalChat initialization"""

    def test_init_server_mode(self):
        """Test initialization in server mode"""
        with patch('bidirectional.BidirectionalChat.generate_rsa_keypair') as mock_gen:
            mock_gen.return_value = (Mock(), Mock())

            chat = bidirectional.BidirectionalChat(
                mode='server',
                port=9999,
                debug=False
            )

            self.assertEqual(chat.mode, 'server')
            self.assertEqual(chat.port, 9999)
            self.assertFalse(chat.debug)
            self.assertTrue(chat.running)

    def test_init_client_mode(self):
        """Test initialization in client mode"""
        with patch('bidirectional.BidirectionalChat.generate_rsa_keypair') as mock_gen:
            mock_gen.return_value = (Mock(), Mock())

            chat = bidirectional.BidirectionalChat(
                mode='client',
                host='192.168.1.100',
                port=9999,
                debug=True
            )

            self.assertEqual(chat.mode, 'client')
            self.assertEqual(chat.host, '192.168.1.100')
            self.assertTrue(chat.debug)

    @patch('os.makedirs')
    @patch('os.path.exists', return_value=False)
    def test_init_creates_output_dir(self, mock_exists, mock_makedirs):
        """Test that output directory is created"""
        with patch('bidirectional.BidirectionalChat.generate_rsa_keypair') as mock_gen:
            mock_gen.return_value = (Mock(), Mock())

            temp_dir = '/tmp/test_output'
            chat = bidirectional.BidirectionalChat(
                mode='server',
                output_dir=temp_dir
            )

            mock_makedirs.assert_called_once_with(temp_dir)

    def test_init_with_encryption_disabled(self):
        """Test initialization with encryption disabled"""
        bidirectional.ENABLE_ENCRYPTION = False

        chat = bidirectional.BidirectionalChat(mode='server')

        self.assertIsNone(chat.private_key)
        self.assertIsNone(chat.public_key)

        bidirectional.ENABLE_ENCRYPTION = True


class TestKeyOperations(unittest.TestCase):
    """Test cryptographic key operations"""

    def setUp(self):
        """Set up test fixtures"""
        with patch('bidirectional.BidirectionalChat.generate_rsa_keypair') as mock_gen:
            self.private_key, self.public_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048,
                backend=default_backend()
            ), None
            mock_gen.return_value = (self.private_key, self.private_key.public_key())

            self.chat = bidirectional.BidirectionalChat(mode='server')

    def test_generate_rsa_keypair(self):
        """Test RSA key pair generation"""
        private_key, public_key = self.chat.generate_rsa_keypair()

        self.assertIsNotNone(private_key)
        self.assertIsNotNone(public_key)
        self.assertEqual(private_key.key_size, bidirectional.RSA_KEY_SIZE)

    def test_serialize_deserialize_public_key(self):
        """Test public key serialization and deserialization"""
        _, public_key = self.chat.generate_rsa_keypair()

        serialized = self.chat.serialize_public_key(public_key)
        deserialized = self.chat.deserialize_public_key(serialized)

        self.assertEqual(public_key.key_size, deserialized.key_size)

    def test_encrypt_decrypt_with_rsa(self):
        """Test RSA encryption and decryption"""
        test_data = b"Test data for RSA"

        encrypted = self.chat.encrypt_with_rsa(test_data, self.chat.public_key)
        decrypted = self.chat.decrypt_with_rsa(encrypted)

        self.assertEqual(decrypted, test_data)

    def test_encrypt_decrypt_large_data(self):
        """Test hybrid encryption and decryption"""
        test_data = b"A" * 10000

        encrypted = self.chat.encrypt_large_data(test_data, self.chat.public_key)
        decrypted = self.chat.decrypt_large_data(encrypted)

        self.assertEqual(decrypted, test_data)


class TestSocketOperations(unittest.TestCase):
    """Test socket operations"""

    def setUp(self):
        """Set up test fixtures"""
        with patch('bidirectional.BidirectionalChat.generate_rsa_keypair') as mock_gen:
            mock_gen.return_value = (Mock(), Mock())
            self.chat = bidirectional.BidirectionalChat(mode='server')

    def test_recv_exact(self):
        """Test receiving exact number of bytes"""
        mock_sock = Mock()
        test_data = b"Hello World!"
        mock_sock.recv.return_value = test_data

        result = self.chat.recv_exact(mock_sock, len(test_data))

        self.assertEqual(result, test_data)

    def test_recv_exact_multiple_chunks(self):
        """Test receiving data in chunks"""
        mock_sock = Mock()
        mock_sock.recv.side_effect = [b"Hello", b" ", b"World!"]

        result = self.chat.recv_exact(mock_sock, 12)

        self.assertEqual(result, b"Hello World!")

    def test_recv_exact_connection_closed(self):
        """Test handling closed connection"""
        mock_sock = Mock()
        mock_sock.recv.return_value = b""

        with self.assertRaises(ConnectionError):
            self.chat.recv_exact(mock_sock, 100)


class TestKeyExchange(unittest.TestCase):
    """Test key exchange operations"""

    def setUp(self):
        """Set up test fixtures"""
        with patch('bidirectional.BidirectionalChat.generate_rsa_keypair') as mock_gen:
            self.private_key, self.public_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048,
                backend=default_backend()
            ), None
            self.public_key = self.private_key.public_key()
            mock_gen.return_value = (self.private_key, self.public_key)

            self.chat = bidirectional.BidirectionalChat(mode='server')

    def test_exchange_keys_as_client(self):
        """Test client-side key exchange"""
        mock_sock = Mock()
        server_private, server_public = self.chat.generate_rsa_keypair()
        server_public_bytes = self.chat.serialize_public_key(server_public)

        # Mock receiving server's key
        def recv_exact_side_effect(sock, num_bytes):
            if num_bytes == 4:
                return len(server_public_bytes).to_bytes(4, 'big')
            else:
                return server_public_bytes

        self.chat.recv_exact = Mock(side_effect=recv_exact_side_effect)

        result = self.chat.exchange_keys_as_client(mock_sock)

        self.assertIsNotNone(result)
        self.assertEqual(mock_sock.sendall.call_count, 2)

    def test_exchange_keys_as_server(self):
        """Test server-side key exchange"""
        mock_conn = Mock()
        client_private, client_public = self.chat.generate_rsa_keypair()
        client_public_bytes = self.chat.serialize_public_key(client_public)

        # Mock receiving client's key
        def recv_exact_side_effect(sock, num_bytes):
            if num_bytes == 4:
                return len(client_public_bytes).to_bytes(4, 'big')
            else:
                return client_public_bytes

        self.chat.recv_exact = Mock(side_effect=recv_exact_side_effect)

        result = self.chat.exchange_keys_as_server(mock_conn)

        self.assertIsNotNone(result)
        self.assertEqual(mock_conn.sendall.call_count, 2)


class TestSendMessage(unittest.TestCase):
    """Test message sending functionality"""

    def setUp(self):
        """Set up test fixtures"""
        with patch('bidirectional.BidirectionalChat.generate_rsa_keypair') as mock_gen:
            private_key, public_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048,
                backend=default_backend()
            ), None
            public_key = private_key.public_key()
            mock_gen.return_value = (private_key, public_key)

            self.chat = bidirectional.BidirectionalChat(mode='client', host='localhost')
            self.chat.connection = Mock()
            self.chat.peer_public_key = public_key

    def test_send_message_success(self):
        """Test successful message sending"""
        bidirectional.ENABLE_ENCRYPTION = False
        test_message = "Hello, World!"

        result = self.chat.send_message(test_message)

        self.assertTrue(result)
        self.assertGreater(self.chat.connection.sendall.call_count, 0)

    def test_send_message_encrypted(self):
        """Test sending encrypted message"""
        bidirectional.ENABLE_ENCRYPTION = True
        test_message = "Secret message"

        result = self.chat.send_message(test_message)

        self.assertTrue(result)
        self.assertGreater(self.chat.connection.sendall.call_count, 0)

    def test_send_message_connection_error(self):
        """Test handling connection error during send"""
        self.chat.connection.sendall.side_effect = Exception("Connection lost")

        result = self.chat.send_message("Test")

        self.assertFalse(result)


class TestSendFile(unittest.TestCase):
    """Test file sending functionality"""

    def setUp(self):
        """Set up test fixtures"""
        with patch('bidirectional.BidirectionalChat.generate_rsa_keypair') as mock_gen:
            private_key, public_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048,
                backend=default_backend()
            ), None
            public_key = private_key.public_key()
            mock_gen.return_value = (private_key, public_key)

            self.chat = bidirectional.BidirectionalChat(mode='client', host='localhost')
            self.chat.connection = Mock()
            self.chat.peer_public_key = public_key

        # Create temporary test file
        self.temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False)
        self.temp_file.write("Test file content")
        self.temp_file.close()

    def tearDown(self):
        """Clean up temporary file"""
        if os.path.exists(self.temp_file.name):
            os.remove(self.temp_file.name)

    def test_send_file_success(self):
        """Test successful file sending"""
        bidirectional.ENABLE_ENCRYPTION = False

        result = self.chat.send_file(self.temp_file.name)

        self.assertTrue(result)
        self.assertGreater(self.chat.connection.sendall.call_count, 0)

    def test_send_file_invalid_path(self):
        """Test sending non-existent file"""
        with patch('builtins.print'):
            result = self.chat.send_file('/nonexistent/file.txt')

        self.assertFalse(result)

    def test_send_file_encrypted(self):
        """Test sending encrypted file"""
        bidirectional.ENABLE_ENCRYPTION = True

        result = self.chat.send_file(self.temp_file.name)

        self.assertTrue(result)


class TestSendDirectory(unittest.TestCase):
    """Test directory sending functionality"""

    def setUp(self):
        """Set up test fixtures"""
        with patch('bidirectional.BidirectionalChat.generate_rsa_keypair') as mock_gen:
            private_key, public_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048,
                backend=default_backend()
            ), None
            public_key = private_key.public_key()
            mock_gen.return_value = (private_key, public_key)

            self.chat = bidirectional.BidirectionalChat(mode='client', host='localhost')
            self.chat.connection = Mock()
            self.chat.peer_public_key = public_key

        # Create temporary test directory
        self.temp_dir = tempfile.mkdtemp()
        with open(os.path.join(self.temp_dir, 'file1.txt'), 'w') as f:
            f.write("File 1")
        with open(os.path.join(self.temp_dir, 'file2.txt'), 'w') as f:
            f.write("File 2")

    def tearDown(self):
        """Clean up temporary directory"""
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_send_directory_success(self):
        """Test successful directory sending"""
        bidirectional.ENABLE_ENCRYPTION = False

        result = self.chat.send_directory(self.temp_dir)

        self.assertTrue(result)
        self.assertGreater(self.chat.connection.sendall.call_count, 0)

    def test_send_directory_invalid_path(self):
        """Test sending non-existent directory"""
        with patch('builtins.print'):
            result = self.chat.send_directory('/nonexistent/directory')

        self.assertFalse(result)


class TestReceiveOperations(unittest.TestCase):
    """Test receiving functionality"""

    def setUp(self):
        """Set up test fixtures"""
        with patch('bidirectional.BidirectionalChat.generate_rsa_keypair') as mock_gen:
            private_key, public_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048,
                backend=default_backend()
            ), None
            public_key = private_key.public_key()
            mock_gen.return_value = (private_key, public_key)

            self.chat = bidirectional.BidirectionalChat(mode='server')
            self.chat.connection = Mock()
            self.chat.peer_name = "TestPeer"

    def test_receive_file(self):
        """Test receiving file"""
        temp_dir = tempfile.mkdtemp()
        self.chat.output_dir = temp_dir

        try:
            test_data = b"Test file content"
            self.chat.connection.recv.return_value = test_data

            # Mock recv_exact to return data
            self.chat.recv_exact = Mock(return_value=test_data)

            metadata = {
                'filename': 'received.txt',
                'filesize': len(test_data),
                'encrypted': False
            }

            with patch('builtins.print'):
                self.chat.receive_file(metadata)

            # Check file was created
            filepath = os.path.join(temp_dir, 'received.txt')
            self.assertTrue(os.path.exists(filepath))
        finally:
            import shutil
            shutil.rmtree(temp_dir)

    def test_receive_directory(self):
        """Test receiving directory"""
        import zipfile

        temp_dir = tempfile.mkdtemp()
        self.chat.output_dir = temp_dir

        try:
            # Create a test zip
            zip_path = os.path.join(temp_dir, 'test.zip')
            with zipfile.ZipFile(zip_path, 'w') as zipf:
                zipf.writestr('testdir/file.txt', 'Content')

            with open(zip_path, 'rb') as f:
                zip_data = f.read()

            os.remove(zip_path)

            # Mock recv_exact to return zip data
            self.chat.recv_exact = Mock(return_value=zip_data)

            metadata = {
                'filename': 'testdir.zip',
                'filesize': len(zip_data),
                'original_dirname': 'testdir',
                'encrypted': False
            }

            with patch('builtins.print'):
                self.chat.receive_directory(metadata)

            # Check directory was extracted
            self.assertTrue(os.path.exists(os.path.join(temp_dir, 'testdir', 'file.txt')))
        finally:
            import shutil
            shutil.rmtree(temp_dir)


class TestDesktopPath(unittest.TestCase):
    """Test desktop path detection"""

    def setUp(self):
        """Set up test fixtures"""
        with patch('bidirectional.BidirectionalChat.generate_rsa_keypair') as mock_gen:
            mock_gen.return_value = (Mock(), Mock())
            self.chat = bidirectional.BidirectionalChat(mode='server')

    @patch('platform.system', return_value='Darwin')
    def test_get_desktop_path_mac(self, mock_system):
        """Test getting desktop path on macOS"""
        desktop = self.chat.get_desktop_path()
        self.assertIn('Desktop', desktop)

    @patch('platform.system', return_value='Windows')
    def test_get_desktop_path_windows(self, mock_system):
        """Test getting desktop path on Windows"""
        desktop = self.chat.get_desktop_path()
        self.assertIn('Desktop', desktop)

    @patch('platform.system', return_value='Linux')
    @patch('os.path.isdir', return_value=True)
    def test_get_desktop_path_linux(self, mock_isdir, mock_system):
        """Test getting desktop path on Linux"""
        desktop = self.chat.get_desktop_path()
        self.assertIn('Desktop', desktop)


class TestMainFunction(unittest.TestCase):
    """Test main function and argument parsing"""

    @patch('bidirectional.BidirectionalChat')
    @patch('sys.argv', ['bidirectional.py', '--connect', '192.168.1.100'])
    def test_main_client_mode(self, mock_chat_class):
        """Test main function in client mode"""
        mock_chat = Mock()
        mock_chat_class.return_value = mock_chat

        bidirectional.main()

        # Verify client mode was used
        call_args = mock_chat_class.call_args
        self.assertEqual(call_args[1]['mode'], 'client')
        self.assertEqual(call_args[1]['host'], '192.168.1.100')

    @patch('bidirectional.BidirectionalChat')
    @patch('sys.argv', ['bidirectional.py'])
    def test_main_server_mode(self, mock_chat_class):
        """Test main function in server mode"""
        mock_chat = Mock()
        mock_chat_class.return_value = mock_chat

        bidirectional.main()

        # Verify server mode was used
        call_args = mock_chat_class.call_args
        self.assertEqual(call_args[1]['mode'], 'server')
        self.assertIsNone(call_args[1]['host'])

    @patch('bidirectional.BidirectionalChat')
    @patch('sys.argv', ['bidirectional.py', '--debug'])
    def test_main_debug_mode(self, mock_chat_class):
        """Test that debug mode is set correctly"""
        mock_chat = Mock()
        mock_chat_class.return_value = mock_chat

        bidirectional.main()

        self.assertTrue(bidirectional.DEBUG_MODE)

    @patch('bidirectional.BidirectionalChat')
    @patch('sys.argv', ['bidirectional.py', '--port', '8888'])
    def test_main_custom_port(self, mock_chat_class):
        """Test main function with custom port"""
        mock_chat = Mock()
        mock_chat_class.return_value = mock_chat

        bidirectional.main()

        # Verify custom port was used
        call_args = mock_chat_class.call_args
        self.assertEqual(call_args[1]['port'], 8888)


class TestThreadedOperations(unittest.TestCase):
    """Test threaded send/receive operations"""

    def setUp(self):
        """Set up test fixtures"""
        with patch('bidirectional.BidirectionalChat.generate_rsa_keypair') as mock_gen:
            mock_gen.return_value = (Mock(), Mock())
            self.chat = bidirectional.BidirectionalChat(mode='server')

    def test_receive_messages_stops_when_not_running(self):
        """Test that receive_messages stops when running is False"""
        self.chat.running = False
        self.chat.connection = Mock()

        # Should exit immediately
        self.chat.receive_messages()

        # Connection should not be used
        self.chat.connection.recv.assert_not_called()

    def test_input_lock_exists(self):
        """Test that input lock is created"""
        self.assertIsNotNone(self.chat.input_lock)
        self.assertIsInstance(self.chat.input_lock, threading.Lock)


if __name__ == '__main__':
    unittest.main()
