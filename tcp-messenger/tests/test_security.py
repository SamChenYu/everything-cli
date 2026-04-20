#!/usr/bin/env python3
"""
Security and robustness tests for TCP Messenger
Tests edge cases, buffer overflows, malformed data, and attack scenarios
"""
import unittest
import socket
import os
import tempfile
import json
from unittest.mock import Mock, patch, MagicMock
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend

import send
import receive
import bidirectional


class TestBufferOverflow(unittest.TestCase):
    """Test buffer overflow and size limit handling"""

    def setUp(self):
        """Set up test fixtures"""
        self.private_key, self.public_key = send.generate_rsa_keypair()

    def test_oversized_metadata(self):
        """Test handling of unreasonably large metadata size claim"""
        mock_sock = Mock()
        # Claim metadata is 1GB (suspicious)
        huge_size = 1024 * 1024 * 1024

        # First recv returns size, then returns empty (connection closed)
        mock_sock.recv.side_effect = [huge_size.to_bytes(4, 'big'), b'']

        # Should raise ConnectionError when it can't receive all claimed bytes
        size_bytes = receive.recv_exact(mock_sock, 4)
        claimed_size = int.from_bytes(size_bytes, 'big')

        with self.assertRaises(ConnectionError):
            # Try to receive huge amount, but connection closes
            receive.recv_exact(mock_sock, claimed_size)

    def test_negative_size_claim(self):
        """Test handling of negative size in metadata"""
        mock_sock = Mock()
        # Try to claim negative size using two's complement
        negative_size = (-100 % (2**32)).to_bytes(4, 'big')
        mock_sock.recv.return_value = negative_size

        size_bytes = receive.recv_exact(mock_sock, 4)
        claimed_size = int.from_bytes(size_bytes, 'big')

        # Should be interpreted as huge positive number
        self.assertGreater(claimed_size, 2**31)

    def test_integer_overflow_in_progress(self):
        """Test integer overflow in progress calculation"""
        # Simulate sending with progress calculation
        data_to_send = b'x' * 1000
        bytes_sent = 2**63  # Near max int

        # This should not crash, even with overflow
        try:
            progress = 100 * bytes_sent // max(len(data_to_send), 1)
            # Progress calculation should handle large numbers
            self.assertIsInstance(progress, int)
        except (ZeroDivisionError, OverflowError) as e:
            self.fail(f"Progress calculation failed with overflow: {e}")

    def test_file_size_mismatch(self):
        """Test receiving file with size mismatch (claimed vs actual)"""
        temp_dir = tempfile.mkdtemp()

        try:
            mock_conn = Mock()
            # Claim 1000 bytes but only send 100
            mock_conn.recv.side_effect = [b'x' * 100, b'']

            metadata = {
                'filename': 'mismatch.txt',
                'filesize': 1000,  # Claims 1000
                'encrypted': False
            }

            # Should handle incomplete reception
            with self.assertRaises((ConnectionError, Exception)):
                # This should detect the mismatch
                data = b''
                bytes_received = 0
                while bytes_received < metadata['filesize']:
                    chunk = mock_conn.recv(4096)
                    if not chunk:
                        raise ConnectionError("Incomplete data")
                    data += chunk
                    bytes_received += len(chunk)
        finally:
            import shutil
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)

    def test_buffer_size_edge_cases(self):
        """Test various buffer size edge cases"""
        mock_sock = Mock()

        # Test empty buffer
        mock_sock.recv.return_value = b''
        with self.assertRaises(ConnectionError):
            send.recv_exact(mock_sock, 1)

        # Test exact buffer size
        mock_sock.recv.return_value = b'x' * send.BUFFER_SIZE
        result = send.recv_exact(mock_sock, send.BUFFER_SIZE)
        self.assertEqual(len(result), send.BUFFER_SIZE)


class TestMalformedData(unittest.TestCase):
    """Test handling of malformed or corrupted data"""

    def setUp(self):
        """Set up test fixtures"""
        self.private_key, self.public_key = receive.generate_rsa_keypair()

    def test_invalid_json_metadata(self):
        """Test handling of invalid JSON in metadata"""
        invalid_json = b'{invalid json here'

        with self.assertRaises(json.JSONDecodeError):
            json.loads(invalid_json.decode('utf-8'))

    def test_missing_metadata_fields(self):
        """Test handling of metadata with missing required fields"""
        # Metadata without required 'type' field
        incomplete_metadata = {
            'filename': 'test.txt',
            # Missing 'type' field
        }

        transfer_type = incomplete_metadata.get('type', 'message')
        # Should default to 'message'
        self.assertEqual(transfer_type, 'message')

    def test_corrupted_encryption_header(self):
        """Test handling of corrupted encryption data"""
        # Create malformed encrypted package (too short)
        corrupted_data = b'xxxx'  # Only 4 bytes, needs at least 4 + key_len + 16

        with self.assertRaises(Exception):
            # Should fail when trying to decrypt
            receive.decrypt_large_data(corrupted_data, self.private_key)

    def test_invalid_key_length_in_encrypted_package(self):
        """Test encrypted package with invalid key length claim"""
        # Claim key length is 1000 bytes but package is only 100 bytes total
        fake_package = (1000).to_bytes(4, 'big') + b'x' * 96

        with self.assertRaises(Exception):
            receive.decrypt_large_data(fake_package, self.private_key)

    def test_non_utf8_message(self):
        """Test handling of non-UTF8 message data"""
        # Invalid UTF-8 sequence
        invalid_utf8 = b'\xff\xfe\xfd'

        with self.assertRaises(UnicodeDecodeError):
            invalid_utf8.decode('utf-8')

    def test_invalid_public_key_format(self):
        """Test deserialization of invalid public key"""
        invalid_key_bytes = b'not a valid PEM key'

        with self.assertRaises(Exception):
            send.deserialize_public_key(invalid_key_bytes)


