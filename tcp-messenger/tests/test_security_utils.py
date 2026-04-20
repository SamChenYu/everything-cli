#!/usr/bin/env python3
"""
Tests for security_utils module
Verifies zip bomb protection and security features
"""
import unittest
import os
import tempfile
import zipfile
import shutil

from security_utils import (
    safe_extract_zip, validate_file_size, safe_filepath, get_safe_output_path,
    ZipBombError, FileSizeError, DiskSpaceError, PathTraversalError,
    MAX_FILE_SIZE, MAX_ZIP_SIZE, MAX_COMPRESSION_RATIO
)


class TestValidateFileSize(unittest.TestCase):
    """Test file size validation"""

    def test_normal_file_size(self):
        """Test that normal file sizes pass validation"""
        # 10MB should be fine
        size = 10 * 1024 * 1024
        self.assertTrue(validate_file_size(size))

    def test_max_file_size(self):
        """Test file at maximum allowed size"""
        # Just under max should pass
        size = MAX_FILE_SIZE - 1
        self.assertTrue(validate_file_size(size))

    def test_oversized_file(self):
        """Test that oversized files are rejected"""
        # Over max should fail
        size = MAX_FILE_SIZE + 1
        with self.assertRaises(FileSizeError) as cm:
            validate_file_size(size)
        self.assertIn("too large", str(cm.exception))

    def test_extremely_large_file(self):
        """Test that extremely large files are rejected"""
        # 1TB should definitely fail
        size = 1024 * 1024 * 1024 * 1024
        with self.assertRaises(FileSizeError):
            validate_file_size(size)


class TestZipBombProtection(unittest.TestCase):
    """Test zip bomb detection and prevention"""

    def setUp(self):
        """Create temporary directory for tests"""
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up temporary directory"""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_normal_zip_extraction(self):
        """Test that normal zip files extract successfully"""
        zip_path = os.path.join(self.temp_dir, 'normal.zip')

        # Create a normal zip with reasonable compression
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            zipf.writestr('file1.txt', 'Hello World')
            zipf.writestr('file2.txt', 'Test content')

        # Should extract without issues
        size = safe_extract_zip(zip_path, self.temp_dir)
        self.assertGreater(size, 0)

        # Verify files were extracted
        self.assertTrue(os.path.exists(os.path.join(self.temp_dir, 'file1.txt')))
        self.assertTrue(os.path.exists(os.path.join(self.temp_dir, 'file2.txt')))

    def test_zip_bomb_detection(self):
        """Test that zip bombs are detected and blocked"""
        zip_path = os.path.join(self.temp_dir, 'bomb.zip')

        # Create a zip bomb (highly compressible data)
        # 10MB of zeros compresses to ~10KB
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            zipf.writestr('bomb.txt', b'\x00' * (10 * 1024 * 1024))

        # Should raise ZipBombError
        with self.assertRaises(ZipBombError) as cm:
            safe_extract_zip(zip_path, self.temp_dir)

        # Verify error message mentions compression ratio
        self.assertIn("compression ratio", str(cm.exception).lower())
        self.assertIn("zip bomb", str(cm.exception).lower())

        # Verify bomb was NOT extracted
        self.assertFalse(os.path.exists(os.path.join(self.temp_dir, 'bomb.txt')))

    def test_large_but_legitimate_zip(self):
        """Test that large legitimate zips are handled correctly"""
        zip_path = os.path.join(self.temp_dir, 'large.zip')

        # Create a zip with many small files (realistic compression)
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for i in range(100):
                zipf.writestr(f'file{i}.txt', f'Content {i}' * 100)

        # Should work if under size limits
        compressed_size = os.path.getsize(zip_path)
        total_size = sum(info.file_size for info in zipfile.ZipFile(zip_path).filelist)
        ratio = total_size / compressed_size

        if ratio < MAX_COMPRESSION_RATIO and total_size < MAX_ZIP_SIZE:
            size = safe_extract_zip(zip_path, self.temp_dir)
            self.assertGreater(size, 0)
        else:
            with self.assertRaises((ZipBombError, FileSizeError)):
                safe_extract_zip(zip_path, self.temp_dir)

    def test_zip_exceeds_size_limit(self):
        """Test that zips exceeding total size are rejected"""
        zip_path = os.path.join(self.temp_dir, 'huge.zip')

        # Create zip that would exceed MAX_ZIP_SIZE when extracted
        # Use low compression to avoid triggering ratio check
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_STORED) as zipf:
            # Write just over the limit
            size = MAX_ZIP_SIZE + 1024
            zipf.writestr('huge.bin', b'x' * size)

        with self.assertRaises(FileSizeError) as cm:
            safe_extract_zip(zip_path, self.temp_dir)

        self.assertIn("too large", str(cm.exception))

    def test_path_traversal_in_zip(self):
        """Test that path traversal in zip is blocked"""
        zip_path = os.path.join(self.temp_dir, 'malicious.zip')

        # Create zip with path traversal attempt
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            zipf.writestr('../../../etc/passwd', 'malicious content')

        with self.assertRaises(PathTraversalError) as cm:
            safe_extract_zip(zip_path, self.temp_dir)

        self.assertIn("path traversal", str(cm.exception).lower())

    def test_absolute_path_in_zip(self):
        """Test that absolute paths in zip are blocked"""
        zip_path = os.path.join(self.temp_dir, 'absolute.zip')

        # Create zip with absolute path
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            zipf.writestr('/tmp/malicious.txt', 'malicious content')

        with self.assertRaises(PathTraversalError) as cm:
            safe_extract_zip(zip_path, self.temp_dir)

        self.assertIn("absolute path", str(cm.exception).lower())


class TestSafeFilepath(unittest.TestCase):
    """Test safe filepath creation"""

    def setUp(self):
        """Create temporary directory"""
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up"""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_normal_filename(self):
        """Test normal filename is handled correctly"""
        filepath = safe_filepath(self.temp_dir, 'test.txt')
        self.assertTrue(filepath.startswith(self.temp_dir))
        self.assertTrue(filepath.endswith('test.txt'))

    def test_path_traversal_blocked(self):
        """Test that path traversal attempts are blocked"""
        with self.assertRaises(PathTraversalError):
            safe_filepath(self.temp_dir, '../../../etc/passwd')

    def test_absolute_path_blocked(self):
        """Test that absolute paths are blocked"""
        # Absolute path should be converted to just filename
        filepath = safe_filepath(self.temp_dir, '/tmp/test.txt')
        self.assertTrue(filepath.startswith(self.temp_dir))
        self.assertTrue(filepath.endswith('test.txt'))
        self.assertNotIn('/tmp/', filepath)

    def test_control_characters_removed(self):
        """Test that control characters are removed"""
        filepath = safe_filepath(self.temp_dir, 'test\x00\n\r\t.txt')
        # Control characters should be stripped
        self.assertNotIn('\x00', filepath)
        self.assertNotIn('\n', filepath)
        self.assertNotIn('\r', filepath)

    def test_empty_filename_rejected(self):
        """Test that empty filename is rejected"""
        with self.assertRaises(ValueError):
            safe_filepath(self.temp_dir, '')

    def test_dot_filename_rejected(self):
        """Test that . and .. are rejected"""
        with self.assertRaises(ValueError):
            safe_filepath(self.temp_dir, '.')

        with self.assertRaises(ValueError):
            safe_filepath(self.temp_dir, '..')

    def test_directory_components_stripped(self):
        """Test that directory components are stripped"""
        filepath = safe_filepath(self.temp_dir, 'subdir/file.txt')
        # Should only use basename
        self.assertNotIn('subdir', filepath)
        self.assertTrue(filepath.endswith('file.txt'))


