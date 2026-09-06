#!/usr/bin/env python3
"""Absolute mouse/keyboard driving for the macOS guest via the QEMU monitor."""
import socket, sys, time
S = "/home/bogdan/macos-vm/run/monitor.sock"
_s = socket.socket(socket.AF_UNIX); _s.connect(S); _s.settimeout(0.02)
def cmd(c, w=0.35):
    _s.sendall((c + "\n").encode()); time.sleep(w)
    try:                       # drain the echo without blocking
        while _s.recv(65536):
            pass
    except Exception: pass
def moveto(x, y):
    cmd("mouse_move -6000 -6000", 0.7)   # pin to origin; HMP mouse_move is relative
    cmd(f"mouse_move {x} {y}", 0.7)
def click(x, y, settle=1.2):
    moveto(x, y); cmd("mouse_button 1", 0.35); cmd("mouse_button 0", settle)
SHIFT = {"!":"1","@":"2","#":"3","$":"4","%":"5","^":"6","&":"7","*":"8","(":"9",")":"0",
         "_":"minus","+":"equal","{":"bracket_left","}":"bracket_right","|":"backslash",
         ":":"semicolon",'"':"apostrophe","<":"comma",">":"dot","?":"slash","~":"grave_accent"}
PLAIN = {" ":"spc","-":"minus","=":"equal","[":"bracket_left","]":"bracket_right",
         "\\":"backslash",";":"semicolon","'":"apostrophe",",":"comma",".":"dot",
         "/":"slash","`":"grave_accent","\n":"ret"}
def typestr(t):
    for ch in t:
        if ch.isupper():      cmd(f"sendkey shift-{ch.lower()}", 0.045)
        elif ch in SHIFT:     cmd(f"sendkey shift-{SHIFT[ch]}", 0.045)
        elif ch in PLAIN:     cmd(f"sendkey {PLAIN[ch]}", 0.045)
        else:                 cmd(f"sendkey {ch}", 0.045)
if __name__ == "__main__":
    a = sys.argv[1:]
    while a:
        op = a.pop(0)
        if op == "click":   click(int(a.pop(0)), int(a.pop(0)))
        elif op == "move":  moveto(int(a.pop(0)), int(a.pop(0)))
        elif op == "type":  typestr(a.pop(0))
        elif op == "enter": cmd("sendkey ret", 0.4)
        elif op == "key":   cmd("sendkey " + a.pop(0), 0.4)
        elif op == "wait":  time.sleep(float(a.pop(0)))
