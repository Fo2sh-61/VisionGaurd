"""
Interactive camera setup.

Run once per installation (and again whenever a camera is added). For EVERY
camera it asks the two things the system cannot guess:

    1. which gate number this camera watches
    2. whether it sees vehicles entering, exiting, or both

Everything else has a sensible default. The wizard also test-opens each stream
so a wrong RTSP URL is caught during installation, not at 2am.
"""

from __future__ import annotations

import sys

from .config import CameraConfig, SystemConfig, RecognitionConfig, CONFIG_PATH

BAR = "─" * 62


def _input(prompt: str) -> str:
    """input() that fails cleanly when stdin runs out (piped/non-interactive)."""
    try:
        return input(prompt)
    except EOFError:
        print("\n\n⚠ انتهت المدخلات / no more input — الإعداد يحتاج طرفية تفاعلية."
              "\n  The wizard needs an interactive terminal. You can also copy"
              "\n  config/cameras.example.yaml to config/cameras.yaml and edit it.")
        raise SystemExit(1) from None


def _ask(prompt: str, default: str = "", required: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        val = _input(f"{prompt}{suffix}: ").strip()
        if not val:
            val = default
        if val or not required:
            return val
        print("  ⚠ هذا الحقل مطلوب / this field is required")


def _ask_int(prompt: str, default: int | None = None, minimum: int = 1) -> int:
    while True:
        raw = _ask(prompt, str(default) if default is not None else "")
        try:
            v = int(raw)
            if v < minimum:
                print(f"  ⚠ must be >= {minimum}")
                continue
            return v
        except ValueError:
            print("  ⚠ أدخل رقمًا / enter a number")


def _ask_choice(prompt: str, choices: dict[str, str], default: str) -> str:
    keys = list(choices)
    print(f"\n{prompt}")
    for i, k in enumerate(keys, 1):
        mark = " (default)" if k == default else ""
        print(f"   {i}) {choices[k]}{mark}")
    while True:
        raw = _input(f"اختر / choose 1-{len(keys)} [{keys.index(default) + 1}]: ").strip()
        if not raw:
            return default
        if raw.isdigit() and 1 <= int(raw) <= len(keys):
            return keys[int(raw) - 1]
        if raw in choices:
            return raw
        print("  ⚠ اختيار غير صحيح / invalid choice")


def _ask_yes(prompt: str, default: bool = True) -> bool:
    d = "Y/n" if default else "y/N"
    raw = _input(f"{prompt} [{d}]: ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes", "nعم", "نعم", "1")


def _test_source(source: str) -> tuple[bool, str]:
    """Bounded probe - never leaves the installer staring at a frozen prompt."""
    try:
        from .capture import probe

        return probe(source, timeout_ms=6000)
    except Exception as exc:
        return False, str(exc)


def add_camera(index: int, existing_ids: set[str]) -> CameraConfig:
    print(f"\n{BAR}\n  الكاميرا رقم {index}  /  CAMERA {index}\n{BAR}")

    name = _ask("اسم الكاميرا / camera name",
                f"كاميرا {index}", required=True)

    print("\nمصدر الكاميرا / camera source:")
    print("   • IP camera:  rtsp://user:pass@192.168.1.64:554/Streaming/Channels/101")
    print("   • USB webcam: 0")
    print("   • video file: /path/to/test.mp4")
    source = _ask("المصدر / source", "0", required=True)

    # -- the two questions that define what this camera MEANS -------------
    gate = _ask_int("\n★ رقم البوابة التي تراقبها هذه الكاميرا"
                    "\n★ Which GATE NUMBER does this camera watch?", 1)

    direction = _ask_choice(
        "★ هذه الكاميرا تصور السيارات الداخلة أم الخارجة؟"
        "\n★ Does this camera see vehicles ENTERING or EXITING?",
        {
            "entry": "دخول  /  ENTRY  (cars coming in)",
            "exit": "خروج  /  EXIT   (cars going out)",
            "both": "الاثنان / BOTH  (one camera for both ways — less accurate)",
        },
        "entry",
    )
    if direction == "both":
        print("  ℹ  ملاحظة: كاميرا واحدة للاتجاهين أقل دقة. "
              "يفضل كاميرا لكل اتجاه.")
        print("     Note: one camera for both directions is less reliable. "
              "Two cameras is better.")

    cam_id = _ask("معرّف قصير / short id",
                  f"gate{gate}_{direction}", required=True)
    n = 2
    base = cam_id
    while cam_id in existing_ids:
        cam_id = f"{base}_{n}"
        n += 1

    rotate = 0
    if _ask_yes("\nهل الكاميرا مركبة بزاوية مائلة؟ / Is the camera rotated?", False):
        rotate = int(_ask_choice("الدوران / rotation",
                                 {"90": "90°", "180": "180°", "270": "270°"}, "90"))

    cam = CameraConfig(id=cam_id, name=name, source=source, gate_number=gate,
                       direction=direction, rotate=rotate)

    if _ask_yes("\nاختبار الاتصال بالكاميرا الآن؟ / Test this camera now?", True):
        ok, info = _test_source(source)
        print(f"  {'✓ متصلة / connected — ' + info if ok else '✗ فشل / failed — ' + info}")
        if not ok and not _ask_yes("  المتابعة على أي حال؟ / Keep it anyway?", True):
            return add_camera(index, existing_ids)

    return cam


def run(existing: SystemConfig | None = None) -> SystemConfig:
    print(f"""
{BAR}
  نظام تسجيل دخول وخروج السيارات — الإعداد
  Vehicle Gate ANPR — setup wizard
{BAR}""")

    site = _ask("\nاسم الموقع / site name",
                existing.site_name if existing else "بوابة الموقع")

    cameras: list[CameraConfig] = list(existing.cameras) if existing else []
    if cameras:
        print(f"\nالكاميرات الحالية / existing cameras: {len(cameras)}")
        for c in cameras:
            print(f"   • {c.id}: بوابة {c.gate_number} / gate {c.gate_number} "
                  f"— {c.direction_ar} ({c.direction})")
        if not _ask_yes("الاحتفاظ بها؟ / Keep them?", True):
            cameras = []

    n_new = _ask_int("\nكم كاميرا تريد إضافتها؟ / How many cameras to add?",
                     0 if cameras else 1, minimum=0)
    for i in range(n_new):
        cameras.append(add_camera(len(cameras) + 1,
                                  {c.id for c in cameras}))

    if not cameras:
        print("\n⚠ لم تتم إضافة أي كاميرا. / No cameras configured.")

    rec = existing.recognition if existing else RecognitionConfig()
    cfg = SystemConfig(site_name=site, cameras=cameras, recognition=rec)
    if existing:
        cfg.web_port = existing.web_port
        cfg.collect_dataset = existing.collect_dataset

    # -- summary ----------------------------------------------------------
    print(f"\n{BAR}\n  الملخص / SUMMARY\n{BAR}")
    print(f"  الموقع / site: {site}")
    gates: dict[int, list[CameraConfig]] = {}
    for c in cameras:
        gates.setdefault(c.gate_number, []).append(c)
    for g in sorted(gates):
        print(f"\n  ▸ البوابة {g} / Gate {g}")
        for c in gates[g]:
            print(f"      {c.id:<18} {c.direction_ar:<10} ({c.direction})")
            print(f"      {'':<18} {c.source}")
        dirs = {c.direction for c in gates[g]}
        if dirs == {"entry"}:
            print("      ⚠ لا توجد كاميرا خروج لهذه البوابة — "
                  "لن يتم حساب مدة البقاء")
            print("      ⚠ no exit camera on this gate — stay duration "
                  "will not be calculated")
        elif dirs == {"exit"}:
            print("      ⚠ لا توجد كاميرا دخول لهذه البوابة "
                  "/ no entry camera on this gate")

    cfg.validate()
    path = cfg.save()
    print(f"\n{BAR}")
    print(f"✓ تم الحفظ / saved to: {path}")
    print("\nالخطوة التالية / next step:")
    print("    python run.py start")
    print(f"    ثم افتح / then open:  http://localhost:{cfg.web_port}")
    print(BAR)
    return cfg


def main() -> int:
    existing = None
    if CONFIG_PATH.exists():
        try:
            existing = SystemConfig.load()
        except Exception as exc:
            print(f"⚠ could not read existing config ({exc}); starting fresh")
    try:
        run(existing)
    except KeyboardInterrupt:
        print("\nألغيت / cancelled")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