class TestGetSafeOutputPath(unittest.TestCase):
    """Test safe output path with duplicate handling"""

    def setUp(self):
        """Create temporary directory"""
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up"""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_new_file(self):
        """Test path for new file"""
        filepath = get_safe_output_path(self.temp_dir, 'test.txt')
        self.assertTrue(filepath.endswith('test.txt'))
        self.assertFalse(os.path.exists(filepath))

    def test_duplicate_filename(self):
        """Test that duplicate filenames get _N suffix"""
        # Create existing file
        existing = os.path.join(self.temp_dir, 'test.txt')
        with open(existing, 'w') as f:
            f.write('existing')

        # New file should get _1 suffix
        filepath = get_safe_output_path(self.temp_dir, 'test.txt')
        self.assertTrue(filepath.endswith('test_1.txt'))
        self.assertFalse(os.path.exists(filepath))

    def test_multiple_duplicates(self):
        """Test handling of multiple duplicates"""
        # Create test.txt and test_1.txt
        for i in ['', '_1', '_2']:
            path = os.path.join(self.temp_dir, f'test{i}.txt')
            with open(path, 'w') as f:
                f.write('content')

        # Should get _3 suffix
        filepath = get_safe_output_path(self.temp_dir, 'test.txt')
        self.assertTrue(filepath.endswith('test_3.txt'))


class TestIntegration(unittest.TestCase):
    """Integration tests for security features"""

    def setUp(self):
        """Create temporary directory"""
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up"""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_realistic_scenario(self):
        """Test realistic file transfer scenario"""
        # Create a normal zip
        zip_path = os.path.join(self.temp_dir, 'project.zip')
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            zipf.writestr('project/file1.py', 'print("hello")')
            zipf.writestr('project/file2.py', 'def test(): pass')
            zipf.writestr('project/README.md', '# Project\nDescription here')

        # Should extract successfully
        extract_dir = os.path.join(self.temp_dir, 'extracted')
        os.makedirs(extract_dir)

        size = safe_extract_zip(zip_path, extract_dir)
        self.assertGreater(size, 0)

        # Verify extraction
        self.assertTrue(os.path.exists(os.path.join(extract_dir, 'project', 'file1.py')))
        self.assertTrue(os.path.exists(os.path.join(extract_dir, 'project', 'file2.py')))
        self.assertTrue(os.path.exists(os.path.join(extract_dir, 'project', 'README.md')))


if __name__ == '__main__':
    unittest.main()
