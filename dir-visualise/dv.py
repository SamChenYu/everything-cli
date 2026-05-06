#!/usr/bin/env python3
"""Directory visualiser: prints a tree of a directory with ls-style flags."""

from __future__ import annotations

import argparse
import os
import stat
import sys
import time
from dataclasses import dataclass
from pathlib import Path


BRANCH = "├── "
LAST_BRANCH = "└── "
PIPE = "│   "
SPACE = "    "


@dataclass
class Entry:
    path: Path
    name: str
    is_dir: bool
    is_link: bool
    size: int
    mtime: float
    mode: int
    nlink: int
    uid: int
    gid: int


def stat_entry(path: Path) -> Entry | None:
    try:
        st = path.lstat()
    except OSError:
        return None
    return Entry(
        path=path,
        name=path.name,
        is_dir=stat.S_ISDIR(st.st_mode),
        is_link=stat.S_ISLNK(st.st_mode),
        size=st.st_size,
        mtime=st.st_mtime,
        mode=st.st_mode,
        nlink=st.st_nlink,
        uid=st.st_uid,
        gid=st.st_gid,
    )


def list_dir(directory: Path, args: argparse.Namespace) -> list[Entry]:
    try:
        names = os.listdir(directory)
    except OSError as e:
        print(f"dv: cannot access '{directory}': {e}", file=sys.stderr)
        return []

    if not (args.all or args.almost_all):
        names = [n for n in names if not n.startswith(".")]

    entries: list[Entry] = []
    for name in names:
        e = stat_entry(directory / name)
        if e is not None:
            entries.append(e)

    if args.sort_size:
        entries.sort(key=lambda e: (-e.size, e.name.lower()))
    elif args.sort_time:
        entries.sort(key=lambda e: (-e.mtime, e.name.lower()))
    else:
        entries.sort(key=lambda e: e.name.lower())

    if args.reverse:
        entries.reverse()

    return entries


def human_size(size: int) -> str:
    units = ["B", "K", "M", "G", "T", "P"]
    s = float(size)
    for u in units:
        if s < 1024 or u == units[-1]:
            if u == "B":
                return f"{int(s)}{u}"
            return f"{s:.1f}{u}"
        s /= 1024
    return f"{size}B"


def mode_string(mode: int) -> str:
    if stat.S_ISDIR(mode):
        t = "d"
    elif stat.S_ISLNK(mode):
        t = "l"
    elif stat.S_ISFIFO(mode):
        t = "p"
    elif stat.S_ISSOCK(mode):
        t = "s"
    elif stat.S_ISBLK(mode):
        t = "b"
    elif stat.S_ISCHR(mode):
        t = "c"
    else:
        t = "-"
    perms = ""
    for who in ("USR", "GRP", "OTH"):
        for what in ("R", "W", "X"):
            bit = getattr(stat, f"S_I{what}{who}")
            perms += what.lower() if mode & bit else "-"
    return t + perms


def owner_name(uid: int) -> str:
    try:
        import pwd
        return pwd.getpwuid(uid).pw_name
    except (ImportError, KeyError):
        return str(uid)


def group_name(gid: int) -> str:
    try:
        import grp
        return grp.getgrgid(gid).gr_name
    except (ImportError, KeyError):
        return str(gid)


def size_str(e: Entry, args: argparse.Namespace) -> str:
    return human_size(e.size) if args.human else str(e.size)


@dataclass
class LongWidths:
    nlink: int = 0
    owner: int = 0
    group: int = 0
    size: int = 0


def long_format(e: Entry, args: argparse.Namespace, widths: LongWidths | None = None) -> str:
    """Format entry like `ls -l`: mode links owner group size mtime."""
    w = widths or LongWidths()
    owner = owner_name(e.uid)
    group = group_name(e.gid)
    size = size_str(e, args)
    nlink_w = max(w.nlink, 2)
    owner_w = max(w.owner, len(owner))
    group_w = max(w.group, len(group))
    size_w = max(w.size, 7)
    mtime = time.strftime("%b %e %H:%M", time.localtime(e.mtime))
    return (
        f"{mode_string(e.mode)} {e.nlink:>{nlink_w}} "
        f"{owner:<{owner_w}} {group:<{group_w}} "
        f"{size:>{size_w}} {mtime}  "
    )


def classifier(e: Entry, args: argparse.Namespace) -> str:
    """Suffix added to names by -F or -p."""
    if args.classify:
        if e.is_dir:
            return "/"
        if e.is_link:
            return "@"
        if stat.S_ISFIFO(e.mode):
            return "|"
        if stat.S_ISSOCK(e.mode):
            return "="
        if not e.is_dir and (e.mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)):
            return "*"
    elif args.slash and e.is_dir:
        return "/"
    return ""


def display_name(e: Entry, args: argparse.Namespace) -> str:
    name = e.name + classifier(e, args)
    if e.is_link:
        try:
            target = os.readlink(e.path)
            return f"{name} -> {target}"
        except OSError:
            return name
    return name


