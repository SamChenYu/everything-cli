#!/usr/bin/env python3
"""
Security utilities for TCP Messenger
Provides safe file handling, path validation, and resource limits
"""
import os
import zipfile


# Security Configuration
MAX_FILE_SIZE = 1024 * 1024 * 1024  # 1GB max file size
MAX_ZIP_SIZE = 100 * 1024 * 1024    # 100MB max uncompressed zip contents
MAX_COMPRESSION_RATIO = 50           # 50x max compression ratio
MIN_DISK_SPACE_PERCENT = 0.1        # Keep 10% disk space free


class SecurityError(Exception):
    """Base exception for security violations"""
    pass


class ZipBombError(SecurityError):
    """Raised when a zip bomb is detected"""
    pass


class FileSizeError(SecurityError):
    """Raised when file size exceeds limits"""
    pass


class DiskSpaceError(SecurityError):
    """Raised when insufficient disk space"""
    pass


class PathTraversalError(SecurityError):
    """Raised when path traversal is detected"""
    pass


def validate_file_size(filesize, output_dir='.'):
    """
    Validate file size is within limits and disk space is available

    Args:
        filesize: Size of file in bytes
        output_dir: Directory where file will be saved

    Raises:
        FileSizeError: If file is too large
        DiskSpaceError: If insufficient disk space
    """
    if filesize > MAX_FILE_SIZE:
        raise FileSizeError(
            f"File too large: {filesize:,} bytes (max: {MAX_FILE_SIZE:,} bytes)"
        )

    # Check available disk space
    try:
        stat = os.statvfs(output_dir)
        available_bytes = stat.f_bavail * stat.f_frsize
        required_bytes = filesize * 1.1  # Add 10% safety margin

        if required_bytes > available_bytes * (1 - MIN_DISK_SPACE_PERCENT):
            raise DiskSpaceError(
                f"Insufficient disk space: need {required_bytes:,} bytes, "
                f"have {available_bytes:,} bytes available"
            )
    except AttributeError:
        # Windows doesn't have statvfs, skip disk check
        pass

    return True


def safe_extract_zip(zip_path, output_dir):
    """
    Safely extract zip file with protection against zip bombs

    Args:
        zip_path: Path to zip file
        output_dir: Directory to extract to

    Returns:
        Total size of extracted files in bytes

    Raises:
        ZipBombError: If zip bomb is detected
        FileSizeError: If uncompressed size exceeds limit
        PathTraversalError: If zip contains dangerous paths
    """
    with zipfile.ZipFile(zip_path, 'r') as zipf:
        # Calculate total uncompressed size
        total_size = sum(info.file_size for info in zipf.filelist)

        # Check absolute size limit
        if total_size > MAX_ZIP_SIZE:
            raise FileSizeError(
                f"Zip contents too large: {total_size:,} bytes "
                f"(max: {MAX_ZIP_SIZE:,} bytes)"
            )

        # Check compression ratio (zip bomb detection)
        compressed_size = os.path.getsize(zip_path)
        if compressed_size > 0:
            ratio = total_size / compressed_size
            if ratio > MAX_COMPRESSION_RATIO:
                raise ZipBombError(
                    f"Potential zip bomb detected: compression ratio {ratio:.1f}x "
                    f"(max: {MAX_COMPRESSION_RATIO}x)"
                )

        # Validate each file path for path traversal
        output_dir_abs = os.path.abspath(output_dir)
        for info in zipf.filelist:
            # Get the full path where file would be extracted
            extract_path = os.path.abspath(os.path.join(output_dir, info.filename))

            # Check for path traversal
            if not extract_path.startswith(output_dir_abs + os.sep):
                raise PathTraversalError(
                    f"Path traversal detected in zip: {info.filename}"
                )

            # Check for absolute paths
            if os.path.isabs(info.filename):
                raise PathTraversalError(
                    f"Absolute path not allowed in zip: {info.filename}"
                )

            # Check for parent directory references
            if '..' in info.filename.split(os.sep):
                raise PathTraversalError(
                    f"Parent directory reference not allowed: {info.filename}"
                )

        # Check disk space before extraction
        validate_file_size(total_size, output_dir)

        # All checks passed - safe to extract
        zipf.extractall(output_dir)

        return total_size


def safe_filepath(output_dir, filename):
    """
    Create safe filepath with validation against path traversal

    Args:
        output_dir: Base directory for file
        filename: Requested filename

    Returns:
        Safe absolute filepath

    Raises:
        PathTraversalError: If path traversal detected
        ValueError: If filename is invalid
    """
    # Strip directory components
    safe_name = os.path.basename(filename)

    # Remove dangerous control characters
    safe_name = safe_name.replace('\x00', '').replace('\n', '').replace('\r', '')
    safe_name = safe_name.replace('\t', '')

    # Check for empty or invalid filename
    if not safe_name or safe_name in ('.', '..'):
        raise ValueError(f"Invalid filename: '{filename}'")

    # Build path
    filepath = os.path.abspath(os.path.join(output_dir, safe_name))
    output_dir_abs = os.path.abspath(output_dir)

    # Verify path is within output directory
    if not filepath.startswith(output_dir_abs + os.sep):
        raise PathTraversalError(
            f"Path traversal detected: '{filename}' -> '{filepath}'"
        )

    return filepath


def get_safe_output_path(output_dir, filename):
    """
    Get safe output path, handling duplicate filenames

    Args:
        output_dir: Base directory
        filename: Desired filename

    Returns:
        Safe filepath that doesn't exist (may have _N suffix)
    """
    filepath = safe_filepath(output_dir, filename)

    # Handle duplicate filenames
    if os.path.exists(filepath):
        base, ext = os.path.splitext(filepath)
        counter = 1
        while os.path.exists(f"{base}_{counter}{ext}"):
            counter += 1
        filepath = f"{base}_{counter}{ext}"

    return filepath


def print_security_info():
    """Print current security configuration"""
    print("Security Configuration:")
    print(f"  Max file size: {MAX_FILE_SIZE / (1024*1024*1024):.1f} GB")
    print(f"  Max zip uncompressed: {MAX_ZIP_SIZE / (1024*1024):.1f} MB")
    print(f"  Max compression ratio: {MAX_COMPRESSION_RATIO}x")
    print(f"  Min free disk space: {MIN_DISK_SPACE_PERCENT * 100:.0f}%")
