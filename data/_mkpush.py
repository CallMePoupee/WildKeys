import json
from pathlib import Path
files = [
  ".gitignore","LICENSE","README.md","Start WildKeys.bat","WildKeys-Setup.spec","WildKeys.spec",
  "build.bat","hotkeys.py","main.py","paths.py","requirements.txt",
  "single_instance.py","storage.py","worker.py","ui/app.js","ui/index.html","ui/minimize.svg","ui/styles.css","ui/x.svg",
  "installer/setup_app.py",
]
root = Path(r"C:\Users\Charlotte\WildKeys")
out = []
for f in files:
    p = root / f
    out.append({"path": f.replace("\\","/"), "content": p.read_text(encoding="utf-8", errors="replace")})
Path(r"C:\Users\Charlotte\WildKeys\data\_push_payload.json").write_text(json.dumps(out), encoding="utf-8")
print("files", len(out), "chars", sum(len(x["content"]) for x in out))
