"""Persistent storage for shortcut lists."""

from __future__ import annotations

import json
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any

from paths import data_dir

DATA_PATH = data_dir() / "lists.json"
STATUS_PATH = data_dir() / "status.json"

# QWERTY order, left→right then top→bottom (top row, then home row).
# E/O/P replaced with D/G/K.
KEYS = list("qwrtyuidgk")

# Old top-row letters → new bindings (lists migrate on load).
LEGACY_KEY_MAP = {"e": "d", "o": "g", "p": "k"}

HOTKEY_STATUS = "Hotkeys armed · Ctrl+Alt+Q W R T Y U I D G K"


def format_paste_line(text: str) -> str:
    """Ensure pasted prompt fragments end with comma + space for chaining."""
    cleaned = str(text).rstrip("\r\n").rstrip()
    if cleaned.endswith(","):
        return cleaned + " "
    return cleaned + ", "

DEFAULT_LABELS = {
    "q": "Shot type",
    "w": "Camera angle",
    "r": "Lighting",
    "t": "Pose",
    "y": "Background",
    "u": "Art style",
    "i": "Hair",
    "d": "Expression",
    "g": "Wardrobe",
    "k": "Details",
}

# Default lines for AI portrait prompt building (one idea per line)
DEFAULT_LINES: dict[str, list[str]] = {
    "q": [
        "extreme close-up portrait, eyes and lips filling the frame",
        "tight headshot from collarbones up, centered face",
        "classic portrait head-and-shoulders crop",
        "three-quarter portrait, chest-up framing",
        "medium portrait, waist-up composition",
        "full-body portrait standing, feet in frame",
        "environmental portrait with subject in a larger scene",
        "profile portrait, full side view of the face",
        "over-the-shoulder portrait looking back toward camera",
        "candid street-style portrait with slight crop asymmetry",
    ],
    "w": [
        "eye-level camera, natural neutral perspective",
        "slightly low angle looking up, subtle hero feel",
        "slightly high angle looking down, soft intimate feel",
        "dutch angle, gentle cinematic tilt",
        "straight-on front-facing camera",
        "three-quarter camera angle to the subject’s right",
        "three-quarter camera angle to the subject’s left",
        "top-down bird’s-eye crop on face and shoulders",
        "worm’s-eye dramatic upward look",
        "long-lens compressed perspective, background softly stacked",
    ],
    "d": [
        "soft closed-mouth smile, warm eyes",
        "broad genuine laugh, joyful eyes",
        "neutral calm expression, relaxed face",
        "serious contemplative look, quiet intensity",
        "subtle smirk, confident micro-expression",
        "surprised open expression, raised brows",
        "wistful distant gaze, soft melancholy",
        "fierce direct stare, strong eye contact",
        "dreamy half-lidded look, gentle softness",
        "playful raised eyebrow, light curiosity",
    ],
    "r": [
        "soft window light from camera left, gentle falloff",
        "Rembrandt lighting with a triangular cheek highlight",
        "butterfly / paramount beauty lighting from above front",
        "split lighting, half face in light half in shadow",
        "golden hour warm sunlight, long soft shadows",
        "overcast daylight, even soft diffusion",
        "studio softbox key with subtle fill, clean portrait light",
        "rim light from behind separating subject from background",
        "neon mixed practicals, magenta and cyan accents",
        "candlelit warm low-key glow, intimate contrast",
        "hard noon sunlight, crisp shadows, high contrast",
        "moonlit cool blue night ambience",
    ],
    "t": [
        "facing camera square, shoulders relaxed",
        "chin slightly down, eyes up toward lens",
        "chin slightly up, confident open posture",
        "head tilted gently to one side",
        "looking off-camera to the side, thoughtful",
        "looking over one shoulder toward camera",
        "hands framing the face lightly",
        "hand near jawline, elegant portrait pose",
        "arms crossed loosely, casual confidence",
        "seated, leaning slightly forward toward camera",
        "standing contrapposto, natural weight shift",
        "walking toward camera, mid-stride candid freeze",
    ],
    "y": [
        "seamless light gray studio backdrop",
        "seamless deep charcoal studio backdrop",
        "soft cream paper backdrop with gentle gradient",
        "blurred city bokeh lights at night",
        "sunlit indoor room with window and sheer curtains",
        "minimalist white loft with soft shadows",
        "lush green garden bokeh background",
        "misty forest path fading into depth",
        "coastal cliffs and soft ocean haze",
        "moody library shelves softly out of focus",
        "neon-lit rainy street reflections",
        "abstract gradient backdrop, clean modern color field",
    ],
    "u": [
        "photorealistic DSLR portrait, natural skin texture",
        "cinematic still, anamorphic lens character, filmic color",
        "editorial fashion portrait, high-end magazine look",
        "fine-art oil painting portrait, visible brushwork",
        "soft watercolor portrait, delicate washes",
        "classic charcoal sketch portrait on textured paper",
        "anime-inspired portrait, clean lines, expressive eyes",
        "3D render portrait, subsurface skin, studio quality",
        "vintage film portrait, 35mm grain, slight halation",
        "black and white fine-art portrait, rich midtones",
        "hyper-detailed fantasy portrait illustration",
        "Polaroid instant-film aesthetic, soft contrast",
    ],
    "i": [
        "long wavy hair cascading over shoulders",
        "straight sleek shoulder-length hair",
        "short textured pixie cut",
        "neat bob with clean ends",
        "curly afro volume, natural texture",
        "tight coils and defined curls",
        "loose beach waves, sunlit strands",
        "braided crown with soft face-framing pieces",
        "high ponytail, polished and sharp",
        "low bun with a few loose strands",
        "undercut with longer top swept back",
        "buzz cut, clean and minimal",
        "silver streaks mixed into dark hair",
        "wet-look hair, sleek and reflective",
    ],
    "g": [
        "simple black turtleneck, minimalist elegance",
        "crisp white button-up shirt, collar open",
        "oversized linen shirt in soft beige",
        "tailored charcoal blazer over a tee",
        "vintage leather jacket, lived-in texture",
        "knit sweater with gentle ribbing",
        "silk slip top with subtle sheen",
        "structured coat with strong shoulders",
        "casual hoodie, relaxed everyday look",
        "formal tuxedo shirt and black bow tie",
        "cultural ceremonial attire, rich fabric detail",
        "athletic zip jacket, clean sporty lines",
        "off-shoulder top, soft romantic drape",
        "denim jacket over a plain tee",
    ],
    "k": [
        "natural freckles across the nose and cheeks",
        "light makeup, dewy skin finish",
        "bold graphic eyeliner, modern editorial",
        "thin metal-frame glasses",
        "small gold hoop earrings",
        "delicate layered necklaces",
        "subtle beauty mark near the lip",
        "soft film grain overlay",
        "shallow depth of field, creamy bokeh",
        "catchlights in both eyes, lively sparkle",
        "slight motion blur in hair strands only",
        "hand-painted texture on skin highlights",
        "muted color grade, desaturated secondary tones",
        "high-clarity micro-contrast on eyes and lips",
    ],
}


