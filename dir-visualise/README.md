# dir-visualise (`dv`)

Prints a directory as a tree (`├──`, `└──`, `│`) with `ls`-style flags.

## Usage

```bash
python3 dv.py [directory] [flags]
```

Defaults: top level only, names only, alphabetical, hidden entries excluded.

## Flags

Mirrors `ls` semantics:

- `-a` / `-A` — include hidden entries
- `-l` — long format (perms, links, owner, group, size, mtime)
- `-h` — human-readable sizes (only with `-l`)
- `-r` — reverse sort
- `-t` — sort by modification time, newest first
- `-S` — sort by size, largest first
- `-1` — one entry per line (no-op for tree output)
- `-F` — append classifier (`/`, `*`, `@`, `|`, `=`)
- `-p` — append `/` to directories only
- `-d` — list the directory itself, not its contents

## Recursion

`-R` differs from `ls`: it accepts an optional integer to cap depth.

- `-R` — recurse with no limit
- `-R N` — recurse at most `N` levels (e.g. `-R 2`)
- `-L N` — alias for `-R N`

Without `-R`, only the top level is shown.

## Example

```bash
dv ~/projects -lh -R 2
```
