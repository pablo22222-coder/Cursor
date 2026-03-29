"""
ResourceThrottle — Controlador Adaptativo de Saturación del Sistema

Monitoriza CPU y RAM con psutil y escala los parámetros de ejecución
en tiempo real para evitar que el software sature el equipo.

Niveles de escalada (0 = máximo rendimiento, 5 = parada):
  Nivel 0 (Normal):      3 Workers · 3 Pestañas/worker
  Nivel 1 (Precaución):  3 Workers · 2 Pestañas/worker
  Nivel 2 (Reducido):    3 Workers · 1 Pestaña/worker
  Nivel 3 (Crítico):     2 Workers · 1 Pestaña/worker
  Nivel 4 (Supervivencia):1 Worker · 1 Pestaña/worker
  Nivel 5 (Parada):      0 Workers  → lanza StopIteration en pipeline

Reglas de transición:
  · Subir nivel  (bajar rendimiento) si CPU > 85% o RAM > 90% durante > 7s
  · Cooldown de 15s tras cada cambio de nivel antes de volver a evaluar
  · Bajar nivel  (recuperar velocidad) si carga baja y estable durante 30-45s
"""

import threading
import time
import collections
from typing import Callable, Dict, Any, List, Optional

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

# ── Umbrales de saturación ───────────────────────────────────────────────────
CPU_HIGH_THRESHOLD  = 85   # % — umbral "alto"
RAM_HIGH_THRESHOLD  = 90   # % — umbral "alto"
CPU_LOW_THRESHOLD   = 60   # % — umbral "bajo" (para recuperación)
RAM_LOW_THRESHOLD   = 70   # % — umbral "bajo" (para recuperación)

STRESS_WINDOW       = 7    # segundos de estrés sostenido para subir nivel
RECOVERY_WINDOW     = 35   # segundos de carga baja sostenida para bajar nivel
COOLDOWN            = 15   # segundos de espera tras cualquier cambio de nivel

POLL_INTERVAL       = 1.0  # segundos entre lecturas de psutil

# ── Tabla de configuración por nivel ────────────────────────────────────────
LEVEL_CONFIG: Dict[int, Dict[str, Any]] = {
    0: {"workers": 3, "tabs": 3, "label": "Normal",        "emoji": "🟢"},
    1: {"workers": 3, "tabs": 2, "label": "Precaución",    "emoji": "🟡"},
    2: {"workers": 3, "tabs": 1, "label": "Reducido",      "emoji": "🟠"},
    3: {"workers": 2, "tabs": 1, "label": "Crítico",       "emoji": "🔴"},
    4: {"workers": 1, "tabs": 1, "label": "Supervivencia", "emoji": "🆘"},
    5: {"workers": 0, "tabs": 0, "label": "PARADA",        "emoji": "💀"},
}
MAX_LEVEL = 5