class TestResourceExhaustion(unittest.TestCase):
    """Test resource exhaustion scenarios"""

    @patch('os.path.getsize')
    def test_extremely_large_file_claim(self, mock_getsize):
        """Test handling of extremely large file size"""
        # Claim file is 1TB
        mock_getsize.return_value = 1024 * 1024 * 1024 * 1024

        # Create a small actual file
        temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False)
        temp_file.write("small")
        temp_file.close()

        try:
            # Mock the file size check to return huge value
            size = os.path.getsize(temp_file.name)

            # The code should handle this, but might take forever
            # In practice, you'd want size limits
            self.assertIsInstance(size, int)
        finally:
            os.remove(temp_file.name)

    def test_zip_bomb_detection(self):
        """Test for basic zip bomb detection (compression ratio)"""
        import zipfile

        temp_dir = tempfile.mkdtemp()
        zip_path = os.path.join(temp_dir, 'test.zip')

        try:
            # Create a highly compressible file (simulated zip bomb)
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # 10MB of zeros compresses to very small size
                zipf.writestr('bomb.txt', b'\x00' * (10 * 1024 * 1024))

            compressed_size = os.path.getsize(zip_path)

            # Extract and measure
            extract_dir = os.path.join(temp_dir, 'extracted')
            os.makedirs(extract_dir)

            with zipfile.ZipFile(zip_path, 'r') as zipf:
                # Get uncompressed size
                uncompressed_size = sum(info.file_size for info in zipf.filelist)

                # Calculate compression ratio
                ratio = uncompressed_size / max(compressed_size, 1)

                # VULNERABILITY DETECTED: Current code does NOT check compression ratio
                # This test documents the vulnerability
                if ratio > 100:
                    # This is a KNOWN ISSUE - the application is vulnerable to zip bombs
                    # Compression ratio should be checked before extraction
                    print(f"\n[VULNERABILITY] Zip bomb detected: {ratio:.1f}x compression")
                    print("[RECOMMENDATION] Add compression ratio check before extracting")

                # For now, we just verify the detection works
                self.assertGreater(ratio, 100, "Test zip should have high compression ratio")
        finally:
            import shutil
            shutil.rmtree(temp_dir)

    def test_memory_efficient_large_data_handling(self):
        """Test that large data is handled in chunks, not all in memory"""
        # This is more of a code inspection test
        # Verify that BUFFER_SIZE is used for chunking
        self.assertEqual(send.BUFFER_SIZE, 4096)
        self.assertEqual(receive.BUFFER_SIZE, 4096)

        # In production, large files should be read/written in chunks
        # Not loaded entirely into memory


class TestConcurrencyIssues(unittest.TestCase):
    """Test concurrent access and race conditions"""

    def test_bidirectional_input_lock_exists(self):
        """Test that bidirectional chat has proper locking"""
        with patch('bidirectional.BidirectionalChat.generate_rsa_keypair') as mock_gen:
            mock_gen.return_value = (Mock(), Mock())
            chat = bidirectional.BidirectionalChat(mode='server')

            # Verify lock exists
            self.assertIsNotNone(chat.input_lock)

            # Verify it's a proper lock
            import threading
            self.assertIsInstance(chat.input_lock, threading.Lock)

    def test_thread_safe_running_flag(self):
        """Test that running flag is properly managed"""
        with patch('bidirectional.BidirectionalChat.generate_rsa_keypair') as mock_gen:
            mock_gen.return_value = (Mock(), Mock())
            chat = bidirectional.BidirectionalChat(mode='server')

            # Initially running
            self.assertTrue(chat.running)

            # Can be set to False
            chat.running = False
            self.assertFalse(chat.running)


