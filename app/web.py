"""Shared web helpers: templates, login check, flash messages, the demo date."""
import os
from datetime import date
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from .services.metrics import lakh, rupees

HERE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(HERE / "templates"))

# The demo world is frozen on one day so the story stays the same for every visitor.
TODAY = date.fromisoformat(os.getenv("DEMO_TODAY", "2026-11-12"))

PHOTO_CREDITS = {
    "hero-factory.jpg": "Prince Prabhakaran", "loom-workers.jpg": "Ryo Harianto", "fabric-rolls.jpg": "Bernd Dittrich",
    "fabric-rolls-pattern.jpg": "Bernd Dittrich", "saree-red.jpg": "Bulbul Ahmed", "saree-embroidered.jpg": "Richard Williams",
    "school-shirt.jpg": "Nimble Made", "shirts-colour-rack.jpg": "Parker Burchfield", "navy-fabric.jpg": "Tim Mossholder",
    "flag-tricolour.jpg": "Onkarphoto", "flag-sky.jpg": "Saradasish Pradhan", "white-textile.jpg": "Ethan Bodnar",
    "thread-lot.jpg": "Eric Muhr", "spools-rack.jpg": "CR", "cotton.jpg": "Ranurte", "sewing-hands.jpg": "Phil Hearing",
    "fabric-shelves.jpg": "Matin Hosseini", "blue-shirts.jpg": "AZUKI .V", "spools-dark.jpg": "Vishal Banik",
}


def num(x, digits=0) -> str:
    if x is None:
        return "–"
    return f"{x:,.{digits}f}"


def icon(name: str, size: int = 18) -> Markup:
    paths = {
        "search": '<circle cx="11" cy="11" r="7"></circle><path d="M20 20l-3.5-3.5"></path>',
        "bell": '<path d="M6 8a6 6 0 1 1 12 0c0 7 3 8 3 8H3s3-1 3-8"></path><path d="M10 20a2 2 0 0 0 4 0"></path>',
        "chev": '<path d="M9 6l6 6-6 6"></path>',
        "plus": '<path d="M12 5v14M5 12h14"></path>',
        "arrow": '<path d="M5 12h14M13 6l6 6-6 6"></path>',
        "button": '<circle cx="12" cy="12" r="8"></circle><circle cx="10" cy="10" r="1"></circle><circle cx="14" cy="10" r="1"></circle><circle cx="10" cy="14" r="1"></circle><circle cx="14" cy="14" r="1"></circle>',
        "bag": '<path d="M6 8h12l-1 12H7L6 8z"></path><path d="M9 8V6a3 3 0 0 1 6 0v2"></path>',
        "alert": '<path d="M12 3l9.5 17h-19L12 3z"></path><path d="M12 10v4M12 17.5v.01"></path>',
        "check": '<path d="M5 12.5l4.5 4.5L19 7.5"></path>',
        "lock": '<rect x="5" y="11" width="14" height="10" rx="2"></rect><path d="M8 11V8a4 4 0 0 1 8 0v3"></path>',
        "box": '<path d="M3 7l9-4 9 4-9 4-9-4z"></path><path d="M3 7v10l9 4 9-4V7"></path><path d="M12 11v10"></path>',
        "drop": '<path d="M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11z"></path>',
        "grid": '<rect x="4" y="4" width="7" height="7" rx="1.5"></rect><rect x="13" y="4" width="7" height="7" rx="1.5"></rect><rect x="4" y="13" width="7" height="7" rx="1.5"></rect><rect x="13" y="13" width="7" height="7" rx="1.5"></rect>',
        "spool": '<path d="M6 4h12M6 20h12"></path><path d="M8 4v16M16 4v16"></path><path d="M8 8l8 3M8 12l8 3M8 16l8 1"></path>',
        "download": '<path d="M12 4v11M7 10l5 5 5-5"></path><path d="M5 20h14"></path>',
    }
    return Markup(f'<svg aria-hidden="true" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
                  f'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{paths[name]}</svg>')


templates.env.globals.update(icon=icon, today=TODAY, credits=PHOTO_CREDITS)
templates.env.filters.update(lakh=lakh, rupees=rupees, num=num,
                             dmy=lambda d: f"{d.day} {d:%b %Y}" if d else "–",   # %-d does not work on Windows
                             dm=lambda d: f"{d.day} {d:%b}" if d else "–")


def flash(request: Request, text: str, kind: str = "ok") -> None:
    request.session.setdefault("flash", []).append({"text": text, "kind": kind})


def render(request: Request, name: str, **ctx):
    ctx["flashes"] = request.session.pop("flash", [])
    ctx["user"] = request.session.get("user")
    return templates.TemplateResponse(request, name, ctx)


class NotSignedIn(Exception):
    pass


def require_user(request: Request) -> dict:
    """Dependency for every page except the sign-in page."""
    user = request.session.get("user")
    if not user:
        raise NotSignedIn()
    return user
