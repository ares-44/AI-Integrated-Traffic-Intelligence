from pathlib import Path
import shutil

p = Path("dashboard/app.py")
s = p.read_text(encoding="utf-8-sig")

backup = p.with_name("app.py.before_header_scale_backup")
if not backup.exists():
    shutil.copy2(p, backup)

css = """
/* Larger PS06 hero banner and readable heading */
.ps06-headerbar {
    min-height: 175px !important;
    padding: 36px 40px !important;
    border-radius: 22px !important;
}
.ps06-headerbar h1 {
    font-size: clamp(2rem, 3.2vw, 3rem) !important;
    line-height: 1.25 !important;
    font-weight: 850 !important;
    letter-spacing: -0.5px !important;
    max-width: 85% !important;
}
.ps06-headerbar p {
    font-size: clamp(1.05rem, 1.45vw, 1.35rem) !important;
    line-height: 1.55 !important;
    font-weight: 500 !important;
}
.ps06-headerbar::after {
    width: 43% !important;
    min-height: 175px !important;
    background-position: center !important;
}
@media (max-width: 700px) {
    .ps06-headerbar {
        min-height: 145px !important;
        padding: 25px 20px !important;
    }
    .ps06-headerbar h1 {
        font-size: 1.7rem !important;
        max-width: 100% !important;
    }
    .ps06-headerbar p {
        font-size: 1rem !important;
    }
}
"""

marker = "</style>"
if "Larger PS06 hero banner and readable heading" not in s:
    if marker not in s:
        raise SystemExit("CSS block not found; no changes made.")
    s = s.replace(marker, css + "\n" + marker, 1)

compile(s, str(p), "exec")
p.write_text(s, encoding="utf-8")
print("Header styling updated; syntax check passed.")
print(f"Backup: {backup}")
