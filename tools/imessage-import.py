#!/usr/bin/env python3
"""
iMessage → Family Book Importer

Reads ~/Library/Messages/chat.db locally.
No data sent to any API or LLM.
Generates a local JSON export for review before importing.

Usage:
    python3 imessage-import.py scan          # Show stats (messages, chats, contacts)
    python3 imessage-import.py groups        # List group chats
    python3 imessage-import.py export GROUP  # Export a group chat to JSON
    python3 imessage-import.py media GROUP   # List media attachments in a group
    python3 imessage-import.py import FILE   # Import JSON into Family Book
"""

import sqlite3
import sys
import json
import os
from pathlib import Path
from datetime import datetime

CHAT_DB = os.path.expanduser("~/Library/Messages/chat.db")
ATTACHMENTS_DIR = os.path.expanduser("~/Library/Messages/Attachments")
EXPORT_DIR = os.path.expanduser("~/Dropbox/Code/family-book/data/imports")

def get_db():
    if not os.path.exists(CHAT_DB):
        print(f"chat.db not found at {CHAT_DB}")
        sys.exit(1)
    return sqlite3.connect(CHAT_DB)

def cmd_scan():
    """Show overview stats."""
    db = get_db()
    c = db.cursor()
    
    msg_count = c.execute("SELECT COUNT(*) FROM message").fetchone()[0]
    chat_count = c.execute("SELECT COUNT(*) FROM chat").fetchone()[0]
    attachment_count = c.execute("SELECT COUNT(*) FROM attachment").fetchone()[0]
    handle_count = c.execute("SELECT COUNT(*) FROM handle").fetchone()[0]
    
    # Date range
    first = c.execute("""
        SELECT datetime(date/1000000000 + 978307200, 'unixepoch', 'localtime') 
        FROM message WHERE date > 0 ORDER BY date ASC LIMIT 1
    """).fetchone()
    last = c.execute("""
        SELECT datetime(date/1000000000 + 978307200, 'unixepoch', 'localtime') 
        FROM message WHERE date > 0 ORDER BY date DESC LIMIT 1
    """).fetchone()
    
    # Attachment types
    types = c.execute("""
        SELECT mime_type, COUNT(*) as cnt FROM attachment 
        WHERE mime_type IS NOT NULL 
        GROUP BY mime_type ORDER BY cnt DESC LIMIT 10
    """).fetchall()
    
    print(f"\n📱 iMessage Database Stats")
    print(f"{'='*40}")
    print(f"Messages:     {msg_count:,}")
    print(f"Chats:        {chat_count:,}")
    print(f"Attachments:  {attachment_count:,}")
    print(f"Contacts:     {handle_count:,}")
    print(f"Date range:   {first[0] if first else '?'} → {last[0] if last else '?'}")
    print(f"\nTop attachment types:")
    for mime, cnt in types:
        print(f"  {mime}: {cnt:,}")
    
    db.close()

def cmd_groups():
    """List group chats with message counts."""
    db = get_db()
    c = db.cursor()
    
    groups = c.execute("""
        SELECT c.display_name, c.chat_identifier, COUNT(cmj.message_id) as msg_count
        FROM chat c
        LEFT JOIN chat_message_join cmj ON c.ROWID = cmj.chat_id
        WHERE c.display_name IS NOT NULL AND c.display_name != ''
        GROUP BY c.ROWID
        ORDER BY msg_count DESC
    """).fetchall()
    
    print(f"\n💬 Group Chats ({len(groups)} found)")
    print(f"{'='*60}")
    for name, identifier, count in groups:
        print(f"  {count:>6,} msgs  {name}")
    
    db.close()