def render_line(
    e: Entry,
    prefix: str,
    connector: str,
    args: argparse.Namespace,
    widths: LongWidths | None = None,
) -> str:
    meta = long_format(e, args, widths) if args.long else ""
    return f"{meta}{prefix}{connector}{display_name(e, args)}"


def walk(
    directory: Path, prefix: str, args: argparse.Namespace, depth: int
) -> tuple[list[tuple[Entry, str, str]], int, int]:
    """Collect (entry, prefix, connector) tuples for every line, plus counts.

    Rendering happens in a second pass so columns can be width-aligned across
    the whole tree.
    """
    if args.max_depth is not None and depth > args.max_depth:
        return [], 0, 0

    entries = list_dir(directory, args)
    nodes: list[tuple[Entry, str, str]] = []
    dir_count = 0
    file_count = 0

    for i, e in enumerate(entries):
        is_last = i == len(entries) - 1
        connector = LAST_BRANCH if is_last else BRANCH
        nodes.append((e, prefix, connector))

        if e.is_dir and not e.is_link:
            dir_count += 1
            extension = SPACE if is_last else PIPE
            sub_nodes, sub_dirs, sub_files = walk(e.path, prefix + extension, args, depth + 1)
            nodes.extend(sub_nodes)
            dir_count += sub_dirs
            file_count += sub_files
        else:
            file_count += 1

    return nodes, dir_count, file_count


def compute_long_widths(
    nodes: list[tuple[Entry, str, str]], args: argparse.Namespace
) -> LongWidths:
    w = LongWidths()
    for e, _, _ in nodes:
        w.nlink = max(w.nlink, len(str(e.nlink)))
        w.owner = max(w.owner, len(owner_name(e.uid)))
        w.group = max(w.group, len(group_name(e.gid)))
        w.size = max(w.size, len(size_str(e, args)))
    return w


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="dv",
        description="Visualise a directory as a tree, with ls-like options.",
        add_help=False,
    )
    p.add_argument("directory", nargs="?", default=".", help="directory to visualise (default: .)")
    p.add_argument("-a", "--all", action="store_true", help="include hidden entries")
    p.add_argument("-A", "--almost-all", action="store_true", help="include hidden entries except '.' and '..'")
    p.add_argument("-l", dest="long", action="store_true", help="long format: perms, links, owner, group, size, mtime")
    p.add_argument("-h", "--human", action="store_true", help="human-readable sizes (with -l)")
    p.add_argument("-r", "--reverse", action="store_true", help="reverse sort order")
    p.add_argument("-t", dest="sort_time", action="store_true", help="sort by modification time, newest first")
    p.add_argument("-S", dest="sort_size", action="store_true", help="sort by size, largest first")
    p.add_argument("-1", dest="one", action="store_true", help="one entry per line (no-op for tree output)")
    p.add_argument("-F", "--classify", action="store_true", help="append indicator (one of */=>@|) to entries")
    p.add_argument("-p", dest="slash", action="store_true", help="append / to directory names")
    p.add_argument("-d", "--directory-only", action="store_true", help="list the directory itself, not its contents")
    p.add_argument(
        "-R",
        "--recursive",
        nargs="?",
        const=-1,
        default=None,
        type=int,
        metavar="N",
        help="recurse into subdirectories; optional N caps depth (e.g. -R 2)",
    )
    p.add_argument("-L", "--max-depth", type=int, default=None, help="alias for -R N")
    p.add_argument("--help", action="help", help="show this help message and exit")
    args = p.parse_args(argv)

    if args.max_depth is not None:
        depth = args.max_depth
    elif args.recursive is None:
        depth = 1
    elif args.recursive == -1:
        depth = None
    else:
        depth = args.recursive
    args.max_depth = depth
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.directory in (".", "./"):
        args.directory = os.getcwd()

    root = Path(args.directory)

    if not root.exists():
        print(f"dv: '{root}' does not exist", file=sys.stderr)
        return 1

    print("\n" * 2, end="")

    if args.directory_only or not root.is_dir():
        e = stat_entry(root)
        if e is None:
            print(f"dv: cannot stat '{root}'", file=sys.stderr)
            return 1
        e = Entry(**{**e.__dict__, "name": str(root)})
        widths = compute_long_widths([(e, "", "")], args) if args.long else None
        print(render_line(e, prefix="", connector="", args=args, widths=widths))
        print("\n" * 2, end="")
        return 0

    header = str(root) + classifier(stat_entry(root), args) if args.classify or args.slash else str(root)
    print(header)
    nodes, dirs, files = walk(root, "", args, depth=1)
    widths = compute_long_widths(nodes, args) if args.long else None
    for e, prefix, connector in nodes:
        print(render_line(e, prefix, connector, args, widths))
    print(f"\n{dirs} director{'y' if dirs == 1 else 'ies'}, {files} file{'' if files == 1 else 's'}")
    print("\n" * 2, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
