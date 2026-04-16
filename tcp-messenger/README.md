# TCP Messenger

Basic TCP messenger and file transfer tool. Sends plain text messages or files over TCP sockets.

**Security Warning:** Do not send anything sensitive. This tool does not use encryption. Security features may be added in the future.

## Features

- Send text messages between computers
- Send individual files
- Send entire directories (automatically zipped)
- Received files default to Desktop location
- Cross-platform support (Windows, macOS, Linux)

## Usage

### Receiving (Server)

Start the receiver first:

```bash
python3 receive.py
```

This will:
- Display the server's IP address
- Listen for incoming connections on port 9999
- Save received files to Desktop by default

**Options:**
- `--output DIR` or `-o DIR`: Specify a custom directory for received files

Example:
```bash
python3 receive.py --output ~/Downloads
```

### Sending (Client)

#### Send text messages:

```bash
python3 send.py
```

Enter the receiver's IP address and start typing messages.

**Options:**
- `--host IP` or `-H IP`: Specify receiver IP without prompting

#### Send a file:

```bash
python3 send.py --file /path/to/file.txt
```

or using the short flag:

```bash
python3 send.py -f document.pdf
```

#### Send a directory:

```bash
python3 send.py --file /path/to/directory
```

The directory will be automatically zipped, sent, and extracted on the receiver's end.

#### Send with host specified:

```bash
python3 send.py --host 192.168.1.100 --file myfile.txt
```

## Examples

**Scenario 1:** Send a photo to another computer

```bash
# On receiving computer
python3 receive.py

# On sending computer (after noting the receiver's IP)
python3 send.py -f ~/Pictures/photo.jpg
```

**Scenario 2:** Send a project directory

```bash
# On receiving computer
python3 receive.py -o ~/Projects

# On sending computer
python3 send.py -H 192.168.1.50 -f ~/Documents/my-project
```

**Scenario 3:** Send text messages

```bash
# On receiving computer
python3 receive.py

# On sending computer
python3 send.py
# Enter IP and start chatting
```

## Requirements

- Python 3.6 or higher
- No external dependencies (uses only standard library)
