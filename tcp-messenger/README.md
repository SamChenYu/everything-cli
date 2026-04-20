# TCP Messenger

Secure TCP messenger and file transfer tool with end-to-end encryption. Send encrypted messages, files, and directories over TCP sockets.

## Features

- **End-to-end encryption** using RSA-2048 + AES-256
- **Bidirectional chat** with real-time two-way messaging
- Send text messages between computers
- Send files and directories during chat sessions
- One-way transfer mode for simple file/message sending
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
python -m venv .venv
source .venv/bin/activate
pip install -r requirements
```

2. Clone or download the scripts

## Usage

### Bidirectional Chat (bidirectional.py)

The bidirectional chat allows both parties to send and receive messages and files simultaneously in real-time.

#### Start as host (listen for connections):

```bash
./bidirectional.py
```

This will:
- Generate RSA encryption keys
- Display the host's IP address
- Listen for incoming connections on port 9999
- Wait for someone to connect

#### Connect to a host:

```bash
./bidirectional.py --connect 192.168.1.100
```

Or using the short flag:

```bash
./bidirectional.py -c 192.168.1.100
```

Once connected, both parties can:
- Send text messages in real-time
- Send files with `/file <path>`
- Send directories with `/dir <path>`
- Type `/help` to see available commands

**Options:**
- `--connect HOST` or `-c HOST`: Connect to specified host IP address
- `--port PORT` or `-p PORT`: Use custom port (default: 9999)
- `--output DIR` or `-o DIR`: Specify directory for received files (default: Desktop)
- `--debug` or `-d`: Enable debug mode

**In-Chat Commands:**
```
/file ~/Documents/report.pdf   - Send a file
/dir ~/Projects/myapp          - Send a directory
/help                          - Show help
```

**Example Session:**

```bash
# Machine 1 (host)
./bidirectional.py
# Shows: Server IP Address: 192.168.1.100

# Machine 2 (connect)
./bidirectional.py -c 192.168.1.100
```

Once connected:
```
You: Hello!
Peer: Hi there!
You: /file report.pdf
[FILE SENT] report.pdf (1024 bytes)
Peer: Thanks, got it!
```

### One-Way Transfer Mode

For simple one-way message/file sending without bidirectional chat, use the original scripts:

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

**Scenario 1:** Real-time chat between two computers

```bash
# Computer 1 (host)
./bidirectional.py

# Computer 2 (connect to the IP shown by Computer 1)
./bidirectional.py -c 192.168.1.100
```

Both can now chat and send files in real-time.

**Scenario 2:** Send files during a chat session

```bash
# In the chat window
You: Hey, check out this document
You: /file ~/Documents/report.pdf
[FILE SENT] report.pdf (52480 bytes)
You: /dir ~/Projects/website
[DIRECTORY SENT] website (1048576 bytes)
Peer: Got them, thanks!
```

**Scenario 3:** One-way file transfer (no chat needed)

```bash
# On receiving computer
python3 receive.py

# On sending computer (after noting the receiver's IP)
python3 send.py -f ~/Pictures/photo.jpg
```

**Scenario 4:** One-way encrypted project directory transfer

```bash
# On receiving computer
python3 receive.py -o ~/Projects

# On sending computer
python3 send.py -H 192.168.1.50 -f ~/Documents/my-project
```

**Scenario 5:** Debug mode to troubleshoot encryption

```bash
# Bidirectional chat with debug
./bidirectional.py --debug
./bidirectional.py -c 192.168.1.100 --debug

# One-way transfer with debug
python3 receive.py --debug
python3 send.py --host 192.168.1.100 --debug
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

### Bidirectional Chat (bidirectional.py)

1. **Connection**: Host listens, client connects
2. **Key Exchange**: Both parties exchange RSA public keys
3. **Threading**: Separate threads handle sending and receiving simultaneously
4. **Encryption**: All messages and files encrypted with RSA-2048 + AES-256
5. **Real-time**: Messages appear instantly, files transfer in background

### One-Way Transfer (send.py / receive.py)

1. **Key Exchange**: When a connection is established, both parties exchange RSA public keys
2. **Encryption**:
   - Small messages: Encrypted directly with RSA-2048
   - Large files: Encrypted with AES-256, then the AES key is encrypted with RSA
3. **Transfer**: Encrypted data is sent over TCP with metadata (type, size, etc.)
4. **Decryption**: Receiver decrypts the data using their private key
5. **Save**: Decrypted files/messages are saved or displayed

## Testing

This project includes comprehensive unit tests for all three main components.

### Running Tests

Run all tests (109 total):
```bash
python3 run_tests.py
```

Run tests with verbose output:
```bash
python3 run_tests.py --verbose
```

Run specific test file:
```bash
python3 run_tests.py test_send.py
python3 run_tests.py test_receive.py
python3 run_tests.py test_bidirectional.py
python3 run_tests.py test_security.py  # Security tests
```

Or use unittest directly:
```bash
python3 -m unittest discover -s . -p "test_*.py"
```

### Test Coverage

**109 total tests** covering:
- RSA key generation and serialization
- Hybrid encryption (AES-256 + RSA-2048)
- Socket communication and data transfer
- File and directory transfers
- Message sending and receiving
- Error handling and edge cases
- Multi-platform support
- Thread synchronization
- **Security vulnerabilities (buffer overflow, zip bombs, etc.)**

See `TEST_DOCUMENTATION.md` for detailed test coverage information.

### ⚠️ Security Findings

Security testing discovered vulnerabilities:
- 🔴 **CRITICAL:** Zip bomb vulnerability (no compression ratio validation)
- 🟡 **MEDIUM:** No file size limits
- 🟡 **MEDIUM:** Path traversal partially mitigated
- 🟡 **MEDIUM:** No connection rate limiting

See `SECURITY_FINDINGS.md` for complete vulnerability report and recommended fixes.

**Important:** This tool is intended for trusted networks. Do not expose directly to the internet without implementing the recommended security fixes.

## Troubleshooting

**Port already in use:**
The server now properly releases the port on shutdown. If you still see this error, wait a few seconds or use `lsof -i :9999` to find and kill the process.

**Connection refused:**
Make sure the receiver is running first and check firewall settings.

**Encryption errors:**
Enable `--debug` mode on both ends to see detailed encryption/decryption logs.
