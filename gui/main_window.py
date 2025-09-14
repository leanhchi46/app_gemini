"""
Giao diện chính, điều phối các tab (Report, Prompt, Options, Chart)
"""

def run_app():
    import tkinter as tk
    from gemini_batch_image_analyzer import GeminiFolderOnceApp
    root = tk.Tk()
    app = GeminiFolderOnceApp(root)
    root.mainloop()