def _blank_state() -> dict[str, Any]:
    return {
        "enabled": True,
        "keys": {
            k: {
                "label": DEFAULT_LABELS[k],
                "lines": list(DEFAULT_LINES.get(k) or []),
                "enabled": True,
            }
            for k in KEYS
        },
    }


def write_status(message: str, extra: dict[str, Any] | None = None) -> None:
    """Best-effort status file for UI polling (worker-safe)."""
    payload: dict[str, Any] = {
        "message": message,
        "ts": __import__("time").time(),
    }
    if extra:
        payload.update(extra)
    try:
        STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATUS_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(STATUS_PATH)
    except OSError:
        pass


def read_status() -> dict[str, Any]:
    try:
        if STATUS_PATH.exists():
            return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return {"message": "Ready", "ts": 0}


class Store:
    def __init__(self, path: Path = DATA_PATH) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._data = _blank_state()
        self._mtime: float = 0.0
        self.load()

    def load(self) -> None:
        with self._lock:
            if not self.path.exists():
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self._data = _blank_state()
                self._write()
                self._mtime = self._file_mtime()
                return
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                had_legacy = any(
                    old in (raw.get("keys") or {}) and new not in (raw.get("keys") or {})
                    for old, new in LEGACY_KEY_MAP.items()
                )
                self._data = self._normalize(raw)
                self._mtime = self._file_mtime()
                if had_legacy:
                    # Persist e/o/p → d/g/k remap so files stay current
                    self._write()
            except (json.JSONDecodeError, OSError):
                self._data = _blank_state()

    def reload_if_changed(self) -> bool:
        """Reload from disk when another process saved. Returns True if reloaded."""
        mtime = self._file_mtime()
        if mtime <= 0:
            return False
        with self._lock:
            if mtime == self._mtime:
                return False
        self.load()
        return True

    def _file_mtime(self) -> float:
        try:
            return self.path.stat().st_mtime
        except OSError:
            return 0.0

    def revision(self) -> float:
        return self._file_mtime()

    def _normalize(self, raw: dict[str, Any]) -> dict[str, Any]:
        base = _blank_state()
        base["enabled"] = bool(raw.get("enabled", True))
        keys = raw.get("keys") or {}
        # Fold legacy e/o/p entries into d/g/k when the new slot is empty
        for old, new in LEGACY_KEY_MAP.items():
            if old in keys and new not in keys:
                keys[new] = keys[old]
        for k in KEYS:
            item = keys.get(k) or {}
            label = str(item.get("label") or DEFAULT_LABELS[k]).strip() or DEFAULT_LABELS[k]
            lines_raw = item.get("lines") or []
            lines: list[str] = []
            if isinstance(lines_raw, list):
                for line in lines_raw:
                    text = str(line).rstrip("\r\n")
                    if text.strip():
                        lines.append(text)
            # Missing key defaults to on (back-compat with older lists.json)
            key_enabled = bool(item.get("enabled", True))
            base["keys"][k] = {
                "label": label,
                "lines": lines,
                "enabled": key_enabled,
            }
        # Remembered per-key states while Armed is off
        snap_raw = raw.get("armed_snapshot")
        if isinstance(snap_raw, dict):
            migrated_snap = dict(snap_raw)
            for old, new in LEGACY_KEY_MAP.items():
                if old in migrated_snap and new not in migrated_snap:
                    migrated_snap[new] = migrated_snap[old]
            base["armed_snapshot"] = {
                k: bool(migrated_snap.get(k, True)) for k in KEYS
            }
        return base

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        tmp.replace(self.path)
        self._mtime = self._file_mtime()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._data)

    def is_enabled(self) -> bool:
        with self._lock:
            return bool(self._data.get("enabled", True))

    def set_enabled(self, enabled: bool) -> dict[str, Any]:
        """
        Armed master switch.
        - Off: snapshot each shortcut's on/off, then turn all shortcuts off.
        - On: restore the snapshotted on/off states.
        """
        enabled = bool(enabled)
        with self._lock:
            currently = bool(self._data.get("enabled", True))
            if not enabled and currently:
                # Turning Armed off — remember, then clear all row toggles
                self._data["armed_snapshot"] = {
                    k: bool(self._data["keys"][k].get("enabled", True)) for k in KEYS
                }
                for k in KEYS:
                    self._data["keys"][k]["enabled"] = False
            elif enabled and not currently:
                # Turning Armed on — restore remembered row toggles
                snap = self._data.get("armed_snapshot")
                if isinstance(snap, dict):
                    for k in KEYS:
                        if k in snap:
                            self._data["keys"][k]["enabled"] = bool(snap[k])
                self._data.pop("armed_snapshot", None)
            self._data["enabled"] = enabled
            self._write()
            return deepcopy(self._data)

    def get_lines(self, key: str) -> list[str]:
        key = key.lower()
        with self._lock:
            item = self._data["keys"].get(key)
            if not item:
                return []
            return list(item.get("lines") or [])

    def is_key_enabled(self, key: str) -> bool:
        key = key.lower()
        with self._lock:
            item = self._data["keys"].get(key) or {}
            return bool(item.get("enabled", True))

    def set_key_enabled(self, key: str, enabled: bool) -> dict[str, Any]:
        key = key.lower()
        if key not in KEYS:
            raise ValueError(f"Unknown key: {key}")
        enabled = bool(enabled)
        with self._lock:
            # Individual shortcuts can only be turned on while global Armed is on.
            if enabled and not bool(self._data.get("enabled", True)):
                raise ValueError("Turn Armed on before enabling a shortcut")
            self._data["keys"][key]["enabled"] = enabled
            self._write()
            return deepcopy(self._data)

    def update_key(
        self,
        key: str,
        *,
        label: str | None = None,
        lines: list[str] | None = None,
        enabled: bool | None = None,
    ) -> dict[str, Any]:
        key = key.lower()
        if key not in KEYS:
            raise ValueError(f"Unknown key: {key}")
        with self._lock:
            item = self._data["keys"][key]
            if label is not None:
                cleaned = label.strip()
                if not cleaned:
                    raise ValueError("List name cannot be empty")
                item["label"] = cleaned
            if lines is not None:
                item["lines"] = [
                    str(line).rstrip("\r\n")
                    for line in lines
                    if str(line).strip()
                ]
            if enabled is not None:
                item["enabled"] = bool(enabled)
            self._write()
            return deepcopy(self._data)
