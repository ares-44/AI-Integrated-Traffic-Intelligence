from pathlib import Path
import shutil

p = Path("dashboard/app.py")
s = p.read_text(encoding="utf-8-sig")

marker = "</style>"
if marker not in s:
    raise SystemExit("CSS style block not found; file unchanged.")

if "ps06-header-city-image" in s:
    print("Header image styling is already installed.")
else:
    css = """
/* Subtle city-traffic image in the top-right of the existing header */
.ps06-headerbar {
    position: relative;
    overflow: hidden;
    isolation: isolate;
}
.ps06-headerbar::after {
    content: "";
    position: absolute;
    z-index: -1;
    top: 0;
    right: 0;
    width: 36%;
    height: 100%;
    background-image:
        linear-gradient(90deg, #101722 0%, rgba(16,23,34,.38) 45%, rgba(16,23,34,.12) 100%),
        url("https://images.unsplash.com/photo-1519608487953-e999c86e7455?auto=format&fit=crop&w=1000&q=85");
    background-size: cover;
    background-position: center 55%;
    opacity: .82;
    pointer-events: none;
}
.ps06-headerbar > * {
    position: relative;
    z-index: 1;
}
"""
    shutil.copy2(p, p.with_name("app.py.before_header_image_backup"))
    s = s.replace(marker, css + "\n" + marker, 1)
    compile(s, str(p), "exec")
    p.write_text(s, encoding="utf-8")
    print("Added top-right header image styling.")
    print("Backup: dashboard/app.py.before_header_image_backup")