class ResourceThrottle:
    """
    Objeto singleton compartido entre el pipeline y los workers de Playwright.
    Corre un hilo de fondo que lee CPU/RAM cada segundo y ajusta el nivel.

    Interfaz pública para el resto del código:
        throttle.current_level        → int 0-5
        throttle.workers              → int activos en este nivel
        throttle.tabs                 → int pestañas por worker
        throttle.should_stop          → bool (True si nivel == 5)
        throttle.history              → list de entradas de log
        throttle.status_dict()        → dict para /api/status
    """

    def __init__(self, on_level_change: Optional[Callable] = None):
        self._lock = threading.Lock()
        self._level = 0
        self._last_change_ts = 0.0   # timestamp del último cambio
        self._stress_since: Optional[float] = None   # cuándo empezó el estrés actual
        self._low_since:    Optional[float] = None   # cuándo empezó la calma actual
        self._history: List[str] = []
        self._cpu: float = 0.0
        self._ram: float = 0.0
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self.on_level_change = on_level_change   # callback(level, config)

    # ── Propiedades ──────────────────────────────────────────────────────────

    @property
    def current_level(self) -> int:
        with self._lock:
            return self._level

    @property
    def workers(self) -> int:
        with self._lock:
            return LEVEL_CONFIG[self._level]["workers"]

    @property
    def tabs(self) -> int:
        with self._lock:
            return LEVEL_CONFIG[self._level]["tabs"]

    @property
    def should_stop(self) -> bool:
        with self._lock:
            return self._level >= MAX_LEVEL

    @property
    def history(self) -> List[str]:
        with self._lock:
            return list(self._history[-20:])   # últimas 20 entradas

    @property
    def cpu(self) -> float:
        with self._lock:
            return self._cpu

    @property
    def ram(self) -> float:
        with self._lock:
            return self._ram

    def status_dict(self) -> Dict[str, Any]:
        with self._lock:
            cfg = LEVEL_CONFIG[self._level]
            return {
                "level":       self._level,
                "label":       cfg["label"],
                "emoji":       cfg["emoji"],
                "workers":     cfg["workers"],
                "tabs":        cfg["tabs"],
                "cpu":         round(self._cpu, 1),
                "ram":         round(self._ram, 1),
                "history":     list(self._history[-10:]),
                "psutil_ok":   PSUTIL_AVAILABLE,
            }

    # ── Ciclo de vida del hilo de monitorización ──────────────────────────────

    def start(self):
        """Arranca el hilo de fondo. Idempotente."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="ResourceThrottle-Monitor"
        )
        self._thread.start()

    def stop(self):
        """Detiene el hilo de fondo."""
        self._running = False

    # ── Hilo de monitorización ────────────────────────────────────────────────

    def _monitor_loop(self):
        if not PSUTIL_AVAILABLE:
            self._log("⚠️ psutil no disponible — throttle desactivado, nivel fijo 0")
            return

        while self._running:
            try:
                cpu = psutil.cpu_percent(interval=None)
                ram = psutil.virtual_memory().percent
                now = time.monotonic()

                with self._lock:
                    self._cpu = cpu
                    self._ram = ram
                    level = self._level
                    last_change = self._last_change_ts

                in_cooldown = (now - last_change) < COOLDOWN
                is_stressed = cpu > CPU_HIGH_THRESHOLD or ram > RAM_HIGH_THRESHOLD
                is_calm     = cpu < CPU_LOW_THRESHOLD and ram < RAM_LOW_THRESHOLD

                # Actualizar ventanas de tiempo
                with self._lock:
                    if is_stressed:
                        if self._stress_since is None:
                            self._stress_since = now
                        self._low_since = None
                    else:
                        self._stress_since = None

                    if is_calm:
                        if self._low_since is None:
                            self._low_since = now
                    else:
                        self._low_since = None

                    stress_secs   = (now - self._stress_since) if self._stress_since else 0
                    recovery_secs = (now - self._low_since)    if self._low_since    else 0

                if not in_cooldown:
                    if stress_secs >= STRESS_WINDOW and level < MAX_LEVEL:
                        self._escalate_up(level, cpu, ram)
                    elif recovery_secs >= RECOVERY_WINDOW and level > 0:
                        self._escalate_down(level, cpu, ram)

            except Exception as e:
                self._log(f"Monitor error: {e}")

            time.sleep(POLL_INTERVAL)

    # ── Transiciones de nivel ─────────────────────────────────────────────────

    def _escalate_up(self, current: int, cpu: float, ram: float):
        new_level = current + 1
        cfg = LEVEL_CONFIG[new_level]
        msg = (
            f"⚠️ Saturación detectada (CPU {cpu:.0f}% / RAM {ram:.0f}%) → "
            f"Activando Nivel {new_level} ({cfg['emoji']} {cfg['label']} · "
            f"{cfg['workers']} workers / {cfg['tabs']} tabs)"
        )
        self._apply_level(new_level, msg)

    def _escalate_down(self, current: int, cpu: float, ram: float):
        new_level = current - 1
        cfg = LEVEL_CONFIG[new_level]
        msg = (
            f"✅ Sistema estable (CPU {cpu:.0f}% / RAM {ram:.0f}%) → "
            f"Recuperando Nivel {new_level} ({cfg['emoji']} {cfg['label']} · "
            f"{cfg['workers']} workers / {cfg['tabs']} tabs)"
        )
        self._apply_level(new_level, msg)

    def _apply_level(self, new_level: int, msg: str):
        with self._lock:
            self._level = new_level
            self._last_change_ts = time.monotonic()
            self._stress_since = None
            self._low_since = None
            self._log(msg)
        print(f"[Throttle] {msg}")
        if self.on_level_change:
            try:
                self.on_level_change(new_level, LEVEL_CONFIG[new_level])
            except Exception:
                pass

    def _log(self, msg: str):
        """Añade entrada al historial (thread-safe si se llama con _lock ya adquirido)."""
        ts = time.strftime("%H:%M:%S")
        entry = f"[{ts}] {msg}"
        self._history.append(entry)
        if len(self._history) > 50:
            self._history.pop(0)


# ── Instancia singleton global ────────────────────────────────────────────────
_throttle: Optional[ResourceThrottle] = None
_throttle_lock = threading.Lock()


def get_throttle() -> ResourceThrottle:
    """Devuelve (y crea si hace falta) el singleton de ResourceThrottle."""
    global _throttle
    with _throttle_lock:
        if _throttle is None:
            _throttle = ResourceThrottle()
            _throttle.start()
        return _throttle


def reset_throttle():
    """Reinicia el throttle al nivel 0 (llamar al inicio de cada búsqueda)."""
    global _throttle
    with _throttle_lock:
        if _throttle is not None:
            _throttle.stop()
        _throttle = ResourceThrottle()
        _throttle.start()
    return _throttle
