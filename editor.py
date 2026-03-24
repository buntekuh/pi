"""
M56 Text Editor — standalone tkinter script.

Usage: python3 editor.py <tempfile> <title>

Opens a simple editor window. Ctrl+S saves and closes.
Ctrl+Q / closing the window discards changes.
"""

import sys
import tkinter as tk
from tkinter import font as tkfont

BG      = "#0a0a0a"
FG      = "#6FAAA6"
CURSOR  = "#6FAAA6"
SEL_BG  = "#1a3a3a"
FONT    = ("Courier New", 13)


def main():
    path  = sys.argv[1]
    title = sys.argv[2] if len(sys.argv) > 2 else path

    with open(path) as f:
        content = f.read()

    root = tk.Tk()
    root.title(f"M56  —  {title}")
    root.geometry("800x600")
    root.configure(bg=BG)

    # Toolbar label
    bar = tk.Label(root, text=f"  {title}    Ctrl+S save   Ctrl+Q discard",
                   bg="#111", fg="#4a7a77", font=("Courier New", 10),
                   anchor="w", padx=6, pady=4)
    bar.pack(fill=tk.X, side=tk.TOP)

    mono = tkfont.Font(family="Courier New", size=13)
    text = tk.Text(root, font=mono,
                   bg=BG, fg=FG,
                   insertbackground=CURSOR,
                   selectbackground=SEL_BG, selectforeground=FG,
                   relief=tk.FLAT, borderwidth=16,
                   wrap=tk.NONE, undo=True)
    text.pack(fill=tk.BOTH, expand=True)
    text.insert("1.0", content)
    text.mark_set("insert", "1.0")
    text.focus_set()

    # Scrollbars
    yscroll = tk.Scrollbar(text, command=text.yview, bg="#111",
                           troughcolor=BG, relief=tk.FLAT)
    yscroll.pack(side=tk.RIGHT, fill=tk.Y)
    text.configure(yscrollcommand=yscroll.set)

    def save_and_close(e=None):
        with open(path, "w") as f:
            f.write(text.get("1.0", "end-1c"))
        root.destroy()

    def discard(e=None):
        root.destroy()

    root.bind("<Control-s>", save_and_close)
    root.bind("<Control-q>", discard)

    root.mainloop()


if __name__ == "__main__":
    main()