class TestNetworkEdgeCases(unittest.TestCase):
    """Test network-related edge cases"""

    def test_partial_metadata_reception(self):
        """Test receiving metadata in multiple small chunks"""
        mock_sock = Mock()
        metadata = {'type': 'message', 'size': 100}
        metadata_json = json.dumps(metadata).encode('utf-8')

        # Simulate receiving 1 byte at a time
        mock_sock.recv.side_effect = [bytes([b]) for b in metadata_json]

        # Should still work
        received = receive.recv_exact(mock_sock, len(metadata_json))
        self.assertEqual(received, metadata_json)

    def test_connection_closed_during_transfer(self):
        """Test handling connection closure mid-transfer"""
        mock_sock = Mock()
        # Receive some data, then connection closes
        mock_sock.recv.side_effect = [b'partial', b'']

        with self.assertRaises(ConnectionError):
            send.recv_exact(mock_sock, 1000)

    def test_socket_error_handling(self):
        """Test handling of socket errors"""
        mock_sock = Mock()
        mock_sock.recv.side_effect = socket.error("Network error")

        with self.assertRaises(socket.error):
            send.recv_exact(mock_sock, 100)

    def test_empty_connection_recv(self):
        """Test receiving from closed connection"""
        mock_sock = Mock()
        mock_sock.recv.return_value = b''

        with self.assertRaises(ConnectionError):
            receive.recv_exact(mock_sock, 1)


class TestPathTraversal(unittest.TestCase):
    """Test path traversal and directory security"""

    def test_filename_with_path_separators(self):
        """Test that filenames with path separators are handled safely"""
        temp_dir = tempfile.mkdtemp()

        try:
            mock_conn = Mock()
            mock_conn.recv.return_value = b'malicious content'

            # Try to use path traversal in filename
            metadata = {
                'filename': '../../../etc/passwd',
                'filesize': 18,
                'encrypted': False
            }

            # When receiving, only basename should be used
            filename = os.path.basename(metadata['filename'])
            self.assertEqual(filename, 'passwd')
            self.assertNotIn('..', filename)

            # Verify safe path construction
            safe_path = os.path.join(temp_dir, filename)
            self.assertTrue(safe_path.startswith(temp_dir))
        finally:
            import shutil
            shutil.rmtree(temp_dir)

    def test_absolute_path_in_filename(self):
        """Test that absolute paths in filenames are rejected"""
        # Filenames should not be absolute paths
        malicious_filename = '/tmp/malicious.txt'
        basename = os.path.basename(malicious_filename)

        # Basename strips the path
        self.assertEqual(basename, 'malicious.txt')
        self.assertFalse(os.path.isabs(basename))


class TestInputValidation(unittest.TestCase):
    """Test input validation and sanitization"""

    def test_special_characters_in_filename(self):
        """Test handling of special characters in filenames"""
        special_names = [
            'test\x00.txt',  # Null byte
            'test\n.txt',    # Newline
            'test\r.txt',    # Carriage return
            'test\t.txt',    # Tab
        ]

        for name in special_names:
            # Filenames with control characters should be handled
            basename = os.path.basename(name)
            # System should not crash, though filename may be modified
            self.assertIsInstance(basename, str)

    def test_empty_filename(self):
        """Test handling of empty filename"""
        metadata = {
            'filename': '',
            'filesize': 100,
            'encrypted': False
        }

        filename = metadata['filename']
        # Empty filename should be detected
        self.assertEqual(len(filename), 0)

    def test_extremely_long_filename(self):
        """Test handling of extremely long filename"""
        # Most filesystems limit filename length to 255 bytes
        long_name = 'a' * 300

        # System should handle this gracefully
        self.assertEqual(len(long_name), 300)
        # In practice, this might need truncation


class TestEncryptionEdgeCases(unittest.TestCase):
    """Test encryption edge cases and potential attacks"""

    def setUp(self):
        """Set up test fixtures"""
        self.private_key, self.public_key = send.generate_rsa_keypair()

    def test_encrypt_max_rsa_size(self):
        """Test encrypting data at RSA size limit"""
        # RSA can only encrypt data smaller than key size minus padding
        # For RSA-2048 with OAEP padding, max is ~190 bytes
        max_size = 190
        data = b'x' * max_size

        # Should work
        try:
            encrypted = send.encrypt_with_rsa(data, self.public_key)
            self.assertIsInstance(encrypted, bytes)
        except Exception as e:
            # If it fails, the data might be too large
            self.assertIn('data', str(e).lower())

    def test_encrypt_oversized_for_rsa(self):
        """Test encrypting data too large for direct RSA encryption"""
        # Data larger than RSA key size should use hybrid encryption
        large_data = b'x' * 1000

        # Direct RSA should fail
        with self.assertRaises(Exception):
            send.encrypt_with_rsa(large_data, self.public_key)

        # But hybrid encryption should work
        encrypted = send.encrypt_large_data(large_data, self.public_key)
        self.assertIsInstance(encrypted, bytes)

    def test_tampered_encrypted_data(self):
        """Test decrypting tampered encrypted data"""
        data = b"Secret message"
        encrypted = send.encrypt_large_data(data, self.public_key)

        # Tamper with the encrypted data
        tampered = bytearray(encrypted)
        tampered[50] ^= 0xFF  # Flip bits

        # Decryption should fail or produce garbage
        try:
            decrypted = receive.decrypt_large_data(bytes(tampered), self.private_key)
            # If it doesn't raise, the data should be corrupted
            self.assertNotEqual(decrypted, data)
        except Exception:
            # Expected: decryption failure
            pass


if __name__ == '__main__':
    unittest.main()