def cmd_export(group_name):
    """Export a group chat to JSON."""
    db = get_db()
    c = db.cursor()
    
    # Find the chat
    chat = c.execute("""
        SELECT ROWID, display_name, chat_identifier 
        FROM chat WHERE display_name LIKE ?
    """, (f"%{group_name}%",)).fetchone()
    
    if not chat:
        print(f"No group chat matching '{group_name}'")
        sys.exit(1)
    
    chat_id, display_name, identifier = chat
    
    # Get messages with sender info
    messages = c.execute("""
        SELECT 
            m.ROWID,
            datetime(m.date/1000000000 + 978307200, 'unixepoch', 'localtime') as timestamp,
            m.text,
            m.is_from_me,
            h.id as sender,
            m.cache_has_attachments
        FROM message m
        JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
        LEFT JOIN handle h ON m.handle_id = h.ROWID
        WHERE cmj.chat_id = ?
        ORDER BY m.date ASC
    """, (chat_id,)).fetchall()
    
    # Build export
    export = {
        "chat_name": display_name,
        "chat_identifier": identifier,
        "message_count": len(messages),
        "exported_at": datetime.now().isoformat(),
        "source": "imessage",
        "messages": []
    }
    
    for row_id, ts, text, is_from_me, sender, has_attachments in messages:
        msg = {
            "timestamp": ts,
            "text": text,
            "sender": "me" if is_from_me else sender,
            "attachments": []
        }
        
        if has_attachments:
            attachments = c.execute("""
                SELECT a.filename, a.mime_type, a.total_bytes
                FROM attachment a
                JOIN message_attachment_join maj ON a.ROWID = maj.attachment_id
                WHERE maj.message_id = ?
            """, (row_id,)).fetchall()
            
            for fname, mime, size in attachments:
                msg["attachments"].append({
                    "filename": fname,
                    "mime_type": mime,
                    "size_bytes": size
                })
        
        export["messages"].append(msg)
    
    # Save
    os.makedirs(EXPORT_DIR, exist_ok=True)
    safe_name = display_name.replace(" ", "_").replace("/", "_").lower()
    outfile = os.path.join(EXPORT_DIR, f"imessage_{safe_name}.json")
    
    with open(outfile, "w") as f:
        json.dump(export, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Exported {len(messages):,} messages from '{display_name}'")
    print(f"📁 {outfile}")
    print(f"\nReview the file before importing into Family Book.")
    
    db.close()

def cmd_media(group_name):
    """List media attachments in a group chat."""
    db = get_db()
    c = db.cursor()
    
    chat = c.execute("""
        SELECT ROWID, display_name FROM chat WHERE display_name LIKE ?
    """, (f"%{group_name}%",)).fetchone()
    
    if not chat:
        print(f"No group chat matching '{group_name}'")
        sys.exit(1)
    
    chat_id, display_name = chat
    
    media = c.execute("""
        SELECT a.filename, a.mime_type, a.total_bytes,
               datetime(m.date/1000000000 + 978307200, 'unixepoch', 'localtime') as ts,
               h.id as sender
        FROM attachment a
        JOIN message_attachment_join maj ON a.ROWID = maj.attachment_id
        JOIN message m ON maj.message_id = m.ROWID
        JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
        LEFT JOIN handle h ON m.handle_id = h.ROWID
        WHERE cmj.chat_id = ?
        AND a.mime_type LIKE 'image/%'
        ORDER BY m.date DESC
        LIMIT 50
    """, (chat_id,)).fetchall()
    
    print(f"\n📷 Recent photos in '{display_name}' ({len(media)} shown)")
    print(f"{'='*60}")
    for fname, mime, size, ts, sender in media:
        size_kb = (size or 0) // 1024
        short_name = os.path.basename(fname) if fname else "?"
        print(f"  {ts}  {sender or 'me':>15}  {size_kb:>6}KB  {short_name}")
    
    db.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    
    cmd = sys.argv[1]
    if cmd == "scan":
        cmd_scan()
    elif cmd == "groups":
        cmd_groups()
    elif cmd == "export" and len(sys.argv) >= 3:
        cmd_export(sys.argv[2])
    elif cmd == "media" and len(sys.argv) >= 3:
        cmd_media(sys.argv[2])
    else:
        print(__doc__)
