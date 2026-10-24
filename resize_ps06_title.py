from pathlib import Path
import shutil

p = Path("dashboard/app.py")
s = p.read_text(encoding="utf-8-sig")

backup = p.with_name("app.py.before_title_text_resize_backup")
if not backup.exists():
    shutil.copy2(p, backup)

css = """
/* PS06 title and subtitle: larger, clearer, presentation-ready */
.ps06-headerbar h1 {
    font-size: clamp(2.4rem, 3.5vw, 3.5rem) !important;
    line-height: 1.2 !important;
    font-weight: 850 !important;
    letter-spacing: -0.7px !important;
    max-width: 100% !important;
}
.ps06-headerbar p {
    font-size: clamp(1.15rem, 1.5vw, 1.45rem) !important;
    line-height: 1.5 !important;
    font-weight: 500 !important;
}
"""

if "PS06 title and subtitle: larger, clearer" not in s:
    marker = "</style>"
    if marker not in s:
        raise SystemExit("Could not find the CSS style block; file unchanged.")
    s = s.replace(marker, css + "\n" + marker, 1)
    compile(s, str(p), "exec")
    p.write_text(s, encoding="utf-8")
    print("Title and subtitle enlarged successfully.")
else:
    print("Title enlargement is already installed.")
