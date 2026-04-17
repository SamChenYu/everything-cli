# TCP Messenger

Secure TCP messenger and file transfer tool with end-to-end encryption. Send encrypted messages, files, and directories over TCP sockets.

## Features

- **End-to-end encryption** using RSA-2048 + AES-256
- Send text messages between computers
- Send individual files
- Send entire directories (automatically zipped)
- Cross-platform support (Windows, macOS, Linux)
- Debug mode to inspect raw data
- Received files default to Desktop location

## Security

All data is encrypted by default using hybrid encryption:
- **RSA-2048** for key exchange and small messages
- **AES-256** (CFB mode) for large files and directories
- Fresh RSA keypairs generated for each session
- Can be disabled by setting `ENABLE_ENCRYPTION = False` in both scripts

## Installation

1. Install dependencies:
```bash
pip install cryptography
```

2. Clone or download the scripts

## Usage

### Receiving (Server)

Start the receiver first:

```bash
python3 receive.py
```

This will:
- Generate RSA encryption keys
- Display the server's IP address
- Listen for incoming connections on port 9999
- Save received files to Desktop by default

**Options:**
- `--output DIR` or `-o DIR`: Specify a custom directory for received files
- `--debug` or `-d`: Enable debug mode (shows raw unencrypted data and detailed logs)

Examples:
```bash
# Save files to Downloads folder
python3 receive.py --output ~/Downloads

# Run with debug mode enabled
python3 receive.py --debug
```

### Sending (Client)

#### Send text messages:

```bash
python3 send.py
```

Enter the receiver's IP address and start typing messages. Each message is encrypted before sending.

**Options:**
- `--host IP` or `-H IP`: Specify receiver IP without prompting
- `--debug` or `-d`: Enable debug mode (shows encryption details)

#### Send a file:

```bash
python3 send.py --file /path/to/file.txt
```

or using the short flag:

```bash
python3 send.py -f document.pdf
```

Files are encrypted using hybrid encryption (AES-256 for the file data, RSA-2048 for the AES key).

#### Send a directory:

```bash
python3 send.py --file /path/to/directory
```

The directory is automatically zipped, encrypted, sent, and extracted on the receiver's end.

#### Send with host specified:

```bash
python3 send.py --host 192.168.1.100 --file myfile.txt
```

## Debug Mode

Debug mode shows what's happening under the hood:

```bash
# Receiver with debug
python3 receive.py --debug

# Sender with debug
python3 send.py --host 192.168.1.100 --debug
```

Debug output includes:
- Key exchange details
- Metadata content
- Encrypted vs decrypted sizes
- Raw unencrypted message content
- All debug messages are prefixed with `[DEBUG]`

## Examples

**Scenario 1:** Send an encrypted photo to another computer

```bash
# On receiving computer
python3 receive.py

# On sending computer (after noting the receiver's IP)
python3 send.py -f ~/Pictures/photo.jpg
```

**Scenario 2:** Send an encrypted project directory

```bash
# On receiving computer
python3 receive.py -o ~/Projects

# On sending computer
python3 send.py -H 192.168.1.50 -f ~/Documents/my-project
```

**Scenario 3:** Send encrypted text messages

```bash
# On receiving computer
python3 receive.py

# On sending computer
python3 send.py -H 192.168.1.100
# Start typing encrypted messages
```

**Scenario 4:** Debug mode to troubleshoot encryption

```bash
# On receiving computer
python3 receive.py --debug

# On sending computer
python3 send.py --host 192.168.1.100 --debug
# See detailed encryption/decryption logs
```

## Configuration

You can modify these settings at the top of both scripts:

```python
ENABLE_ENCRYPTION = True  # Set to False to disable encryption
RSA_KEY_SIZE = 2048      # RSA key size (2048 or 4096)
AES_KEY_SIZE = 32        # AES-256 (32 bytes)
PORT = 9999              # Network port
```

## Requirements

- Python 3.6 or higher
- `cryptography` library (`pip install cryptography`)

## How It Works

1. **Key Exchange**: When a connection is established, both parties exchange RSA public keys
2. **Encryption**:
   - Small messages: Encrypted directly with RSA-2048
   - Large files: Encrypted with AES-256, then the AES key is encrypted with RSA
3. **Transfer**: Encrypted data is sent over TCP with metadata (type, size, etc.)
4. **Decryption**: Receiver decrypts the data using their private key
5. **Save**: Decrypted files/messages are saved or displayed

## Troubleshooting

**Port already in use:**
The server now properly releases the port on shutdown. If you still see this error, wait a few seconds or use `lsof -i :9999` to find and kill the process.

**Connection refused:**
Make sure the receiver is running first and check firewall settings.

**Encryption errors:**
Enable `--debug` mode on both ends to see detailed encryption/decryption logs.
